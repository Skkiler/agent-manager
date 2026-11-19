"""Area de trabalho do painel (bancada estilo VS Code/Kiro): arquivos, busca, Git, Docker, terminal, HTTP e problemas.

Quem usa e o USUARIO no proprio computador (painel autenticado). Regra de seguranca (decisao do usuario, ADR-026):
- a Forja e o usuario PODEM ler e editar segredos (.env, chaves): o painel mostra e marca como "segredo";
- o que a Forja NUNCA faz: enviar segredos aos agentes externos (Kiro, Codex) nem registrar conteudo em log. Nada desta area
  alimenta prompts, memoria ou anexos de agente (essas rotas usam ProjetosServico/catalogo, que continuam escondendo segredos);
- acoes perigosas do usuario (push, apagar, reset --hard, segredo indo para o commit...) viram PERGUNTA (HTTP 428 com os
  motivos; o painel reenvia com `confirmado=true`), nunca bloqueio;
- tudo continua dentro das pastas do projeto (sem links simbolicos e sem pastas protegidas/proibidas da Forja).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from forja.assistente.comandos import Assistente, montar_linha
from forja.dominio.erros import ConfirmacaoNecessaria, Conflito, ValidacaoDominio
from forja.ferramentas import sandbox
from forja.ferramentas.busca_texto import buscar_texto
from forja.ferramentas.estrutura import estrutura_codigo
from forja.ferramentas.git_leitura import ler_git
from forja.ferramentas.outline import outline_arquivo
from forja.observabilidade.sanitizar import sanitizar_texto
from forja.orquestracao.projetos_servico import _ignorar
from forja.seguranca.acoes import descrever_acao
from forja.seguranca.sensiveis import caminho_sensivel

log = logging.getLogger("forja.area")  # so metadados (operacao, codigo, tempo): nunca conteudo, comando completo ou saida
MAX_LER = 2_000_000
MAX_SALVAR = 2_000_000
MAX_SAIDA = 200_000
MAX_HTTP = 2_000_000
LINGUAGENS = {".py": "python", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".ts": "typescript", ".tsx": "typescript",
              ".jsx": "javascript", ".json": "json", ".md": "markdown", ".markdown": "markdown", ".css": "css", ".scss": "css",
              ".html": "html", ".htm": "html", ".sql": "sql", ".ps1": "powershell", ".sh": "shell", ".bash": "shell", ".yml": "yaml",
              ".yaml": "yaml", ".toml": "toml", ".ini": "ini", ".cfg": "ini", ".txt": "texto", ".xml": "xml", ".svg": "xml",
              ".rs": "rust", ".go": "go", ".java": "java", ".cs": "csharp", ".c": "c", ".h": "c", ".cpp": "cpp", ".dockerfile": "docker",
              ".env": "ini", ".http": "texto", ".jsonl": "json", ".csv": "texto", ".tsv": "texto", ".log": "texto"}
_ID_DOCKER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,255}$")
_INTERNOS = ("APP_", "FORJA_")  # configuracao e credenciais do PROPRIO servidor: nao vao para os comandos do usuario
_GIT_ESCRITA_REMOTA = {"push"}
_GIT_DEMORADOS = {"push", "pull", "fetch", "clone", "gc", "submodule", "lfs"}


def _sha(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


def linguagem_de(nome: str) -> str:
    n = nome.lower()
    if n == "dockerfile" or n.endswith(".dockerfile"):
        return "docker"
    if n == ".env" or n.startswith(".env."):
        return "ini"
    return LINGUAGENS.get(Path(n).suffix, "texto")


def ambiente_usuario() -> dict[str, str]:
    """Ambiente dos comandos do USUARIO: o do computador (PATH, credenciais de Git/Docker/npm do usuario...) sem a configuracao
    interna do servidor da Forja (APP_*/FORJA_*: token da API, integracoes)."""
    return {k: v for k, v in os.environ.items() if not k.upper().startswith(_INTERNOS)}


class AreaTrabalho:
    def __init__(self, projetos: Any, assistente: Assistente | None = None) -> None:
        self.projetos = projetos  # ProjetosServico: resolucao segura das pastas do projeto
        self.assistente = assistente or Assistente()
        self.terminal_ativo = True  # preferencia 'terminal_ativo'
        self.terminal_tempo_s = 120.0
        self.gerente_lsp: Any | None = None  # adapters.lsp.GerenteLsp (ligado pelo app)

    # ------------------------------------------------------------------ resolucao
    def _pasta(self, projeto_id: str, raiz: int) -> tuple[dict[str, str], Path]:
        projeto = self.projetos.obter(projeto_id)
        pastas = self.projetos.pastas_validas(projeto)
        if not 0 <= raiz < len(pastas):
            raise ValidacaoDominio("pasta do projeto nao encontrada")
        return pastas[raiz], Path(pastas[raiz]["caminho"]).resolve()

    def _arquivo(self, projeto_id: str, raiz: int, rel: str) -> tuple[dict[str, str], Path, Path]:
        if not rel:
            raise ValidacaoDominio("informe o arquivo")
        projeto = self.projetos.obter(projeto_id)
        base, alvo = self.projetos._resolver(projeto, raiz, rel)
        pasta = next(p for p in self.projetos.pastas_validas(projeto) if Path(p["caminho"]).resolve() == base)
        if alvo.is_symlink():
            raise ValidacaoDominio("links simbólicos não são abertos")
        return pasta, base, alvo

    @staticmethod
    def _so_trabalho(pasta: dict[str, str]) -> None:
        if pasta.get("papel") != "trabalho":
            raise ValidacaoDominio("pasta de CONSULTA é somente leitura: use uma pasta de trabalho do projeto")

    # ------------------------------------------------------------------ arquivos
    def listar(self, projeto_id: str, raiz: int, rel: str = "") -> dict[str, Any]:
        """Explorador do USUARIO: inclui segredos (marcados). O @ dos agentes usa ProjetosServico.listar, que os esconde."""
        projeto = self.projetos.obter(projeto_id)
        base, alvo = self.projetos._resolver(projeto, raiz, rel)
        if not alvo.is_dir():
            raise ValidacaoDominio("não é uma pasta")
        itens = []  # mesma regra de pastas ignoradas do explorador dos agentes (node_modules, .git...)
        with os.scandir(alvo) as it:
            for e in sorted(it, key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.casefold())):
                if e.is_symlink() or (e.is_dir(follow_symlinks=False) and _ignorar(e.name)):
                    continue
                p = Path(e.path)
                d = e.is_dir(follow_symlinks=False)
                rel_p = p.relative_to(base).as_posix()
                itens.append({"nome": e.name, "rel": rel_p, "pasta": d, "segredo": caminho_sensivel(rel_p),
                              "tamanho": None if d else e.stat(follow_symlinks=False).st_size})
                if len(itens) >= 2000:
                    break
        return {"raiz": raiz, "rel": alvo.relative_to(base).as_posix() if alvo != base else "", "itens": itens, "truncado": len(itens) >= 2000}

    def ler(self, projeto_id: str, raiz: int, rel: str) -> dict[str, Any]:
        pasta, base, alvo = self._arquivo(projeto_id, raiz, rel)
        if not alvo.is_file():
            raise ValidacaoDominio("não é um arquivo")
        if alvo.stat().st_size > MAX_LER:
            raise ValidacaoDominio(f"arquivo acima de {MAX_LER // 1_000_000} MB (abra no seu editor)")
        dados = alvo.read_bytes()
        if b"\x00" in dados[:8000]:
            raise ValidacaoDominio("arquivo binário: o editor do painel abre só texto")
        texto = dados.decode("utf-8", errors="replace")
        rel_n = alvo.relative_to(base).as_posix()
        return {"rel": rel_n, "nome": alvo.name, "conteudo": texto, "sha": _sha(dados),
                "linguagem": linguagem_de(alvo.name), "tamanho": len(dados), "somente_leitura": pasta.get("papel") != "trabalho",
                "fim_de_linha": "crlf" if b"\r\n" in dados else "lf", "segredo": caminho_sensivel(rel_n)}

    def salvar(self, projeto_id: str, raiz: int, rel: str, conteudo: str, sha_esperado: str | None) -> dict[str, Any]:
        pasta, base, alvo = self._arquivo(projeto_id, raiz, rel)
        self._so_trabalho(pasta)
        dados = conteudo.encode("utf-8")
        if len(dados) > MAX_SALVAR:
            raise ValidacaoDominio("conteúdo grande demais para o editor do painel")
        if alvo.exists():
            if not alvo.is_file():
                raise ValidacaoDominio("não é um arquivo")
            atual = _sha(alvo.read_bytes())
            if sha_esperado != atual:
                raise Conflito("O arquivo mudou no disco desde que você abriu (outro editor ou um agente). Recarregue e refaça a "
                               "alteração; nada foi sobrescrito.")
        elif sha_esperado:
            raise Conflito("O arquivo foi apagado no disco desde que você abriu; nada foi gravado.")
        alvo.parent.mkdir(parents=True, exist_ok=True)
        tmp = alvo.with_name(f".{alvo.name}.forja.tmp")
        tmp.write_bytes(dados)
        os.replace(tmp, alvo)
        return {"rel": alvo.relative_to(base).as_posix(), "sha": _sha(dados), "tamanho": len(dados)}

    # ------------------------------------------------------------------ busca, simbolos e problemas
    def buscar(self, projeto_id: str, raiz: int, padrao: str, regex: bool = False, incluir: str = "", limite: int = 100,
               incluir_segredos: bool = False) -> dict[str, Any]:
        """Busca do usuario. Segredos ficam fora por padrao (uma busca ampla nao espalha senhas pela tela); o usuario pode incluir."""
        _pasta, base = self._pasta(projeto_id, raiz)
        r = buscar_texto(base, ".", padrao, regex, True, incluir, 0, max(1, min(limite, 200)), pular_segredos=not incluir_segredos)
        return {"ocorrencias": r.dados["ocorrencias"], "arquivos": len(r.dados["arquivos"]), "avisos": r.avisos, "truncado": r.truncado,
                "segredos_pulados": r.dados.get("segredos_pulados", 0)}

    def simbolos(self, projeto_id: str, raiz: int, rel: str) -> dict[str, Any]:
        _pasta, base, alvo = self._arquivo(projeto_id, raiz, rel)
        if caminho_sensivel(alvo.relative_to(base).as_posix()):
            return {"rel": rel, "simbolos": []}
        try:
            r = outline_arquivo(base, alvo.relative_to(base).as_posix())
        except ValidacaoDominio:
            return {"rel": rel, "simbolos": []}
        return {"rel": rel, "simbolos": r.dados.get("simbolos", [])}

    def definicao(self, projeto_id: str, raiz: int, nome: str) -> dict[str, Any]:
        """Ir para a definicao (F12): indice estrutural (Python por AST; JS/TS por regex)."""
        _pasta, base = self._pasta(projeto_id, raiz)
        if not re.fullmatch(r"[A-Za-z_$][\w$.]{0,120}", nome or ""):
            raise ValidacaoDominio("nome de símbolo inválido")
        r = estrutura_codigo(base, ".", "definicao", nome.split(".")[-1])
        return {"nome": nome, "definicoes": r.dados.get("definicoes", [])[:20]}

    def problemas(self, projeto_id: str, raiz: int, rel: str, conteudo: str | None = None) -> dict[str, Any]:
        """Diagnostico do arquivo aberto: JSON (sintaxe), Python (compilacao + ruff, se o projeto tiver). Sem rodar codigo do projeto."""
        _pasta, base, alvo = self._arquivo(projeto_id, raiz, rel)
        texto = conteudo if conteudo is not None else (alvo.read_text(encoding="utf-8", errors="replace") if alvo.is_file() else "")
        lng = linguagem_de(alvo.name)
        itens: list[dict[str, Any]] = []
        if lng == "json" and not alvo.name.lower().endswith((".jsonl", ".ndjson")):
            try:
                json.loads(texto or "null")
            except json.JSONDecodeError as e:
                itens.append({"linha": e.lineno, "coluna": e.colno, "gravidade": "erro", "codigo": "json", "mensagem": e.msg})
        elif lng == "python":
            try:
                compile(texto, alvo.name, "exec", dont_inherit=True)
            except SyntaxError as e:
                itens.append({"linha": e.lineno or 1, "coluna": e.offset or 1, "gravidade": "erro", "codigo": "sintaxe",
                              "mensagem": str(e.msg)})
            itens += self._ruff(base, alvo, texto)
        return {"rel": rel, "linguagem": lng, "problemas": itens[:200]}

    # ------------------------------------------------------------------ servidor de linguagem (LSP)
    def lsp(self, acao: str, projeto_id: str, raiz: int, rel: str, texto: str, linha: int = 0, coluna: int = 0,
            gatilho: str = "") -> dict[str, Any]:
        """Completar, explicar (hover + assinatura), definicao, diagnosticos ou fechar, pelo servidor de linguagem do arquivo.
        A raiz do servidor e a pasta do projeto; o texto vem do editor (pode estar sem salvar)."""
        if self.gerente_lsp is None:
            raise ValidacaoDominio("servidores de linguagem indisponíveis neste servidor")
        from forja.adapters.lsp.cliente import ErroLsp

        _pasta, base, alvo = self._arquivo(projeto_id, raiz, rel)
        lng = linguagem_de(alvo.name)
        g = self.gerente_lsp
        try:
            if acao == "completar":
                return g.completar(base, alvo, lng, texto, linha, coluna, gatilho[:1])
            if acao == "explicar":
                return g.explicar(base, alvo, lng, texto, linha, coluna)
            if acao == "definicao":
                return {"definicoes": g.definicao(base, alvo, lng, texto, linha, coluna)}
            if acao == "diagnosticos":
                return {"rel": rel, "problemas": [{"linha": d["linha"], "coluna": d["coluna"], "gravidade": d["severidade"],
                                                   "codigo": d["codigo"] or d["fonte"], "mensagem": d["mensagem"], "fonte": d["fonte"]}
                                                  for d in g.diagnosticos(base, alvo, lng, texto)]}
            if acao == "fechar":
                g.fechar(base, alvo, lng)
                return {"ok": True}
        except TimeoutError as e:
            return {"indisponivel": True, "motivo": f"o servidor de linguagem demorou ({e}); tente de novo em instantes"}
        except ErroLsp as e:
            return {"indisponivel": True, "motivo": str(e)[:300]}
        raise ValidacaoDominio("ação de LSP desconhecida")

    @staticmethod
    def _ruff(base: Path, alvo: Path, texto: str) -> list[dict[str, Any]]:
        ruff = shutil.which("ruff")
        if not ruff:
            return []
        try:
            r = subprocess.run([ruff, "check", "--no-cache", "--output-format=json", "--stdin-filename", str(alvo), "-"],  # noqa: S603
                               cwd=str(base), input=texto, capture_output=True, text=True, encoding="utf-8", timeout=20,
                               env=ambiente_usuario(), check=False)
            dados = json.loads(r.stdout or "[]")
        except (OSError, subprocess.SubprocessError, ValueError):
            return []
        return [{"linha": (d.get("location") or {}).get("row", 1), "coluna": (d.get("location") or {}).get("column", 1),
                 "gravidade": "aviso", "codigo": str(d.get("code") or "ruff"), "mensagem": str(d.get("message") or "")[:300]}
                for d in dados if isinstance(d, dict)]

    # ------------------------------------------------------------------ confirmacao (perguntar, nunca bloquear)
    def _confirmar(self, linha: str, confirmado: bool, extras: list[str] | None = None) -> dict[str, Any]:
        analise = self.assistente.analisar(linha)
        motivos = list(extras or []) + analise["motivos"]
        if (analise["precisa_confirmar"] or extras) and not confirmado:
            raise ConfirmacaoNecessaria(f"Confirme: {linha[:160]}", motivos, "alto")
        return analise

    # ------------------------------------------------------------------ Git
    def git(self, projeto_id: str, raiz: int, operacao: str, ref: str = "", arquivo: str = "", limite: int = 30) -> dict[str, Any]:
        _pasta, base = self._pasta(projeto_id, raiz)
        if operacao == "status":
            return self._status(base)
        try:
            r = ler_git(base, ".", operacao, ref, "", arquivo, 1, 0, limite)
        except ValidacaoDominio as e:
            if "repositorio git" in e.mensagem:
                return {"resumo": "a pasta não é um repositório git", "dados": {"repositorio": False}, "avisos": []}
            raise
        return {"resumo": r.resumo, "dados": r.dados, "avisos": r.avisos}

    def _status(self, base: Path) -> dict[str, Any]:
        """Status do USUARIO (inclui segredos, marcados), branch, ahead/behind, remotos, branches e stash."""
        try:
            bruto = self._git(base, ["status", "--porcelain=v1", "-b", "--untracked-files=all"])
        except ValidacaoDominio as e:
            if "not a git repository" in e.mensagem.lower() or "nao e um repositorio" in e.mensagem.lower():
                return {"resumo": "a pasta não é um repositório git", "dados": {"branch": "", "alterados": [], "repositorio": False}, "avisos": []}
            raise
        linhas = bruto.splitlines()
        cab = linhas[0][3:] if linhas and linhas[0].startswith("##") else ""
        ramo, _, resto = cab.partition("...")
        m = re.search(r"\[(?:ahead (\d+))?(?:, )?(?:behind (\d+))?\]", cab)
        itens = []
        for ln in linhas[1:]:
            if len(ln) > 3:
                arq = ln[3:].split(" -> ")[-1].strip('"')
                itens.append({"estado": ln[:2].strip() or "?", "x": ln[0], "y": ln[1], "arquivo": ln[3:], "segredo": caminho_sensivel(arq)})
        branches = [b for b in self._git_ou(base, ["branch", "--format=%(refname:short)"]).splitlines() if b]
        remotos = {}
        for ln in self._git_ou(base, ["remote", "-v"]).splitlines():
            partes = ln.split()
            if len(partes) >= 2:
                remotos[partes[0]] = partes[1]
        stash = [s for s in self._git_ou(base, ["stash", "list", "--format=%gd\t%s"]).splitlines() if s][:30]
        avisos = []
        segredos = [i["arquivo"] for i in itens if i["segredo"] and i["x"] not in (" ", "?")]
        if segredos:
            avisos.append(f"arquivo de segredo PREPARADO para commit: {', '.join(segredos[:3])} (vai para o histórico do Git)")
        return {"resumo": f"branch {ramo}; {len(itens)} alterado(s)", "avisos": avisos,
                "dados": {"repositorio": True, "branch": ramo.replace("No commits yet on ", "").strip(), "upstream": resto.split(" [")[0].strip(),
                          "a_frente": int(m.group(1) or 0) if m else 0, "atras": int(m.group(2) or 0) if m else 0,
                          "alterados": itens[:2000], "branches": branches[:300], "remotos": remotos, "stash": stash}}

    def git_versao(self, projeto_id: str, raiz: int, rel: str, versao: str = "HEAD") -> dict[str, Any]:
        """Conteudo de um arquivo numa versao (HEAD, index ou commit) para a revisao lado a lado."""
        _pasta, base, alvo = self._arquivo(projeto_id, raiz, rel)
        if not re.fullmatch(r"index|HEAD(~\d+)?|[0-9a-fA-F]{4,40}|[\w./-]{1,120}", versao) or versao.startswith("-"):
            raise ValidacaoDominio("versão inválida")
        caminho = alvo.relative_to(base).as_posix()
        alvo_git = f":{caminho}" if versao == "index" else f"{versao}:{caminho}"
        try:
            texto = self._git(base, ["show", alvo_git])
            existe = True
        except ValidacaoDominio:
            texto, existe = "", False
        return {"rel": caminho, "versao": versao, "conteudo": texto[:MAX_LER], "existe": existe}

    def git_executar(self, projeto_id: str, raiz: int, args: list[str], confirmado: bool = False) -> dict[str, Any]:
        """Qualquer comando git (sem shell; argumentos ja separados). Perigoso = pergunta; segredo indo para o commit = pergunta."""
        pasta, base = self._pasta(projeto_id, raiz)
        if not args:
            raise ValidacaoDominio("informe o comando git")
        sub = args[0].lower()
        if sub not in ("status", "log", "diff", "show", "branch", "remote", "stash", "blame", "config", "tag", "rev-parse", "ls-files", "reflog", "describe", "shortlog"):
            self._so_trabalho(pasta)
        extras: list[str] = []
        if sub == "add":
            previstos = self._git_ou(base, ["add", "--dry-run", *args[1:]])
            sens = [ln.split("'", 2)[1] for ln in previstos.splitlines() if ln.startswith("add '") and caminho_sensivel(ln.split("'", 2)[1])]
            if sens:
                extras.append(f"vai preparar arquivo de segredo para commit: {', '.join(sens[:3])} (entra no histórico e vai para o remoto no push)")
        if sub == "commit":
            preparados = self._git_ou(base, ["diff", "--cached", "--name-only"]).splitlines()
            if "-a" in args or "--all" in args:
                preparados += self._git_ou(base, ["diff", "--name-only"]).splitlines()
            sens = [x for x in preparados if caminho_sensivel(x)]
            if sens:
                extras.append(f"o commit inclui arquivo de segredo: {', '.join(sens[:3])}")
        if sub in _GIT_ESCRITA_REMOTA:
            extras.append("publica no servidor remoto: confira branch e remoto antes")
        linha = montar_linha("git", args)
        analise = self._confirmar(linha, confirmado, extras)
        t0 = time.monotonic()
        env = {**ambiente_usuario(), "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}
        try:
            r = subprocess.run(["git", "-c", "core.quotepath=false", *args], cwd=str(base), env=env, capture_output=True, text=True,  # noqa: S603, S607
                               encoding="utf-8", errors="replace", timeout=300 if sub in _GIT_DEMORADOS else 60, stdin=subprocess.DEVNULL, check=False)
        except subprocess.TimeoutExpired:
            return {"codigo": -1, "saida": "", "erro": "o git passou do tempo máximo (rede lenta ou pedindo senha?)", "tempo_s": time.monotonic() - t0}
        except OSError as e:
            raise ValidacaoDominio(f"git indisponível: {type(e).__name__}") from e
        log.info("git do usuario", extra={"evento": "area.git", "sub": sub, "codigo": r.returncode})
        erro = r.stderr[-MAX_SAIDA:]
        if r.returncode and "terminal prompts disabled" in erro.lower():
            erro += ("\n\nO Git pediu usuário/senha. Configure um gerenciador de credenciais (Git Credential Manager) ou use SSH, e "
                     "faça o primeiro login pelo seu terminal.")
        return {"codigo": r.returncode, "saida": r.stdout[-MAX_SAIDA:], "erro": erro, "tempo_s": round(time.monotonic() - t0, 2),
                "risco": analise["risco"]}

    def git_acao(self, projeto_id: str, raiz: int, acao: str, arquivos: list[str], mensagem: str = "", confirmado: bool = False) -> dict[str, Any]:
        """Atalhos dos botoes (stage, unstage, commit, discard) sobre git_executar."""
        for a in arquivos:
            if a.startswith("-") or ".." in Path(a).parts or Path(a).is_absolute():
                raise ValidacaoDominio(f"arquivo não permitido: {a[:80]}")
        if acao == "stage":
            args = ["add", "--", *arquivos] if arquivos else ["add", "-A"]
        elif acao == "unstage":
            args = ["restore", "--staged", "--", *arquivos] if arquivos else ["reset", "-q"]
        elif acao == "commit":
            msg = (mensagem or "").strip()
            if not msg:
                raise ValidacaoDominio("escreva a mensagem do commit")
            args = ["commit", "-m", msg[:2000]]
        elif acao == "discard":
            if not arquivos:
                raise ValidacaoDominio("escolha os arquivos para descartar")
            args = ["restore", "--", *arquivos]
        else:
            raise ValidacaoDominio("ação de Git inválida (stage, unstage, commit, discard)")
        r = self.git_executar(projeto_id, raiz, args, confirmado)
        if r["codigo"] != 0:
            raise ValidacaoDominio("git: " + ((r["erro"] or r["saida"]).strip().splitlines() or ["falhou"])[-1][:300])
        return {"acao": acao, "saida": r["saida"][-4000:], "avisos": []}

    @staticmethod
    def _git(base: Path, args: list[str], timeout: float = 30) -> str:
        env = {**ambiente_usuario(), "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"}
        try:
            r = subprocess.run(["git", "-c", "core.fsmonitor=false", "-c", "core.quotepath=false", *args], cwd=str(base), env=env,  # noqa: S603, S607
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, stdin=subprocess.DEVNULL, check=False)
        except (OSError, subprocess.SubprocessError) as e:
            raise ValidacaoDominio(f"git indisponível: {type(e).__name__}") from e
        if r.returncode != 0:
            raise ValidacaoDominio("git: " + sanitizar_texto((r.stderr or r.stdout or "falhou").strip().splitlines()[-1] if (r.stderr or r.stdout).strip() else "falhou")[:300])
        return r.stdout

    def _git_ou(self, base: Path, args: list[str]) -> str:
        try:
            return self._git(base, args)
        except ValidacaoDominio:
            return ""

    # ------------------------------------------------------------------ terminal
    def terminal(self, projeto_id: str, raiz: int, comando: str, confirmado: bool = False, tempo_s: float | None = None) -> dict[str, Any]:
        if not self.terminal_ativo:
            raise ValidacaoDominio("terminal desligado (Configurações > Segurança)")
        comando = (comando or "").strip()
        if not comando or len(comando) > 4000:
            raise ValidacaoDominio("comando vazio ou longo demais")
        pasta, base = self._pasta(projeto_id, raiz)
        self._so_trabalho(pasta)
        analise = self._confirmar(comando, confirmado)
        item = descrever_acao({"kind": "execute", "toolCallId": "terminal", "rawInput": {"command": comando}}, base)
        avisos = list(analise["avisos"])
        if item["sensivel"]:
            avisos.append("o comando lê segredo: o resultado aparece só para você (não vai para os agentes nem para o log)")
        args = (["powershell", "-NoProfile", "-NonInteractive", "-Command", comando] if os.name == "nt" else ["bash", "-c", comando])
        teto = max(5.0, min(float(tempo_s or self.terminal_tempo_s), 900.0))
        s = sandbox.executar(args, base, ambiente_usuario(), teto, "basico")
        log.info("terminal do usuario", extra={"evento": "area.terminal", "codigo": s.codigo, "esgotado": s.esgotado})
        return {"comando": comando[:300], "codigo": s.codigo, "tempo_esgotado": s.esgotado, "saida": s.texto[-MAX_SAIDA:],
                "risco": analise["risco"], "categoria": item["categoria"], "avisos": avisos, "erros_previstos": analise["erros"]}

    # ------------------------------------------------------------------ Docker
    @staticmethod
    def _docker(args: list[str], timeout: float = 20, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        exe = shutil.which("docker")
        if not exe:
            raise ValidacaoDominio("Docker não encontrado nesta máquina")
        try:
            return subprocess.run([exe, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,  # noqa: S603
                                  env=ambiente_usuario(), stdin=subprocess.DEVNULL, check=False, cwd=str(cwd) if cwd else None)
        except subprocess.TimeoutExpired as e:
            raise ValidacaoDominio("o Docker não respondeu a tempo (o serviço está ligado?)") from e
        except OSError as e:
            raise ValidacaoDominio(f"Docker indisponível: {type(e).__name__}") from e

    def _docker_ok(self, args: list[str], timeout: float = 20) -> str:
        r = self._docker(args, timeout)
        if r.returncode != 0:
            raise ValidacaoDominio("docker: " + sanitizar_texto((r.stderr or "falhou").strip().splitlines()[-1] if r.stderr.strip() else "falhou")[:300])
        return r.stdout

    def docker(self, recurso: str) -> list[dict[str, Any]]:
        fmt = "{{json .}}"
        if recurso == "containers":
            bruto = self._docker_ok(["ps", "-a", "--format", fmt])
            campos = ("ID", "Names", "Image", "State", "Status", "Ports")
        elif recurso == "imagens":
            bruto = self._docker_ok(["images", "--format", fmt])
            campos = ("ID", "Repository", "Tag", "Size", "CreatedSince")
        elif recurso == "volumes":
            bruto = self._docker_ok(["volume", "ls", "--format", fmt])
            campos = ("Name", "Driver", "Mountpoint")
        elif recurso == "redes":
            bruto = self._docker_ok(["network", "ls", "--format", fmt])
            campos = ("ID", "Name", "Driver", "Scope")
        elif recurso == "compose":
            bruto = self._docker_ok(["compose", "ls", "-a", "--format", "json"])
            try:
                return [{k: str(v)[:300] for k, v in d.items() if k in ("Name", "Status", "ConfigFiles")} for d in json.loads(bruto or "[]")]
            except ValueError:
                return []
        else:
            raise ValidacaoDominio("recurso inválido (containers, imagens, volumes, redes, compose)")
        saida = []
        for linha in bruto.splitlines():
            try:
                d = json.loads(linha)
            except ValueError:
                continue
            saida.append({k: str(d.get(k, ""))[:300] for k in campos})
        return saida[:500]

    def docker_logs(self, id_: str, linhas: int = 200) -> dict[str, Any]:
        if not _ID_DOCKER.match(id_ or ""):
            raise ValidacaoDominio("container inválido")
        r = self._docker(["logs", "--tail", str(max(1, min(linhas, 5000))), id_], 30)
        return {"id": id_, "saida": (r.stdout + r.stderr)[-MAX_SAIDA:]}

    def docker_acao(self, id_: str, acao: str, confirmado: bool = False) -> dict[str, Any]:
        if not _ID_DOCKER.match(id_ or "") or acao not in ("start", "stop", "restart", "kill", "rm", "pause", "unpause"):
            raise ValidacaoDominio("container ou ação inválida")
        r = self.docker_executar([acao, id_], confirmado)
        if r["codigo"] != 0:
            raise ValidacaoDominio("docker: " + ((r["erro"] or "falhou").strip().splitlines() or ["falhou"])[-1][:300])
        return {"id": id_, "acao": acao}

    def docker_executar(self, args: list[str], confirmado: bool = False, projeto_id: str | None = None, raiz: int = 0) -> dict[str, Any]:
        """Qualquer comando docker (sem shell). Interativo (-it) nao funciona sem terminal; perigoso = pergunta."""
        if not args:
            raise ValidacaoDominio("informe o comando docker")
        sub = args[0].lower()
        opcoes_iniciais = []
        for a in args[1:]:  # so as opcoes antes do container/imagem (depois vem o comando de dentro do container)
            if not a.startswith("-"):
                break
            opcoes_iniciais.append(a)
        if sub == "attach" or (sub in ("exec", "run") and any(a in ("-it", "-ti", "-i", "-t", "--interactive", "--tty") for a in opcoes_iniciais)):
            raise ValidacaoDominio("modo interativo (-it/-a) precisa de um terminal de verdade: rode pelo seu terminal ou use sem -it")
        cwd = None
        if projeto_id:
            _pasta, cwd = self._pasta(projeto_id, raiz)
        linha = montar_linha("docker", args)
        analise = self._confirmar(linha, confirmado)
        t0 = time.monotonic()
        demorado = sub in ("build", "pull", "push", "compose", "run", "system", "image", "buildx")
        try:
            r = self._docker(args, 900 if demorado else 120, cwd)
        except ValidacaoDominio as e:
            return {"codigo": -1, "saida": "", "erro": e.mensagem, "tempo_s": round(time.monotonic() - t0, 2)}
        log.info("docker do usuario", extra={"evento": "area.docker", "sub": sub, "codigo": r.returncode})
        return {"codigo": r.returncode, "saida": r.stdout[-MAX_SAIDA:], "erro": r.stderr[-MAX_SAIDA:], "tempo_s": round(time.monotonic() - t0, 2),
                "risco": analise["risco"], "avisos": (["inspect mostra as variáveis de ambiente do container: ficam só na sua tela"] if sub == "inspect" else [])}

    # ------------------------------------------------------------------ HTTP (estilo Postman)
    def http(self, metodo: str, url: str, cabecalhos: dict[str, str], corpo: str | None, tempo_s: float = 30.0,
             seguir: bool = True, verificar_tls: bool = True) -> dict[str, Any]:
        """Requisicao feita pelo servidor local (o navegador nao pode: CSP connect-src 'self'). Conteudo nunca vai para log."""
        import httpx

        if not re.match(r"(?i)^https?://[^\s/]+", url or ""):
            raise ValidacaoDominio("URL deve começar com http:// ou https://")
        metodo = metodo.upper()
        if metodo not in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
            raise ValidacaoDominio("método inválido")
        t0 = time.monotonic()
        try:
            with httpx.Client(timeout=max(1.0, min(tempo_s, 120.0)), follow_redirects=seguir, verify=verificar_tls, trust_env=True) as c:
                with c.stream(metodo, url, headers=cabecalhos, content=corpo.encode("utf-8") if corpo else None) as r:
                    dados = bytearray()
                    for bloco in r.iter_bytes():
                        dados += bloco
                        if len(dados) > MAX_HTTP:
                            break
                    tempo = round((time.monotonic() - t0) * 1000)
                    tipo = r.headers.get("content-type", "")
                    texto_ok = any(x in tipo for x in ("json", "text", "xml", "javascript", "html", "csv", "yaml", "x-www-form")) or not tipo
                    corpo_resp = bytes(dados[:MAX_HTTP])
                    try:
                        texto = corpo_resp.decode(r.encoding or "utf-8") if texto_ok else ""
                    except (LookupError, UnicodeDecodeError):
                        texto = corpo_resp.decode("utf-8", errors="replace")
                    return {"status": r.status_code, "motivo": r.reason_phrase, "cabecalhos": [[k, v] for k, v in r.headers.multi_items()][:200],
                            "corpo": texto, "base64": "" if texto_ok else base64.b64encode(corpo_resp[:200_000]).decode(), "tipo": tipo,
                            "tamanho": len(dados), "truncado": len(dados) > MAX_HTTP, "tempo_ms": tempo, "url_final": str(r.url),
                            "versao_http": r.http_version, "redirecionamentos": len(r.history)}
        except httpx.TimeoutException:
            return {"status": 0, "erro": f"tempo esgotado ({tempo_s:.0f}s)", "tempo_ms": round((time.monotonic() - t0) * 1000)}
        except httpx.HTTPError as e:
            return {"status": 0, "erro": f"{type(e).__name__}: {sanitizar_texto(str(e))[:300]}", "tempo_ms": round((time.monotonic() - t0) * 1000)}

