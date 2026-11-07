"""Repositorio operacional SQLite. Sem regras de negocio: apenas persistencia atomica."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from fnmatch import fnmatch
from typing import Any

from sqlalchemy import Engine, delete, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from forja.adapters.sqlite import tabelas as T
from forja.dominio.erros import LockIndisponivel
from forja.observabilidade.sanitizar import sanitizar


def novo_id(prefixo: str) -> str:
    return f"{prefixo}-{uuid.uuid4().hex[:12]}"


def _dict(row: Any) -> dict[str, Any]:
    return {c.key: getattr(row, c.key) for c in row.__table__.columns}


def _norm(p: str) -> str:
    return p.replace("\\", "/").lower()


def _sobrepoe(a: str, b: str) -> bool:
    a, b = _norm(a), _norm(b)
    return a == b or fnmatch(a, b) or fnmatch(b, a)


class Tx:
    """Unidade de trabalho. Todos os metodos operam na mesma transacao."""

    def __init__(self, s: Session) -> None:
        self.s = s

    # ---- genericos ----
    def inserir(self, cls: type, **campos: Any) -> dict[str, Any]:
        obj = cls(**campos)
        self.s.add(obj)
        self.s.flush()
        return _dict(obj)

    def obter(self, cls: type, id_: str) -> dict[str, Any] | None:
        obj = self.s.get(cls, id_)
        return None if obj is None else _dict(obj)

    def listar(self, cls: type, ordem: Any = None, limite: int = 500, **filtros: Any) -> list[dict[str, Any]]:
        q = select(cls)
        for k, v in filtros.items():
            if v is not None:
                q = q.where(getattr(cls, k) == v)
        q = q.order_by(ordem if ordem is not None else cls.criado_em).limit(limite)
        return [_dict(o) for o in self.s.scalars(q)]

    def atualizar(self, cls: type, id_: str, **campos: Any) -> None:
        self.s.execute(update(cls).where(cls.id == id_).values(**campos))

    # ---- tarefa com concorrencia otimista ----
    def atualizar_tarefa_condicional(
        self, tarefa_id: str, estado_atual: str, versao_esperada: int, **campos: Any
    ) -> bool:
        res = self.s.execute(
            update(T.Tarefa)
            .where(
                T.Tarefa.id == tarefa_id,
                T.Tarefa.versao_estado == versao_esperada,
                T.Tarefa.estado == estado_atual,
            )
            .values(versao_estado=versao_esperada + 1, **campos)
        )
        return res.rowcount == 1

    def contar_evidencias(self, tarefa_id: str) -> int:
        q = select(func.count()).select_from(T.Evidencia).where(T.Evidencia.tarefa_id == tarefa_id)
        return self.s.scalar(q) or 0

    def tarefas_por_estado(self, objetivo_id: str) -> dict[str, int]:
        q = select(T.Tarefa.estado, func.count()).where(T.Tarefa.objetivo_id == objetivo_id).group_by(T.Tarefa.estado)
        return {e: n for e, n in self.s.execute(q)}

    # ---- eventos ----
    def emitir_evento(
        self,
        tipo: str,
        ts: str,
        payload: dict[str, Any] | None = None,
        projeto_id: str | None = None,
        tarefa_id: str | None = None,
        execucao_id: str | None = None,
        correlation_id: str | None = None,
        dedup_key: str | None = None,
    ) -> int | None:
        if dedup_key is not None:
            existente = self.s.scalar(select(T.Evento.seq).where(T.Evento.dedup_key == dedup_key))
            if existente is not None:
                return None  # duplicado: nao grava de novo
        ev = T.Evento(
            event_id=uuid.uuid4().hex,
            dedup_key=dedup_key,
            tipo=tipo,
            ts=ts,
            projeto_id=projeto_id,
            tarefa_id=tarefa_id,
            execucao_id=execucao_id,
            correlation_id=correlation_id,
            payload=sanitizar(payload or {}),
        )
        self.s.add(ev)
        self.s.flush()
        return ev.seq

    def eventos_apos(self, seq: int, limite: int = 500, projeto_id: str | None = None) -> list[dict[str, Any]]:
        q = select(T.Evento).where(T.Evento.seq > seq)
        if projeto_id:
            q = q.where(T.Evento.projeto_id == projeto_id)
        q = q.order_by(T.Evento.seq).limit(limite)
        return [_dict(e) for e in self.s.scalars(q)]

    def ultimo_seq(self) -> int:
        return self.s.scalar(select(func.max(T.Evento.seq))) or 0

    # ---- locks ----
    def purgar_locks_expirados(self, agora_iso: str) -> int:
        return self.s.execute(delete(T.RecursoLock).where(T.RecursoLock.expira_em <= agora_iso)).rowcount

    def adquirir_locks(self, recursos: list[str], titular: str, agora_iso: str, expira_iso: str) -> None:
        self.purgar_locks_expirados(agora_iso)
        outros = [(r.recurso, r.titular) for r in self.s.scalars(select(T.RecursoLock)) if r.titular != titular]
        for novo in recursos:
            for existente, dono in outros:
                if _sobrepoe(novo, existente):
                    raise LockIndisponivel(f"Recurso {novo!r} em conflito com lock de {dono} ({existente!r}).")
        for novo in recursos:
            atual = self.s.get(T.RecursoLock, novo)
            if atual is None:
                self.s.add(T.RecursoLock(recurso=novo, titular=titular, adquirido_em=agora_iso, expira_em=expira_iso))
            else:
                atual.expira_em = expira_iso
        self.s.flush()

    def liberar_locks(self, titular: str) -> int:
        return self.s.execute(delete(T.RecursoLock).where(T.RecursoLock.titular == titular)).rowcount

    def listar_locks(self) -> list[dict[str, Any]]:
        return [_dict(r) for r in self.s.scalars(select(T.RecursoLock).order_by(T.RecursoLock.recurso))]

    # ---- idempotencia ----
    def obter_idempotencia(self, escopo: str, chave: str) -> dict[str, Any] | None:
        row = self.s.get(T.Idempotencia, (escopo, chave))
        return None if row is None else _dict(row)

    def gravar_idempotencia(self, **campos: Any) -> None:
        self.s.add(T.Idempotencia(**campos))
        self.s.flush()


class RepositorioSqlite:
    def __init__(self, engine_escrita: Engine, engine_leitura: Engine) -> None:
        self._w = sessionmaker(engine_escrita, expire_on_commit=False)
        self._r = sessionmaker(engine_leitura, expire_on_commit=False)

    @contextmanager
    def escrita(self) -> Iterator[Tx]:
        with self._w() as s:
            try:
                yield Tx(s)
                s.commit()
            except BaseException:
                s.rollback()
                raise

    @contextmanager
    def leitura(self) -> Iterator[Tx]:
        with self._r() as s:
            try:
                yield Tx(s)
            finally:
                s.rollback()
