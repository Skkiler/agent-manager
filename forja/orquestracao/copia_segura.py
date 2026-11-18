"""Copia de trabalho SEM segredos: o agente trabalha numa copia da pasta que nao tem .env, chaves nem credenciais.

Por que existe (achado no Kiro real): no nivel 'total', um comando de busca inofensivo (Get-ChildItem -Recurse | Select-String)
leu o .env e o valor entrou no contexto do modelo. Regras e orientacoes reduzem o risco, mas so tirar o segredo do alcance
garante. Fluxo:
1. antes de executar, a Forja copia a pasta de trabalho para `<pasta>/.forja-copias/<execucao>/`, SEM arquivos de segredo, sem
   .git e sem pastas de dependencias (node_modules, .venv...), e guarda um manifesto (tamanho + hash) do que copiou;
2. o agente trabalha na copia (o .env da pasta original fica FORA da pasta de trabalho dele: ler exige permissao e e negado);
3. ao terminar, a Forja devolve para a pasta original SO o que o agente mudou, e so onde voce nao mexeu nesse meio-tempo.
   Arquivo que voce alterou e o agente tambem vira CONFLITO: nada e sobrescrito; a copia fica guardada para voce comparar.
   Arquivos de segredo nunca voltam (nem os que o agente criar). Depois a copia e apagada.
A copia fica DENTRO da pasta original de proposito: o Node acha node_modules subindo pastas e a verificacao acha a .venv do projeto.
No Git, a pasta entra no exclude LOCAL (.git/info/exclude), sem alterar arquivo versionado.
Melhor esforco com falha segura: se a copia nao puder ser feita (pasta grande demais, erro de disco), a execucao continua na pasta
original com as outras protecoes (perfil DENY, mediador, aviso de varredura) e isso vira evento.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from forja.seguranca.sensiveis import DEPENDENCIAS, caminho_sensivel, segredos_nas_pastas

log = logging.getLogger("forja.copia_segura")
PASTA = ".forja-copias"
MODOS = ("autonomia", "sempre", "desligado")
MODOS_QUE_ESCREVEM = frozenset({"alteracao_codigo", "verificacao", "documentacao"})
MAX_ARQUIVOS = 20_000
MAX_BYTES = 400 * 1024 * 1024
LIMITE_HASH = 8 * 1024 * 1024  # acima disto, o manifesto usa tamanho + data (hash custaria caro)
# O que nao vai para a copia: dependencias/caches (pesados e reconstruiveis) e a propria area de copias.
PULAR = frozenset(DEPENDENCIAS | {"dist", "build", "htmlcov", ".tox", ".nox", ".idea", ".next", ".turbo", PASTA, ".worktrees"})


@dataclass
class _Copia:
    origem: Path
    destino: Path
    manifesto: dict[str, tuple[int, str]] = field(default_factory=dict)  # rel -> (tamanho, hash ou "mtime:<ns>")


def _assinatura(p: Path) -> tuple[int, str]:
    st = p.stat()
    if st.st_size > LIMITE_HASH:
        return st.st_size, f"mtime:{st.st_mtime_ns}"
    h = hashlib.sha256()
    with p.open("rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return st.st_size, h.hexdigest()


def _pular_dir(nome: str) -> bool:
    return nome in PULAR or nome.endswith(".egg-info")


def _arquivos(base: Path):
    """(relativo, caminho) de tudo que entra/volta: sem segredos, sem links simbolicos, sem dependencias/caches."""
    for atual, dirs, nomes in os.walk(base, followlinks=False):
        rel_dir = Path(atual).relative_to(base).as_posix()
        dirs[:] = [d for d in dirs if not _pular_dir(d) and not Path(atual, d).is_symlink()
                   and not caminho_sensivel(d if rel_dir == "." else f"{rel_dir}/{d}")]
        for nome in nomes:
            rel = nome if rel_dir == "." else f"{rel_dir}/{nome}"
            p = Path(atual) / nome
            if p.is_symlink() or caminho_sensivel(rel):
                continue
            yield rel, p


def _excluir_no_git(pasta: Path) -> None:
    """Coloca /.forja-copias/ no exclude LOCAL do repositorio (se for git). Nao altera arquivo versionado."""
    try:
        r = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=str(pasta), capture_output=True, text=True,  # noqa: S603, S607
                           timeout=10, stdin=subprocess.DEVNULL, check=False, encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return
    if r.returncode != 0 or not r.stdout.strip():
        return
    gitdir = Path(r.stdout.strip())
    gitdir = gitdir if gitdir.is_absolute() else pasta / gitdir
    exclude = gitdir / "info" / "exclude"
    try:
        atual = exclude.read_text(encoding="utf-8", errors="replace") if exclude.is_file() else ""
        linha = f"/{PASTA}/"
        if linha not in atual.splitlines() and f"{PASTA}/" not in atual.splitlines():
            exclude.parent.mkdir(parents=True, exist_ok=True)
            exclude.write_text(atual + ("" if atual.endswith("\n") or not atual else "\n") + linha + "\n", encoding="utf-8")
    except OSError:
        pass


class CopiasSemSegredos:
    def __init__(self) -> None:
        self.modo = "autonomia"  # preferencia 'copia_sem_segredos': autonomia | sempre | desligado
        self._ativas: dict[str, list[_Copia]] = {}
        self._mu = threading.Lock()

    # ------------------------------------------------------------------ decisao
    def precisa(self, nivel: str, modo_tarefa: str | None, pasta: Path) -> bool:
        """'autonomia' (padrao): niveis em que o agente edita/roda comandos sem perguntar (liberado/total) em tarefa que escreve.
        'sempre': toda tarefa com pasta de trabalho. Em qualquer caso, so se a pasta TIVER arquivo com cara de segredo."""
        if self.modo == "desligado":
            return False
        if self.modo == "autonomia" and (nivel not in ("liberado", "total") or modo_tarefa not in MODOS_QUE_ESCREVEM):
            return False
        achados, completa = segredos_nas_pastas([pasta])
        return bool(achados) or not completa

    # ------------------------------------------------------------------ criar
    def criar(self, execucao_id: str, pasta: Path) -> _Copia | None:
        """Copia `pasta` sem segredos. None = nao deu (grande demais ou erro): o chamador segue na original com as outras protecoes."""
        origem = pasta.resolve()
        destino = origem / PASTA / f"{execucao_id[-12:]}-{uuid.uuid4().hex[:6]}"
        copia = _Copia(origem, destino)
        n, total = 0, 0
        try:
            destino.mkdir(parents=True, exist_ok=False)
            _excluir_no_git(origem)
            for rel, p in _arquivos(origem):
                n += 1
                total += p.stat().st_size
                if n > MAX_ARQUIVOS or total > MAX_BYTES:
                    raise _Grande(f"{n} arquivos / {total // (1024 * 1024)} MB")
                alvo = destino / rel
                alvo.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, alvo)
                copia.manifesto[rel] = _assinatura(alvo)
        except _Grande as e:
            log.info("copia sem segredos nao feita: pasta grande demais (%s)", e)
            shutil.rmtree(destino, ignore_errors=True)
            return None
        except OSError as e:
            log.warning("copia sem segredos falhou: %s", type(e).__name__)
            shutil.rmtree(destino, ignore_errors=True)
            return None
        with self._mu:
            self._ativas.setdefault(execucao_id, []).append(copia)
        return copia

    def ativas(self, execucao_id: str) -> list[_Copia]:
        with self._mu:
            return list(self._ativas.get(execucao_id, []))

    # ------------------------------------------------------------------ devolver
    def sincronizar(self, execucao_id: str) -> list[dict[str, Any]]:
        """Devolve as mudancas do agente para as pastas originais. Um resumo por copia:
        {pasta, aplicados, criados, removidos, conflitos, segredos_ignorados, copia_mantida}."""
        with self._mu:
            copias = self._ativas.pop(execucao_id, [])
        return [self._sincronizar(c) for c in copias]

    def _sincronizar(self, c: _Copia) -> dict[str, Any]:
        res: dict[str, Any] = {"pasta": c.origem.name, "aplicados": [], "criados": [], "removidos": [], "conflitos": [],
                               "segredos_ignorados": 0, "copia_mantida": None}
        if not c.destino.is_dir():
            return res
        try:
            na_copia = dict(_arquivos(c.destino))
            for nome in self._segredos_criados(c.destino):
                res["segredos_ignorados"] += 1
                log.info("arquivo de segredo criado na copia nao volta para a pasta original", extra={"arquivo": nome[:80]})
            for rel, p in na_copia.items():
                orig = c.origem / rel
                antes = c.manifesto.get(rel)
                agora = _assinatura(p)
                if antes is not None and agora == antes:
                    continue  # o agente nao mexeu
                if antes is None:  # arquivo novo do agente
                    if orig.exists():
                        res["conflitos"].append(rel)  # voce criou um arquivo com o mesmo nome no meio-tempo
                        continue
                    orig.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(p, orig)
                    res["criados"].append(rel)
                    continue
                if not orig.exists() or _assinatura(orig) != antes:
                    res["conflitos"].append(rel)  # voce mudou (ou apagou) o arquivo enquanto o agente trabalhava
                    continue
                tmp = orig.with_name(f".{orig.name}.forja-{uuid.uuid4().hex[:6]}.tmp")
                shutil.copy2(p, tmp)
                os.replace(tmp, orig)
                res["aplicados"].append(rel)
            for rel, antes in c.manifesto.items():
                if rel in na_copia:
                    continue
                orig = c.origem / rel  # o agente apagou o arquivo na copia
                if orig.exists() and _assinatura(orig) == antes:
                    orig.unlink()
                    res["removidos"].append(rel)
                elif orig.exists():
                    res["conflitos"].append(rel)
        except OSError as e:
            log.warning("falha ao devolver as mudancas da copia: %s", type(e).__name__)
            res["conflitos"].append(f"(erro ao devolver: {type(e).__name__})")
        if res["conflitos"]:
            res["copia_mantida"] = str(c.destino)  # nada se perde: voce compara e decide
        else:
            shutil.rmtree(c.destino, ignore_errors=True)
            try:
                (c.origem / PASTA).rmdir()  # so se ficou vazia
            except OSError:
                pass
        return res

    @staticmethod
    def _segredos_criados(base: Path) -> list[str]:
        achados, _ = segredos_nas_pastas([base])
        return achados

    def descartar(self, execucao_id: str) -> None:
        """Apaga as copias sem devolver nada (execucao cancelada antes de trabalhar)."""
        with self._mu:
            copias = self._ativas.pop(execucao_id, [])
        for c in copias:
            shutil.rmtree(c.destino, ignore_errors=True)


class _Grande(Exception):
    pass
