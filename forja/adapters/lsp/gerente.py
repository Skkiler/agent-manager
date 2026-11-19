"""Servidores de linguagem (LSP) para o editor do painel: Python, JavaScript/TypeScript, HTML, CSS e C# (ADR-027).

- Opcional e local: nenhum servidor vem instalado. O usuario instala pela tela (Configuracoes > Editor) e a Forja guarda tudo em
  `<dados>/lsp` (npm --prefix; `dotnet tool --tool-path` para C#), sem mexer no Node/.NET globais. Tambem usa um servidor que ja
  esteja no PATH.
- Sob demanda: o processo so sobe quando um arquivo daquela linguagem pede completar/explicar/definicao/diagnostico; fica
  ocioso no maximo `ocioso_s` e no maximo `max_servidores` ao mesmo tempo (o mais antigo e encerrado). Perfil 16 GB: 2.
- So para o USUARIO no painel (nunca para agentes). Raiz = pasta do projeto; ambiente = o do usuario sem APP_*/FORJA_*.
- Posicoes em UTF-16 (padrao do LSP), as mesmas do editor em JavaScript.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from forja.adapters.lsp.cliente import ClienteLsp, ErroLsp

log = logging.getLogger("forja.lsp")
WINDOWS = os.name == "nt"
MAX_ITENS = 150
MAX_TEXTO_DOC = 3000


@dataclass(frozen=True)
class DefServidor:
    id: str
    rotulo: str
    linguagens: tuple[str, ...]  # linguagens do editor atendidas
    executavel: str
    args: tuple[str, ...] = ()
    npm: tuple[str, ...] = ()  # pacotes instalados em <dados>/lsp
    dotnet: str = ""  # ferramenta .NET instalada em <dados>/lsp/dotnet
    alternativas: tuple[tuple[str, tuple[str, ...]], ...] = ()  # outros executaveis aceitos no PATH
    opcoes_init: dict[str, Any] = field(default_factory=dict)
    requisito: str = ""


SERVIDORES: tuple[DefServidor, ...] = (
    DefServidor("python", "Pyright (Python)", ("python",), "pyright-langserver", ("--stdio",), npm=("pyright",),
                alternativas=(("basedpyright-langserver", ("--stdio",)), ("pylsp", ()), ("jedi-language-server", ())), requisito="Node.js (npm)"),
    DefServidor("typescript", "TypeScript/JavaScript", ("javascript", "typescript"), "typescript-language-server", ("--stdio",),
                # typescript@5: o TypeScript 7 (porta nativa) nao traz lib/tsserver.js, que o typescript-language-server usa (medido)
                npm=("typescript-language-server", "typescript@5"), requisito="Node.js (npm)"),
    DefServidor("html", "HTML (VS Code)", ("html",), "vscode-html-language-server", ("--stdio",), npm=("vscode-langservers-extracted",),
                opcoes_init={"provideFormatter": False, "embeddedLanguages": {"css": True, "javascript": True}}, requisito="Node.js (npm)"),
    DefServidor("css", "CSS (VS Code)", ("css",), "vscode-css-language-server", ("--stdio",), npm=("vscode-langservers-extracted",),
                opcoes_init={"provideFormatter": False}, requisito="Node.js (npm)"),
    DefServidor("csharp", "C# (csharp-ls)", ("csharp",), "csharp-ls", (), dotnet="csharp-ls",
                alternativas=(("OmniSharp", ("-lsp",)),), requisito=".NET SDK 8+ (dotnet)"),
)
ID_LINGUAGEM = {"python": "python", "javascript": "javascript", "typescript": "typescript", "html": "html", "css": "css", "csharp": "csharp"}
_TIPOS = {1: "palavra", 2: "metodo", 3: "funcao", 4: "classe", 5: "propriedade", 6: "palavra", 7: "classe", 8: "classe", 9: "modulo",
          10: "propriedade", 11: "valor", 12: "valor", 13: "classe", 14: "palavra-chave", 15: "trecho", 16: "valor", 17: "palavra",
          20: "constante", 21: "constante", 22: "classe", 25: "classe"}
_SEVERIDADE = {1: "erro", 2: "aviso", 3: "info", 4: "dica"}


def snippet_lsp(texto: str) -> str:
    """Trecho do LSP ($1, ${1:x}, ${1|a,b|}, $0) no formato do editor (${x} = campo, ${0} = cursor, $${ = '${' literal)."""
    saida, i, n = [], 0, len(texto)
    while i < n:
        c = texto[i]
        if c == "\\" and i + 1 < n:
            saida.append("$${" if texto[i + 1] == "$" and i + 2 < n and texto[i + 2] == "{" else texto[i + 1])
            i += 3 if saida[-1] == "$${" else 2
            continue
        if c == "$" and i + 1 < n and texto[i + 1].isdigit():
            j = i + 1
            while j < n and texto[j].isdigit():
                j += 1
            saida.append("${0}" if texto[i + 1:j] == "0" else "${}")
            i = j
            continue
        if c == "$" and i + 1 < n and texto[i + 1] == "{":
            nivel, j = 1, i + 2
            while j < n and nivel:
                nivel += {"{": 1, "}": -1}.get(texto[j], 0)
                j += 1
            interno = texto[i + 2:j - 1]
            num, _, resto = interno.partition(":")
            if num == "0":
                saida.append("${0}")
            elif "|" in interno and interno.split("|")[0].isdigit():
                saida.append("${" + interno.split("|")[1].split(",")[0] + "}")
            elif num.isdigit():
                saida.append("${" + snippet_lsp(resto).replace("${", "").replace("}", "") + "}")
            # variaveis (${TM_SELECTED_TEXT}) somem
            i = j
            continue
        if c == "$" and i + 1 < n and (texto[i + 1].isalpha() or texto[i + 1] == "_"):
            j = i + 1
            while j < n and (texto[j].isalnum() or texto[j] == "_"):
                j += 1
            i = j  # variavel $TM_FILENAME: some
            continue
        saida.append(c)
        i += 1
    return "".join(saida)


def _uri(p: Path) -> str:
    return p.resolve().as_uri()


def _caminho_de_uri(uri: str) -> Path | None:
    u = urlparse(uri)
    if u.scheme != "file":
        return None
    caminho = unquote(u.path)
    if WINDOWS and caminho.startswith("/") and len(caminho) > 2 and caminho[2] == ":":
        caminho = caminho[1:]
    return Path(caminho)


def _dentro(p: Path, raiz: Path) -> str | None:
    try:
        return p.resolve().relative_to(raiz.resolve()).as_posix()
    except ValueError:
        return None


def _doc(valor: Any) -> str:
    if isinstance(valor, dict):
        valor = valor.get("value", "")
    elif isinstance(valor, list):
        valor = "\n\n".join(_doc(v) for v in valor)
    return str(valor or "")[:MAX_TEXTO_DOC]


@dataclass
class Sessao:
    defn: DefServidor
    raiz: Path
    cliente: ClienteLsp
    docs: dict[str, tuple[int, str]] = field(default_factory=dict)
    ultimo_uso: float = field(default_factory=time.monotonic)
    mu: threading.Lock = field(default_factory=threading.Lock)


class GerenteLsp:
    def __init__(self, dados_dir: Path | None, ambiente: Callable[[], dict[str, str]] | None = None) -> None:
        self.pasta = (dados_dir / "lsp") if dados_dir else None
        self.ambiente = ambiente or (lambda: dict(os.environ))
        self.ativo = True  # preferencia 'lsp_ativo'
        self.max_servidores = 2  # preferencia 'lsp_max_servidores'
        self.ocioso_s = 600.0
        self.tempo_pedido_s = 6.0
        self._sessoes: dict[tuple[str, str], Sessao] = {}
        self._mu = threading.Lock()
        self._instalando: dict[str, dict[str, Any]] = {}
        self._fila_instalacao = threading.Lock()
        self._parar = threading.Event()
        self._faxina: threading.Thread | None = None

    # ------------------------------------------------------------------ descoberta e instalacao
    def _bin_local(self, nome: str) -> Path | None:
        if self.pasta is None:
            return None
        candidatos = [self.pasta / "node_modules" / ".bin" / (nome + ".cmd" if WINDOWS else nome),
                      self.pasta / "dotnet" / (nome + ".exe" if WINDOWS else nome)]
        return next((c for c in candidatos if c.is_file()), None)

    def resolver(self, d: DefServidor) -> list[str] | None:
        local = self._bin_local(d.executavel)
        if local:
            return [str(local), *d.args]
        for exe, args in ((d.executavel, d.args), *d.alternativas):
            achado = shutil.which(exe, path=self.ambiente().get("PATH"))
            if achado:
                return [achado, *args]
        return None

    @staticmethod
    def servidor_de(linguagem: str) -> DefServidor | None:
        return next((d for d in SERVIDORES if linguagem in d.linguagens), None)

    def estado(self) -> dict[str, Any]:
        with self._mu:
            rodando = {}
            for (sid, raiz), s in self._sessoes.items():
                if s.cliente.vivo:
                    rodando.setdefault(sid, []).append(Path(raiz).name)
        env_path = self.ambiente().get("PATH")
        itens = []
        for d in SERVIDORES:
            cmd = self.resolver(d)
            inst = self._instalando.get(d.id) or {}
            itens.append({"id": d.id, "rotulo": d.rotulo, "linguagens": list(d.linguagens), "disponivel": bool(cmd),
                          "executavel": Path(cmd[0]).name if cmd else None, "local": bool(cmd and self.pasta and str(self.pasta) in cmd[0]),
                          "rodando": rodando.get(d.id, []), "requisito": d.requisito,
                          "pode_instalar": bool((d.npm and shutil.which("npm", path=env_path)) or (d.dotnet and shutil.which("dotnet", path=env_path))),
                          "instalacao": self._descrever_instalacao(d), "instalando": inst.get("rodando", False),
                          "ultima_instalacao": {k: inst.get(k) for k in ("ok", "saida", "terminou_em") if k in inst} or None})
        return {"ativo": self.ativo, "max_servidores": self.max_servidores, "pasta": str(self.pasta) if self.pasta else None, "servidores": itens}

    def _descrever_instalacao(self, d: DefServidor) -> str:
        if d.npm:
            return f"npm install --prefix <dados>/lsp {' '.join(d.npm)}"
        return f"dotnet tool install {d.dotnet} --tool-path <dados>/lsp/dotnet"

    def instalar(self, servidor_id: str) -> dict[str, Any]:
        """Instala em segundo plano (baixa pacotes da internet: o painel pede confirmacao antes)."""
        d = next((x for x in SERVIDORES if x.id == servidor_id), None)
        if d is None or self.pasta is None:
            raise ErroLsp("servidor desconhecido")
        env = self.ambiente()
        if d.npm:
            exe = shutil.which("npm", path=env.get("PATH"))
            if not exe:
                raise ErroLsp("npm nao encontrado: instale o Node.js LTS (https://nodejs.org) e tente de novo")
            cmd = [exe, "install", "--prefix", str(self.pasta), "--no-audit", "--no-fund", "--loglevel", "error", *d.npm]
        else:
            exe = shutil.which("dotnet", path=env.get("PATH"))
            if not exe:
                raise ErroLsp("dotnet nao encontrado: instale o .NET SDK 8 ou mais novo (https://dot.net) e tente de novo")
            cmd = [exe, "tool", "install", d.dotnet, "--tool-path", str(self.pasta / "dotnet")]
        with self._mu:
            if (self._instalando.get(servidor_id) or {}).get("rodando"):
                return {"instalando": True}
            self._instalando[servidor_id] = {"rodando": True}
        self.pasta.mkdir(parents=True, exist_ok=True)

        def rodar() -> None:
            # uma instalacao por vez: dois `npm install` na mesma pasta se atropelam (ENOTEMPTY, medido)
            with self._fila_instalacao:
                self._rodar_instalacao(servidor_id, cmd, env)

        threading.Thread(target=rodar, daemon=True, name=f"forja-lsp-instalar-{servidor_id}").start()
        return {"instalando": True, "comando": " ".join(Path(cmd[0]).name if i == 0 else c for i, c in enumerate(cmd))}

    def _rodar_instalacao(self, servidor_id: str, cmd: list[str], env: dict[str, str]) -> None:
        try:
            r = subprocess.run(cmd, cwd=str(self.pasta), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",  # noqa: S603
                               timeout=900, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            saida = ((r.stdout or "") + (r.stderr or "")).strip()[-1500:]
            ok = r.returncode == 0 or "already installed" in saida
        except (OSError, subprocess.TimeoutExpired) as e:
            ok, saida = False, f"{type(e).__name__}: {e}"[:500]
        self._instalando[servidor_id] = {"rodando": False, "ok": ok, "saida": saida, "terminou_em": time.time()}
        log.info("instalacao do servidor de linguagem %s: %s", servidor_id, "ok" if ok else "falhou")

    # ------------------------------------------------------------------ sessoes
    def _configuracao(self, raiz: Path) -> Callable[[list[dict[str, Any]]], list[Any]]:
        venv = next((p for p in (raiz / ".venv" / "Scripts" / "python.exe", raiz / ".venv" / "bin" / "python",
                                 raiz / "venv" / "Scripts" / "python.exe", raiz / "venv" / "bin" / "python") if p.is_file()), None)
        analise = {"diagnosticMode": "openFilesOnly", "autoSearchPaths": True, "useLibraryCodeForTypes": True, "typeCheckingMode": "basic"}

        def responder(itens: list[dict[str, Any]]) -> list[Any]:
            saida: list[Any] = []
            for it in itens:
                sec = it.get("section") or ""
                if sec == "python":
                    saida.append({"pythonPath": str(venv) if venv else None, "analysis": analise})
                elif sec == "python.analysis":
                    saida.append(analise)
                elif sec in ("html", "css", "scss", "less"):
                    saida.append({"validate": True, "suggest": {"html5": True}, "autoClosingTags": True})
                else:
                    saida.append({})
            return saida

        return responder

    def _sessao(self, d: DefServidor, raiz: Path) -> Sessao:
        chave = (d.id, str(raiz.resolve()).casefold() if WINDOWS else str(raiz.resolve()))
        with self._mu:
            s = self._sessoes.get(chave)
            if s and s.cliente.vivo:
                s.ultimo_uso = time.monotonic()
                return s
            cmd = self.resolver(d)
            if cmd is None:
                raise ErroLsp(f"servidor de {d.rotulo} nao instalado (Configurações > Editor > Servidores de linguagem)")
            vivos = sorted((x for x in self._sessoes.items() if x[1].cliente.vivo), key=lambda x: x[1].ultimo_uso)
            while len(vivos) >= max(1, self.max_servidores):  # limite de processos: encerra o mais antigo
                k, velho = vivos.pop(0)
                threading.Thread(target=velho.cliente.encerrar, daemon=True).start()
                self._sessoes.pop(k, None)
            cliente = ClienteLsp(cmd, str(raiz), self.ambiente(), self._configuracao(raiz))
            cliente.iniciar()
            s = Sessao(d, raiz, cliente)
            self._sessoes[chave] = s
        opcoes = dict(d.opcoes_init)
        tsserver = self.pasta / "node_modules" / "typescript" / "lib" / "tsserver.js" if self.pasta else None
        if d.id == "typescript" and tsserver and tsserver.is_file() and not (raiz / "node_modules" / "typescript").is_dir():
            opcoes["tsserver"] = {"path": str(tsserver)}  # o TypeScript instalado pela Forja, se o projeto nao tiver o seu
        try:
            r = cliente.pedir("initialize", {
                "processId": os.getpid(), "rootUri": _uri(raiz), "rootPath": str(raiz),
                "workspaceFolders": [{"uri": _uri(raiz), "name": raiz.name}], "initializationOptions": opcoes or None,
                "clientInfo": {"name": "Forja", "version": "1"},
                "capabilities": {
                    "workspace": {"configuration": True, "workspaceFolders": True},
                    "textDocument": {
                        "synchronization": {"didSave": False, "dynamicRegistration": False},
                        "completion": {"completionItem": {"snippetSupport": True, "documentationFormat": ["markdown", "plaintext"],
                                                          "resolveSupport": {"properties": ["documentation", "detail"]}},
                                       "contextSupport": True},
                        "hover": {"contentFormat": ["markdown", "plaintext"]},
                        "signatureHelp": {"signatureInformation": {"documentationFormat": ["markdown", "plaintext"],
                                                                   "parameterInformation": {"labelOffsetSupport": True}}},
                        "definition": {"linkSupport": False},
                        "publishDiagnostics": {"relatedInformation": False}}},
            }, 30.0)
            cliente.capacidades = (r or {}).get("capabilities") or {}
            cliente.notificar("initialized", {})
            cliente.notificar("workspace/didChangeConfiguration", {"settings": {}})
        except (ErroLsp, TimeoutError) as e:
            cliente.encerrar(0.5)
            with self._mu:
                self._sessoes.pop(chave, None)
            raise ErroLsp(f"o servidor de {d.rotulo} nao iniciou: {e}") from e
        self._garantir_faxina()
        return s

    def _sincronizar(self, s: Sessao, arquivo: Path, texto: str, linguagem: str) -> str:
        uri = _uri(arquivo)
        h = hashlib.sha256(texto.encode("utf-8", errors="replace")).hexdigest()
        atual = s.docs.get(uri)
        if atual is None:
            s.cliente.notificar("textDocument/didOpen", {"textDocument": {"uri": uri, "languageId": ID_LINGUAGEM.get(linguagem, linguagem),
                                                                          "version": 1, "text": texto}})
            s.docs[uri] = (1, h)
        elif atual[1] != h:
            versao = atual[0] + 1
            s.cliente.notificar("textDocument/didChange", {"textDocument": {"uri": uri, "version": versao}, "contentChanges": [{"text": texto}]})
            s.docs[uri] = (versao, h)
        return uri

    def _com_sessao(self, raiz: Path, arquivo: Path, linguagem: str, texto: str, fn: Callable[[Sessao, str], Any]) -> Any:
        if not self.ativo:
            raise ErroLsp("servidores de linguagem desligados (Configurações > Editor)")
        d = self.servidor_de(linguagem)
        if d is None:
            raise ErroLsp(f"sem servidor de linguagem para {linguagem}")
        s = self._sessao(d, raiz)
        with s.mu:
            s.ultimo_uso = time.monotonic()
            uri = self._sincronizar(s, arquivo, texto, linguagem)
            return fn(s, uri)

    # ------------------------------------------------------------------ recursos
    def completar(self, raiz: Path, arquivo: Path, linguagem: str, texto: str, linha: int, coluna: int,
                  gatilho: str = "") -> dict[str, Any]:
        def fn(s: Sessao, uri: str) -> dict[str, Any]:
            ctx = {"triggerKind": 2, "triggerCharacter": gatilho} if gatilho else {"triggerKind": 1}
            r = s.cliente.pedir("textDocument/completion", {"textDocument": {"uri": uri}, "position": {"line": linha, "character": coluna},
                                                            "context": ctx}, self.tempo_pedido_s)
            itens = (r or {}).get("items", []) if isinstance(r, dict) else (r or [])
            # o servidor pode devolver centenas (ex.: todos os membros de `os`): os que casam com o que ja foi digitado vem antes
            linhas = texto.split("\n")
            antes = linhas[linha][:coluna] if 0 <= linha < len(linhas) else ""
            prefixo = re.search(r"[\w$-]*$", antes).group(0).casefold()

            def ordem(x: dict[str, Any]) -> tuple[int, str]:
                rot = str(x.get("filterText") or x.get("label") or "").casefold()
                return (0 if rot.startswith(prefixo) else 1 if prefixo and prefixo in rot else 2, str(x.get("sortText") or rot))

            saida = []
            for it in sorted(itens, key=ordem)[:MAX_ITENS]:
                te = it.get("textEdit") or {}
                novo = te.get("newText") or it.get("insertText") or it.get("label") or ""
                if it.get("insertTextFormat") == 2:
                    novo = snippet_lsp(novo)
                else:
                    novo = novo.replace("${", "$${")
                rotulo = str(it.get("label") or "")
                saida.append({"rotulo": rotulo[:120], "tipo": _TIPOS.get(it.get("kind") or 0, "palavra"), "assinatura": str(it.get("detail") or "")[:200],
                              "doc": _doc(it.get("documentation"))[:600], "inserir": novo[:1500], "filtro": str(it.get("filterText") or rotulo)[:120]})
            return {"itens": saida, "incompleta": bool(isinstance(r, dict) and r.get("isIncomplete"))}

        return self._com_sessao(raiz, arquivo, linguagem, texto, fn)

    def explicar(self, raiz: Path, arquivo: Path, linguagem: str, texto: str, linha: int, coluna: int) -> dict[str, Any]:
        def fn(s: Sessao, uri: str) -> dict[str, Any]:
            pos = {"textDocument": {"uri": uri}, "position": {"line": linha, "character": coluna}}
            h = s.cliente.pedir("textDocument/hover", pos, self.tempo_pedido_s) or {}
            assinatura = None
            if s.cliente.capacidades.get("signatureHelpProvider") is not None:
                try:
                    sh = s.cliente.pedir("textDocument/signatureHelp", pos, 3.0) or {}
                    sigs = sh.get("signatures") or []
                    if sigs:
                        ativa = sigs[min(int(sh.get("activeSignature") or 0), len(sigs) - 1)]
                        params = ativa.get("parameters") or []
                        ip = int(sh.get("activeParameter") if sh.get("activeParameter") is not None else ativa.get("activeParameter") or 0)
                        rot = ativa.get("label", "")
                        p = params[ip]["label"] if 0 <= ip < len(params) else None
                        trecho = rot[p[0]:p[1]] if isinstance(p, list) and len(p) == 2 else (p or "")
                        assinatura = {"rotulo": rot[:300], "parametro": str(trecho)[:120], "doc": _doc(ativa.get("documentation"))[:800],
                                      "doc_parametro": _doc(params[ip].get("documentation"))[:400] if 0 <= ip < len(params) else ""}
                except (ErroLsp, TimeoutError):
                    assinatura = None
            return {"texto": _doc(h.get("contents")), "assinatura": assinatura}

        return self._com_sessao(raiz, arquivo, linguagem, texto, fn)

    def definicao(self, raiz: Path, arquivo: Path, linguagem: str, texto: str, linha: int, coluna: int) -> list[dict[str, Any]]:
        def fn(s: Sessao, uri: str) -> list[dict[str, Any]]:
            r = s.cliente.pedir("textDocument/definition", {"textDocument": {"uri": uri}, "position": {"line": linha, "character": coluna}},
                                self.tempo_pedido_s)
            locais = r if isinstance(r, list) else ([r] if r else [])
            saida = []
            for loc in locais[:20]:
                alvo_uri = loc.get("uri") or loc.get("targetUri") or ""
                faixa = loc.get("range") or loc.get("targetSelectionRange") or loc.get("targetRange") or {}
                p = _caminho_de_uri(alvo_uri)
                rel = _dentro(p, raiz) if p else None
                ini = faixa.get("start") or {}
                saida.append({"rel": rel, "externo": rel is None, "nome": p.name if p else alvo_uri[-80:],
                              "linha": int(ini.get("line", 0)) + 1, "coluna": int(ini.get("character", 0)) + 1})
            return saida

        return self._com_sessao(raiz, arquivo, linguagem, texto, fn)

    def diagnosticos(self, raiz: Path, arquivo: Path, linguagem: str, texto: str, espera_s: float = 5.0) -> list[dict[str, Any]]:
        d = self.servidor_de(linguagem)
        if d is None or not self.ativo:
            return []
        s = self._sessao(d, raiz)
        uri = _uri(arquivo)
        with s.mu:
            s.ultimo_uso = time.monotonic()
            versao_antes = s.docs.get(uri)
            ev = s.cliente.nova_espera(uri)
            self._sincronizar(s, arquivo, texto, linguagem)
            mudou = versao_antes is None or s.docs.get(uri) != versao_antes
        brutos = s.cliente.aguardar_diagnosticos(uri, ev, espera_s if mudou or not s.cliente.tem_diagnosticos(uri) else 0.0)
        saida = []
        for x in brutos[:200]:
            ini, fim = (x.get("range") or {}).get("start") or {}, (x.get("range") or {}).get("end") or {}
            saida.append({"linha": int(ini.get("line", 0)) + 1, "coluna": int(ini.get("character", 0)) + 1, "fim_linha": int(fim.get("line", 0)) + 1,
                          "fim_coluna": int(fim.get("character", 0)) + 1, "severidade": _SEVERIDADE.get(x.get("severity") or 1, "erro"),
                          "mensagem": str(x.get("message") or "")[:500], "fonte": str(x.get("source") or d.id)[:40],
                          "codigo": str(x.get("code") or "")[:60]})
        return saida

    def fechar(self, raiz: Path, arquivo: Path, linguagem: str) -> None:
        d = self.servidor_de(linguagem)
        if d is None:
            return
        chave = (d.id, str(raiz.resolve()).casefold() if WINDOWS else str(raiz.resolve()))
        s = self._sessoes.get(chave)
        if s and s.cliente.vivo:
            uri = _uri(arquivo)
            with s.mu:
                if s.docs.pop(uri, None):
                    try:
                        s.cliente.notificar("textDocument/didClose", {"textDocument": {"uri": uri}})
                    except ErroLsp:
                        pass

    # ------------------------------------------------------------------ ciclo de vida
    def _garantir_faxina(self) -> None:
        if self._faxina is not None:
            return

        def laco() -> None:
            while not self._parar.wait(30.0):
                agora = time.monotonic()
                with self._mu:
                    velhos = [(k, s) for k, s in self._sessoes.items() if not s.cliente.vivo or agora - s.ultimo_uso > self.ocioso_s]
                    for k, _s in velhos:
                        self._sessoes.pop(k, None)
                for _k, s in velhos:
                    s.cliente.encerrar(1.0)

        self._faxina = threading.Thread(target=laco, daemon=True, name="forja-lsp-faxina")
        self._faxina.start()

    def encerrar_todos(self) -> None:
        self._parar.set()
        with self._mu:
            todas = list(self._sessoes.values())
            self._sessoes.clear()
        for s in todas:
            s.cliente.encerrar(1.0)
