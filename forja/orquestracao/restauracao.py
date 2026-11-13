"""Pontos de restauracao: desfazer as alteracoes de UMA tarefa na pasta de trabalho.

Antes de uma execucao que pode escrever, a Forja fotografa a pasta (hash de cada arquivo + copia do conteudo, enderecada por
conteudo, fora do Git e fora da pasta do projeto). Ao terminar, fotografa de novo e guarda a diferenca. Desfazer:
- restaura arquivos alterados ou apagados pela execucao e remove os que ela criou;
- SO mexe em arquivos que continuam exatamente como a execucao os deixou (mesmo hash). Se voce mexeu depois, o arquivo vira
  conflito e fica intocado (a menos que voce force);
- nunca le nem copia arquivos com cara de segredo (.env, chaves), links simbolicos, pastas ignoradas (.git, node_modules...)
  nem arquivos grandes: esses ficam de fora e isso e informado (`ignorados`).
Melhor esforco: falhar aqui nunca impede a execucao (a execucao so perde a opcao de desfazer).
"""

from __future__ import annotations

import hashlib
import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from forja.adapters.sqlite import tabelas as T
from forja.adapters.sqlite.repositorio import RepositorioSqlite, novo_id
from forja.dominio.erros import Conflito, NaoEncontrado
from forja.dominio.tempo import Relogio, RelogioSistema, iso
from forja.memoria.indexador import IGNORAR_DIRS
from forja.seguranca.acoes import caminho_sensivel

log = logging.getLogger("forja.restauracao")

MODOS_QUE_ESCREVEM = frozenset({"alteracao_codigo", "verificacao", "documentacao"})


@dataclass(frozen=True)
class Limites:
    max_arquivo: int = 5_000_000  # bytes por arquivo
    max_arquivos: int = 20_000
    max_total: int = 300_000_000  # bytes copiados por ponto


def _ignorar_dir(nome: str) -> bool:
    return nome in IGNORAR_DIRS or nome.endswith(".egg-info") or nome in (".worktrees", ".forja")


class PontosRestauracao:
    def __init__(self, repo: RepositorioSqlite, dir_blobs: Path, relogio: Relogio | None = None, limites: Limites | None = None) -> None:
        self.repo = repo
        self.dir_blobs = dir_blobs
        self.relogio = relogio or RelogioSistema()
        self.limites = limites or Limites()

    # ------------------------------------------------------------------ foto
    def _ts(self) -> str:
        return iso(self.relogio.agora())

    def _blob(self, sha: str) -> Path:
        return self.dir_blobs / sha[:2] / sha

    def _guardar(self, sha: str, dados: bytes) -> None:
        destino = self._blob(sha)
        if destino.exists():
            return
        destino.parent.mkdir(parents=True, exist_ok=True)
        tmp = destino.with_name(f"{sha}.{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_bytes(dados)
            try:
                tmp.replace(destino)
            except OSError:
                if not destino.exists():
                    raise
        finally:
            tmp.unlink(missing_ok=True)

    def _fotografar(self, pasta: Path, copiar: bool) -> tuple[dict[str, str], dict[str, Any]]:
        """{relativo: sha256} dos arquivos elegiveis. `copiar` guarda o conteudo (foto 'antes')."""
        lim = self.limites
        mapa: dict[str, str] = {}
        info: dict[str, Any] = {"ignorados": 0, "parcial": False}
        total = 0
        base = pasta.resolve()
        for atual, dirs, nomes in os.walk(base, followlinks=False):
            dirs[:] = sorted(d for d in dirs if not _ignorar_dir(d) and not Path(atual, d).is_symlink())
            for nome in sorted(nomes):
                p = Path(atual) / nome
                rel = p.relative_to(base).as_posix()
                if caminho_sensivel(rel) or p.is_symlink():
                    info["ignorados"] += 1
                    continue
                try:
                    tam = p.stat().st_size
                    if tam > lim.max_arquivo:
                        info["ignorados"] += 1
                        continue
                    if len(mapa) >= lim.max_arquivos or (copiar and total + tam > lim.max_total):
                        info["parcial"] = True
                        return mapa, info
                    dados = p.read_bytes()
                except OSError:
                    info["ignorados"] += 1
                    continue
                sha = hashlib.sha256(dados).hexdigest()
                if copiar:
                    self._guardar(sha, dados)
                    total += tam
                mapa[rel] = sha
        return mapa, info

    def capturar(self, execucao_id: str, tarefa_id: str, pasta: Path) -> str | None:
        """Foto 'antes'. Devolve o id do ponto ou None (pasta inexistente ou falha; a execucao segue sem desfazer)."""
        try:
            if not pasta.is_dir():
                return None
            antes, info = self._fotografar(pasta, copiar=True)
            with self.repo.escrita() as t:
                pid = novo_id("PR")
                t.inserir(T.PontoRestauracao, id=pid, execucao_id=execucao_id, tarefa_id=tarefa_id, pasta=str(pasta.resolve()),
                          estado="capturado", antes=antes, depois=None, resumo={"ignorados": info["ignorados"]},
                          parcial=info["parcial"], criado_em=self._ts())
                t.emitir_evento("restauracao.capturada", self._ts(), {"ponto_id": pid, "arquivos": len(antes), "parcial": info["parcial"],
                                                                       "ignorados": info["ignorados"]},
                                tarefa_id=tarefa_id, execucao_id=execucao_id)
            return pid
        except Exception:  # noqa: BLE001 - desfazer e protecao extra; nunca impede a execucao
            log.exception("falha ao capturar ponto de restauracao", extra={"execucao_id": execucao_id})
            return None

    def finalizar(self, ponto_id: str) -> dict[str, Any] | None:
        """Foto 'depois' (sem copiar) e o resumo da diferenca."""
        try:
            with self.repo.leitura() as t:
                p = t.obter(T.PontoRestauracao, ponto_id)
            if p is None or p["estado"] != "capturado":
                return None
            depois, _info = self._fotografar(Path(p["pasta"]), copiar=False)
            antes = p["antes"] or {}
            resumo = {
                "alterados": sorted(k for k in antes.keys() & depois.keys() if antes[k] != depois[k]),
                "adicionados": sorted(depois.keys() - antes.keys()),
                "removidos": sorted(antes.keys() - depois.keys()),
                "ignorados": (p["resumo"] or {}).get("ignorados", 0),
            }
            mudou = bool(resumo["alterados"] or resumo["adicionados"] or resumo["removidos"])
            with self.repo.escrita() as t:
                t.atualizar(T.PontoRestauracao, ponto_id, depois=depois, resumo=resumo,
                            estado="finalizado" if mudou else "sem_mudancas", finalizado_em=self._ts())
                t.emitir_evento("restauracao.finalizada", self._ts(), {"ponto_id": ponto_id, **{k: len(v) for k, v in resumo.items()
                                                                                               if isinstance(v, list)}},
                                tarefa_id=p["tarefa_id"], execucao_id=p["execucao_id"])
            return resumo
        except Exception:  # noqa: BLE001
            log.exception("falha ao finalizar ponto de restauracao", extra={"ponto_id": ponto_id})
            return None

    # ------------------------------------------------------------------ consulta e desfazer
    @staticmethod
    def _publico(p: dict[str, Any]) -> dict[str, Any]:
        r = p.get("resumo") or {}
        return {"id": p["id"], "execucao_id": p["execucao_id"], "tarefa_id": p["tarefa_id"], "estado": p["estado"], "parcial": p["parcial"],
                "pasta": Path(p["pasta"]).name, "criado_em": p["criado_em"], "finalizado_em": p["finalizado_em"], "desfeito_em": p["desfeito_em"],
                "alterados": r.get("alterados", [])[:200], "adicionados": r.get("adicionados", [])[:200], "removidos": r.get("removidos", [])[:200],
                "ignorados": r.get("ignorados", 0), "pode_desfazer": p["estado"] == "finalizado"}

    def listar(self, tarefa_id: str) -> list[dict[str, Any]]:
        with self.repo.leitura() as t:
            return [self._publico(p) for p in t.listar(T.PontoRestauracao, tarefa_id=tarefa_id, limite=50)]

    def tem_desfazer(self, tarefa_ids: list[str]) -> set[str]:
        if not tarefa_ids:
            return set()
        with self.repo.leitura() as t:
            linhas = t.s.query(T.PontoRestauracao.tarefa_id).filter(
                T.PontoRestauracao.tarefa_id.in_(tarefa_ids), T.PontoRestauracao.estado == "finalizado").all()
        return {x[0] for x in linhas}

    def desfazer(self, ponto_id: str, forcar: bool = False, ator: str = "operador") -> dict[str, Any]:
        with self.repo.leitura() as t:
            p = t.obter(T.PontoRestauracao, ponto_id)
        if p is None:
            raise NaoEncontrado(f"Ponto de restauracao {ponto_id} nao encontrado.")
        if p["estado"] != "finalizado":
            raise Conflito(f"Nada a desfazer (estado: {p['estado']}).")
        with self.repo.leitura() as t:  # so a execucao mais recente da pasta pode ser desfeita sem forcar (ordem segura)
            posteriores = [x for x in t.listar(T.PontoRestauracao, estado="finalizado", limite=5000)
                           if x["pasta"] == p["pasta"] and x["criado_em"] > p["criado_em"]]
        if posteriores and not forcar:
            raise Conflito("Ha execucoes mais novas nesta pasta; desfaca primeiro a mais recente (ou force).")
        base = Path(p["pasta"]).resolve()
        antes, depois = p["antes"] or {}, p["depois"] or {}
        r = p["resumo"] or {}
        restaurados, removidos, conflitos = [], [], []

        def alvo(rel: str) -> Path | None:
            destino = (base / rel).resolve()
            return destino if base in destino.parents and not caminho_sensivel(rel) else None

        def atual_sha(destino: Path) -> str | None:
            if not destino.is_file() or destino.is_symlink():
                return None
            try:
                return hashlib.sha256(destino.read_bytes()).hexdigest()
            except OSError:
                return "?"

        for rel in r.get("alterados", []) + r.get("removidos", []):
            destino = alvo(rel)
            if destino is None:
                continue
            agora = atual_sha(destino)
            esperado = depois.get(rel)  # None = a execucao apagou
            if agora != esperado and agora != antes.get(rel) and not forcar:
                conflitos.append(rel)
                continue
            if agora == antes.get(rel):
                continue
            blob = self._blob(antes[rel])
            if not blob.is_file():
                conflitos.append(rel)
                continue
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(blob.read_bytes())
            restaurados.append(rel)
        for rel in r.get("adicionados", []):
            destino = alvo(rel)
            if destino is None:
                continue
            agora = atual_sha(destino)
            if agora is None:
                continue
            if agora != depois.get(rel) and not forcar:
                conflitos.append(rel)
                continue
            destino.unlink(missing_ok=True)
            removidos.append(rel)
        estado = "desfeito" if not conflitos else "finalizado"
        with self.repo.escrita() as t:
            if not conflitos:
                t.atualizar(T.PontoRestauracao, ponto_id, estado=estado, desfeito_em=self._ts())
            t.emitir_evento("restauracao.desfeita" if not conflitos else "restauracao.conflito", self._ts(),
                            {"ponto_id": ponto_id, "restaurados": len(restaurados), "removidos": len(removidos), "conflitos": len(conflitos),
                             "forcado": forcar, "ator": ator[:60]}, tarefa_id=p["tarefa_id"], execucao_id=p["execucao_id"])
        return {"ponto_id": ponto_id, "estado": estado, "restaurados": restaurados, "removidos": removidos, "conflitos": conflitos}
