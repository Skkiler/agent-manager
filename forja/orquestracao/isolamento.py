"""Pastas isoladas para tarefas em paralelo.

Duas execucoes escrevendo na MESMA pasta se atropelam. Ao iniciar uma execucao, a Forja reserva cada pasta de trabalho:
- pasta livre: a execucao usa a pasta original;
- pasta ocupada e repositorio git: cria uma copia isolada (`git worktree`) em `<repositorio>/.worktrees/`, num branch proprio
  `forja/<tarefa>-<exec>`. O branch fica para voce revisar e juntar; nada e mesclado sozinho;
- pasta ocupada e sem git: a execucao NAO comeca (falha fechada) e diz qual tarefa ocupa a pasta.
Observacao: o worktree parte do ultimo commit (HEAD); alteracoes nao commitadas da pasta original nao vao para a copia.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
from pathlib import Path
from typing import Any

from forja.adapters.sqlite import tabelas as T
from forja.adapters.sqlite.repositorio import RepositorioSqlite
from forja.dominio.erros import Conflito, NaoEncontrado
from forja.dominio.tempo import Relogio, RelogioSistema, iso
from forja.ferramentas.verificacao import ambiente_limpo

log = logging.getLogger("forja.isolamento")
_SEGURO = re.compile(r"[^A-Za-z0-9._-]+")


def _norm(p: Path) -> str:
    s = str(p.resolve())
    return s.lower() if os.name == "nt" else s


def _git(args: list[str], cwd: Path, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    env = {**ambiente_limpo(), "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"}
    return subprocess.run(["git", *args], cwd=str(cwd), env=env, capture_output=True, text=True,  # noqa: S603, S607 - lista fixa, sem shell
                          encoding="utf-8", errors="replace", timeout=timeout, stdin=subprocess.DEVNULL, check=False)


def raiz_git(pasta: Path) -> Path | None:
    try:
        r = _git(["rev-parse", "--show-toplevel"], pasta, 15)
    except (OSError, subprocess.SubprocessError):
        return None
    return Path(r.stdout.strip()).resolve() if r.returncode == 0 and r.stdout.strip() else None


class Isolamento:
    def __init__(self, repo: RepositorioSqlite, relogio: Relogio | None = None) -> None:
        self.repo = repo
        self.relogio = relogio or RelogioSistema()
        self.ativo = True  # preferencia: False = nunca cria worktree (pasta ocupada sempre bloqueia)
        self._ocupadas: dict[str, str] = {}  # pasta normalizada -> execucao_id
        self._mu = threading.Lock()

    def ocupante(self, pasta: Path) -> str | None:
        with self._mu:
            return self._ocupadas.get(_norm(pasta))

    def reservar(self, execucao_id: str, tarefa_id: str, pastas: list[dict[str, Any]],
                 forcar: bool = False) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
        """Devolve (pastas efetivas, areas criadas, motivo de bloqueio). Reserva atomica: ou todas, ou nenhuma.
        `forcar`: a tarefa pediu copia isolada mesmo com a pasta livre (politica sandbox=worktree)."""
        efetivas: list[dict[str, Any]] = []
        areas: list[dict[str, Any]] = []
        reservadas: list[str] = []
        with self._mu:
            for item in pastas:
                if item.get("papel") != "trabalho":
                    efetivas.append(item)
                    continue
                pasta = Path(item["caminho"])
                chave = _norm(pasta)
                dono = self._ocupadas.get(chave)
                if forcar and dono is None:  # politica da tarefa 'sandbox: worktree': sempre numa copia isolada
                    dono = "politica_sandbox_worktree"
                if dono is None or dono == execucao_id:
                    self._ocupadas[chave] = execucao_id
                    reservadas.append(chave)
                    efetivas.append(item)
                    continue
                area = self._criar_area(execucao_id, tarefa_id, pasta) if self.ativo else None
                if area is None:
                    for c in reservadas:
                        self._ocupadas.pop(c, None)
                    if dono == "politica_sandbox_worktree":
                        return pastas, [], (f"isolamento_indisponivel: a tarefa pede copia isolada (sandbox=worktree), mas "
                                            f"'{pasta.name}' nao e um repositorio git" + ("" if self.ativo else " ou o isolamento esta desligado"))
                    return pastas, [], (f"pasta_ocupada: a pasta '{pasta.name}' esta em uso pela execucao {dono}; "
                                        "aguarde terminar" + (" (sem git nao ha como isolar)" if self.ativo else ""))
                self._ocupadas[_norm(Path(area["caminho_efetivo"]))] = execucao_id
                reservadas.append(_norm(Path(area["caminho_efetivo"])))
                areas.append(area)
                efetivas.append({**item, "caminho": area["caminho_efetivo"], "isolada": True})
        return efetivas, areas, None

    @staticmethod
    def _excluir_localmente(topo: Path) -> None:
        r = _git(["rev-parse", "--git-common-dir"], topo, 15)
        if r.returncode != 0 or not r.stdout.strip():
            return
        gitdir = Path(r.stdout.strip())
        gitdir = gitdir if gitdir.is_absolute() else (topo / gitdir)
        exclude = gitdir / "info" / "exclude"
        atual = exclude.read_text(encoding="utf-8", errors="replace") if exclude.is_file() else ""
        if "/.worktrees/" not in atual.splitlines():
            exclude.parent.mkdir(parents=True, exist_ok=True)
            exclude.write_text(atual + ("" if atual.endswith("\n") or not atual else "\n") + "/.worktrees/\n", encoding="utf-8")

    def liberar(self, execucao_id: str) -> int:
        """Devolve quantas pastas foram liberadas (0 = esta execucao nao segurava nenhuma)."""
        with self._mu:
            chaves = [k for k, v in self._ocupadas.items() if v == execucao_id]
            for chave in chaves:
                self._ocupadas.pop(chave, None)
        return len(chaves)

    def _criar_area(self, execucao_id: str, tarefa_id: str, pasta: Path) -> dict[str, Any] | None:
        topo = raiz_git(pasta)
        if topo is None:
            return None
        nome = _SEGURO.sub("-", f"{tarefa_id}-{execucao_id[-6:]}")[:80]
        branch = f"forja/{nome}"
        # Dentro do proprio repositorio (convencao .worktrees/), e nao na area de dados da Forja: o perfil do Kiro NEGA a area de
        # dados, entao o agente nao conseguiria trabalhar la. A pasta entra no exclude LOCAL do git (nao altera arquivo versionado).
        destino = (topo / ".worktrees" / nome).resolve()
        try:
            self._excluir_localmente(topo)
            r = _git(["worktree", "add", "-b", branch, str(destino), "HEAD"], topo)
            if r.returncode != 0:
                log.warning("git worktree falhou (codigo %s)", r.returncode)
                return None
        except (OSError, subprocess.SubprocessError) as e:
            log.warning("git worktree indisponivel: %s", type(e).__name__)
            return None
        relativo = pasta.resolve().relative_to(topo) if pasta.resolve() != topo else Path()
        efetivo = destino / relativo
        agora = iso(self.relogio.agora())
        with self.repo.escrita() as t:
            t.inserir(T.AreaIsolada, id=execucao_id, tarefa_id=tarefa_id, pasta_origem=str(topo), caminho=str(destino), branch=branch,
                      estado="ativa", criado_em=agora)
            t.emitir_evento("isolamento.criado", agora, {"branch": branch, "pasta": pasta.name}, tarefa_id=tarefa_id, execucao_id=execucao_id)
        return {"id": execucao_id, "branch": branch, "caminho": str(destino), "caminho_efetivo": str(efetivo)}

    # ------------------------------------------------------------------ gestao pela tela
    def listar(self, incluir_removidas: bool = False) -> list[dict[str, Any]]:
        with self.repo.leitura() as t:
            linhas = t.listar(T.AreaIsolada, limite=500)
        return [{"id": a["id"], "tarefa_id": a["tarefa_id"], "branch": a["branch"], "pasta": Path(a["pasta_origem"]).name,
                 "estado": a["estado"], "criado_em": a["criado_em"], "removida_em": a["removida_em"]}
                for a in linhas if incluir_removidas or a["estado"] == "ativa"]

    def remover(self, area_id: str) -> dict[str, Any]:
        """Remove a COPIA (git worktree remove). O branch continua no repositorio: o trabalho nunca e perdido."""
        with self.repo.leitura() as t:
            a = t.obter(T.AreaIsolada, area_id)
        if a is None:
            raise NaoEncontrado(f"Area isolada {area_id} nao encontrada.")
        if a["estado"] != "ativa":
            raise Conflito("Area isolada ja removida.")
        with self._mu:
            if area_id in self._ocupadas.values():
                raise Conflito("A execucao ainda esta usando esta area; aguarde terminar.")
        destino = Path(a["caminho"])
        if destino.exists():
            r = _git(["worktree", "remove", str(destino)], Path(a["pasta_origem"]))
            if r.returncode != 0:  # alteracoes nao commitadas na copia: nao apaga trabalho sem pedir
                raise Conflito("A copia tem alteracoes nao commitadas; faca commit no branch (ou descarte) antes de remover.")
        agora = iso(self.relogio.agora())
        with self.repo.escrita() as t:
            t.atualizar(T.AreaIsolada, area_id, estado="removida", removida_em=agora)
            t.emitir_evento("isolamento.removido", agora, {"branch": a["branch"]}, tarefa_id=a["tarefa_id"], execucao_id=area_id)
        return {"id": area_id, "estado": "removida", "branch": a["branch"]}
