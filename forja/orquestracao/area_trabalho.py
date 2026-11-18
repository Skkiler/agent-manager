"""Area de trabalho do painel (editor estilo VS Code/Kiro): ler e salvar arquivos, Git, terminal, Docker, problemas e busca.

Tudo passa pelas PASTAS DO PROJETO (ProjetosServico._resolver): nada fora delas, sem links, sem pastas protegidas/proibidas.
Regras que valem sempre (iguais as dos agentes):
- arquivos com cara de segredo (.env, chaves, credenciais) nunca sao lidos, salvos, buscados nem aparecem no Git/terminal;
- pasta de CONSULTA e so leitura (salvar, Git que escreve e terminal so na pasta de TRABALHO);
- salvar usa concorrencia otimista (hash do conteudo lido): se o arquivo mudou no disco, nada e sobrescrito;
- terminal: um comando por vez, sem shell interativo, ambiente limpo, tempo maximo, arvore de processos presa (Job Object) e
  saida redigida; comando que imprime segredo (o mesmo classificador do mediador) e recusado;
- Docker: so listar, ver logs (redigidos) e iniciar/parar/reiniciar; nunca `inspect`/`exec` (mostram variaveis de ambiente).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from forja.dominio.erros import Conflito, ValidacaoDominio
from forja.ferramentas import sandbox
from forja.ferramentas.busca_texto import buscar_texto
from forja.ferramentas.git_leitura import ler_git
from forja.ferramentas.verificacao import ambiente_limpo
from forja.observabilidade.sanitizar import redigir_segredos, sanitizar_texto
from forja.seguranca.acoes import descrever_acao
from forja.seguranca.sensiveis import caminho_sensivel

log = logging.getLogger("forja.area")
MAX_LER = 2_000_000
MAX_SALVAR = 2_000_000
MAX_SAIDA = 60_000
LINGUAGENS = {".py": "python", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".ts": "typescript", ".tsx": "typescript",
              ".jsx": "javascript", ".json": "json", ".md": "markdown", ".markdown": "markdown", ".css": "css", ".scss": "css",
              ".html": "html", ".htm": "html", ".sql": "sql", ".ps1": "powershell", ".sh": "shell", ".bash": "shell", ".yml": "yaml",
              ".yaml": "yaml", ".toml": "toml", ".ini": "ini", ".cfg": "ini", ".txt": "texto", ".xml": "xml", ".svg": "xml",
              ".rs": "rust", ".go": "go", ".java": "java", ".cs": "csharp", ".c": "c", ".h": "c", ".cpp": "cpp", ".dockerfile": "docker"}
_ID_DOCKER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def _sha(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


def linguagem_de(nome: str) -> str:
    n = nome.lower()
    if n == "dockerfile" or n.endswith(".dockerfile"):
        return "docker"
    return LINGUAGENS.get(Path(n).suffix, "texto")


class AreaTrabalho:
    def __init__(self, projetos: Any) -> None:
        self.projetos = projetos  # ProjetosServico: resolucao segura das pastas do projeto
        self.terminal_ativo = True  # preferencia 'terminal_ativo'
        self.terminal_tempo_s = 120.0

    # ------------------------------------------------------------------ resolucao
    def _pasta(self, projeto_id: str, raiz: int) -> tuple[dict[str, str], Path]:
        projeto = self.projetos.obter(projeto_id)
        pastas = self.projetos.pastas_validas(projeto)
        if not 0 <= raiz < len(pastas):
            raise ValidacaoDominio("pasta do projeto nao encontrada")
        return pastas[raiz], Path(pastas[raiz]["caminho"]).resolve()

    def _arquivo(self, projeto_id: str, raiz: int, rel: str) -> tuple[dict[str, str], Path, Path]:
        if not rel or caminho_sensivel(rel):
            raise ValidacaoDominio("arquivo de segredo (.env, chaves, credenciais) nunca é aberto pelo painel")
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
        return {"rel": alvo.relative_to(base).as_posix(), "nome": alvo.name, "conteudo": texto, "sha": _sha(dados),
                "linguagem": linguagem_de(alvo.name), "tamanho": len(dados), "somente_leitura": pasta.get("papel") != "trabalho",
                "fim_de_linha": "crlf" if b"\r\n" in dados else "lf"}

    def salvar(self, projeto_id: str, raiz: int, rel: str, conteudo: str, sha_esperado: str | None) -> dict[str, Any]:
        pasta, base, alvo = self._arquivo(projeto_id, raiz, rel)
        self._so_trabalho(pasta)
        dados = conteudo.encode("utf-8")
        if len(dados) > MAX_SALVAR:
            raise ValidacaoDominio("conteudo grande demais para o editor do painel")
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

    # ------------------------------------------------------------------ busca e problemas
    def buscar(self, projeto_id: str, raiz: int, padrao: str, regex: bool = False, incluir: str = "", limite: int = 100) -> dict[str, Any]:
        _pasta, base = self._pasta(projeto_id, raiz)
        r = buscar_texto(base, ".", padrao, regex, True, incluir, 0, max(1, min(limite, 200)))
        return {"ocorrencias": r.dados["ocorrencias"], "arquivos": len(r.dados["arquivos"]), "avisos": r.avisos, "truncado": r.truncado}

    def problemas(self, projeto_id: str, raiz: int, rel: str, conteudo: str | None = None) -> dict[str, Any]:
        """Diagnostico do arquivo aberto: JSON (sintaxe), Python (compilacao + ruff, se o projeto tiver). Sem rodar codigo do projeto."""
        _pasta, base, alvo = self._arquivo(projeto_id, raiz, rel)
        texto = conteudo if conteudo is not None else (alvo.read_text(encoding="utf-8", errors="replace") if alvo.is_file() else "")
        lng = linguagem_de(alvo.name)
        itens: list[dict[str, Any]] = []
        if lng == "json":
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

    @staticmethod
    def _ruff(base: Path, alvo: Path, texto: str) -> list[dict[str, Any]]:
        ruff = shutil.which("ruff")
        if not ruff:
            return []
        try:
            r = subprocess.run([ruff, "check", "--no-cache", "--output-format=json", "--stdin-filename", str(alvo), "-"],  # noqa: S603
                               cwd=str(base), input=texto, capture_output=True, text=True, encoding="utf-8", timeout=20,
                               env=ambiente_limpo(), check=False)
            dados = json.loads(r.stdout or "[]")
        except (OSError, subprocess.SubprocessError, ValueError):
            return []
        return [{"linha": (d.get("location") or {}).get("row", 1), "coluna": (d.get("location") or {}).get("column", 1),
                 "gravidade": "aviso", "codigo": str(d.get("code") or "ruff"), "mensagem": str(d.get("message") or "")[:300]}
                for d in dados if isinstance(d, dict)]

    # ------------------------------------------------------------------ Git
    def git(self, projeto_id: str, raiz: int, operacao: str, ref: str = "", arquivo: str = "", limite: int = 30) -> dict[str, Any]:
        _pasta, base = self._pasta(projeto_id, raiz)
        try:
            r = ler_git(base, ".", operacao, ref, "", arquivo, 1, 0, limite)
        except ValidacaoDominio as e:
            if operacao == "status" and "repositorio git" in e.mensagem:  # pasta comum: estado normal, nao erro
                return {"resumo": "a pasta nao e um repositorio git", "dados": {"branch": "", "alterados": [], "repositorio": False}, "avisos": []}
            raise
        return {"resumo": r.resumo, "dados": {**r.dados, "repositorio": True} if operacao == "status" else r.dados, "avisos": r.avisos}

    def git_acao(self, projeto_id: str, raiz: int, acao: str, arquivos: list[str], mensagem: str = "") -> dict[str, Any]:
        pasta, base = self._pasta(projeto_id, raiz)
        self._so_trabalho(pasta)
        for a in arquivos:
            if caminho_sensivel(a) or a.startswith("-") or ".." in Path(a).parts or Path(a).is_absolute():
                raise ValidacaoDominio(f"arquivo nao permitido: {a[:80]}")
        if acao == "stage":
            args = ["add", "--", *arquivos] if arquivos else ["add", "-u"]
        elif acao == "unstage":
            args = ["restore", "--staged", "--", *arquivos] if arquivos else ["reset", "-q"]
        elif acao == "commit":
            msg = (mensagem or "").strip()
            if not msg:
                raise ValidacaoDominio("escreva a mensagem do commit")
            args = ["commit", "-m", msg[:2000]]
        else:
            raise ValidacaoDominio("acao de Git invalida (stage, unstage ou commit)")
        if acao == "commit":
            preparados = self._git(base, ["diff", "--cached", "--name-only"]).splitlines()
            if any(caminho_sensivel(x) for x in preparados):
                raise ValidacaoDominio("há arquivo de segredo preparado para o commit; tire-o (unstage) antes")
        saida = self._git(base, args)
        avisos = []
        if acao == "stage":  # 'add -u' pode pegar um .env versionado: a Forja tira de novo e avisa
            sens = [x for x in self._git(base, ["diff", "--cached", "--name-only"]).splitlines() if caminho_sensivel(x)]
            if sens:
                self._git(base, ["restore", "--staged", "--", *sens])
                avisos.append(f"{len(sens)} arquivo(s) de segredo NAO foram preparados para commit")
        return {"acao": acao, "saida": redigir_segredos(saida)[-4000:], "avisos": avisos}

    @staticmethod
    def _git(base: Path, args: list[str]) -> str:
        env = {**ambiente_limpo(), "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"}
        try:
            r = subprocess.run(["git", "-c", "core.fsmonitor=false", *args], cwd=str(base), env=env, capture_output=True, text=True,  # noqa: S603, S607
                               encoding="utf-8", errors="replace", timeout=30, stdin=subprocess.DEVNULL, check=False)
        except (OSError, subprocess.SubprocessError) as e:
            raise ValidacaoDominio(f"git indisponivel: {type(e).__name__}") from e
        if r.returncode != 0:
            raise ValidacaoDominio("git: " + sanitizar_texto((r.stderr or r.stdout or "falhou").strip().splitlines()[-1])[:300])
        return r.stdout

    # ------------------------------------------------------------------ terminal
    def terminal(self, projeto_id: str, raiz: int, comando: str) -> dict[str, Any]:
        if not self.terminal_ativo:
            raise ValidacaoDominio("terminal desligado (Configurações > Segurança)")
        comando = (comando or "").strip()
        if not comando or len(comando) > 2000:
            raise ValidacaoDominio("comando vazio ou longo demais")
        pasta, base = self._pasta(projeto_id, raiz)
        self._so_trabalho(pasta)
        item = descrever_acao({"kind": "execute", "toolCallId": "terminal", "rawInput": {"command": comando}}, base)
        if item["sensivel"]:
            raise ValidacaoDominio("comando recusado: ele lê ou imprime segredo (.env, chaves ou variáveis de ambiente). "
                                   "Use 'env.verificar' em Ferramentas para conferir um .env.")
        args = (["powershell", "-NoProfile", "-NonInteractive", "-Command", comando] if os.name == "nt"
                else ["bash", "-c", comando])
        s = sandbox.executar(args, base, ambiente_limpo(), self.terminal_tempo_s, "basico")
        saida = redigir_segredos(s.texto[-MAX_SAIDA:])
        return {"comando": sanitizar_texto(comando)[:300], "codigo": s.codigo, "tempo_esgotado": s.esgotado, "saida": saida,
                "risco": item["risco"], "categoria": item["categoria"]}

    # ------------------------------------------------------------------ Docker
    @staticmethod
    def _docker(args: list[str], timeout: float = 20) -> str:
        exe = shutil.which("docker")
        if not exe:
            raise ValidacaoDominio("Docker não encontrado nesta máquina")
        try:
            r = subprocess.run([exe, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,  # noqa: S603
                               env=ambiente_limpo(), stdin=subprocess.DEVNULL, check=False)
        except subprocess.TimeoutExpired as e:
            raise ValidacaoDominio("o Docker não respondeu (o serviço está ligado?)") from e
        except OSError as e:
            raise ValidacaoDominio(f"Docker indisponivel: {type(e).__name__}") from e
        if r.returncode != 0:
            raise ValidacaoDominio("docker: " + sanitizar_texto((r.stderr or "falhou").strip().splitlines()[-1] if r.stderr.strip() else "falhou")[:300])
        return r.stdout

    def docker(self, recurso: str) -> list[dict[str, Any]]:
        fmt = "{{json .}}"
        if recurso == "containers":
            bruto = self._docker(["ps", "-a", "--format", fmt])
            campos = ("ID", "Names", "Image", "State", "Status", "Ports")
        elif recurso == "imagens":
            bruto = self._docker(["images", "--format", fmt])
            campos = ("ID", "Repository", "Tag", "Size", "CreatedSince")
        elif recurso == "compose":
            bruto = self._docker(["compose", "ls", "--format", "json"])
            try:
                return [{k: str(v)[:200] for k, v in d.items() if k in ("Name", "Status")} for d in json.loads(bruto or "[]")]
            except ValueError:
                return []
        else:
            raise ValidacaoDominio("recurso invalido (containers, imagens, compose)")
        saida = []
        for linha in bruto.splitlines():
            try:
                d = json.loads(linha)
            except ValueError:
                continue
            saida.append({k: str(d.get(k, ""))[:200] for k in campos})
        return saida[:300]

    def docker_logs(self, id_: str, linhas: int = 200) -> dict[str, Any]:
        if not _ID_DOCKER.match(id_ or ""):
            raise ValidacaoDominio("container invalido")
        bruto = self._docker(["logs", "--tail", str(max(1, min(linhas, 2000))), id_], 30)
        return {"id": id_, "saida": redigir_segredos(bruto[-MAX_SAIDA:])}

    def docker_acao(self, id_: str, acao: str) -> dict[str, Any]:
        if not _ID_DOCKER.match(id_ or "") or acao not in ("start", "stop", "restart"):
            raise ValidacaoDominio("container ou acao invalida (start, stop, restart)")
        self._docker([acao, id_], 60)
        return {"id": id_, "acao": acao}
