"""Tabelas SQLAlchemy (persistencia interna). Datas em ISO-8601 UTC (texto)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Projeto(Base):
    __tablename__ = "projeto"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    nome: Mapped[str] = mapped_column(String(200), unique=True)
    descricao: Mapped[str] = mapped_column(Text, default="")
    estado: Mapped[str] = mapped_column(String(32), default="ativo")
    criado_em: Mapped[str] = mapped_column(String(40))


class Objetivo(Base):
    __tablename__ = "objetivo"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    projeto_id: Mapped[str] = mapped_column(ForeignKey("projeto.id"), index=True)
    titulo: Mapped[str] = mapped_column(String(200))
    descricao: Mapped[str] = mapped_column(Text, default="")
    prioridade: Mapped[int] = mapped_column(Integer, default=3)
    criterios_sucesso: Mapped[Any] = mapped_column(JSON)
    orcamento: Mapped[Any] = mapped_column(JSON)
    criado_em: Mapped[str] = mapped_column(String(40))


class Tarefa(Base):
    __tablename__ = "tarefa"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    objetivo_id: Mapped[str] = mapped_column(ForeignKey("objetivo.id"), index=True)
    projeto_id: Mapped[str] = mapped_column(ForeignKey("projeto.id"), index=True)
    titulo: Mapped[str] = mapped_column(String(200))
    descricao: Mapped[str] = mapped_column(Text, default="")
    criterios_aceite: Mapped[Any] = mapped_column(JSON)
    dependencias: Mapped[Any] = mapped_column(JSON)
    especialidade: Mapped[str] = mapped_column(String(200))
    modo: Mapped[str] = mapped_column(String(32))
    recursos: Mapped[Any] = mapped_column(JSON)
    orcamento: Mapped[Any] = mapped_column(JSON)
    politicas: Mapped[Any] = mapped_column(JSON)
    entrada: Mapped[Any] = mapped_column(JSON)
    contexto_refs: Mapped[Any] = mapped_column(JSON)
    estado: Mapped[str] = mapped_column(String(32), index=True)
    versao_estado: Mapped[int] = mapped_column(Integer, default=1)
    tentativas: Mapped[int] = mapped_column(Integer, default=0)
    motivo_estado: Mapped[str] = mapped_column(Text, default="")
    correlation_id: Mapped[str] = mapped_column(String(64))
    criado_em: Mapped[str] = mapped_column(String(40))
    atualizado_em: Mapped[str] = mapped_column(String(40))


class Execucao(Base):
    __tablename__ = "execucao"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tarefa_id: Mapped[str] = mapped_column(ForeignKey("tarefa.id"), index=True)
    estado: Mapped[str] = mapped_column(String(32), index=True)
    agente_id: Mapped[str] = mapped_column(String(200))
    tentativa: Mapped[int] = mapped_column(Integer, default=0)
    checkpoint: Mapped[Any] = mapped_column(JSON)
    resultado: Mapped[Any] = mapped_column(JSON, nullable=True)
    deadline: Mapped[str | None] = mapped_column(String(40), nullable=True)
    iniciado_em: Mapped[str | None] = mapped_column(String(40), nullable=True)
    finalizado_em: Mapped[str | None] = mapped_column(String(40), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(64))
    criado_em: Mapped[str] = mapped_column(String(40))


class Evento(Base):
    __tablename__ = "evento"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True)
    dedup_key: Mapped[str | None] = mapped_column(String(200), unique=True, nullable=True)
    tipo: Mapped[str] = mapped_column(String(100), index=True)
    ts: Mapped[str] = mapped_column(String(40))
    projeto_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    tarefa_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    execucao_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[Any] = mapped_column(JSON)


class Artefato(Base):
    __tablename__ = "artefato"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tarefa_id: Mapped[str | None] = mapped_column(ForeignKey("tarefa.id"), nullable=True, index=True)
    execucao_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    nome: Mapped[str] = mapped_column(String(200))
    tipo: Mapped[str] = mapped_column(String(32))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    caminho_relativo: Mapped[str] = mapped_column(String(300))
    tamanho: Mapped[int] = mapped_column(Integer)
    origem: Mapped[str] = mapped_column(String(100))
    criado_em: Mapped[str] = mapped_column(String(40))


class Evidencia(Base):
    __tablename__ = "evidencia"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tarefa_id: Mapped[str] = mapped_column(ForeignKey("tarefa.id"), index=True)
    execucao_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tipo: Mapped[str] = mapped_column(String(200))
    resumo: Mapped[str] = mapped_column(Text)
    artefato_id: Mapped[str | None] = mapped_column(ForeignKey("artefato.id"), nullable=True)
    simulada: Mapped[bool] = mapped_column(Boolean, default=False)
    criado_em: Mapped[str] = mapped_column(String(40))


class Aprovacao(Base):
    __tablename__ = "aprovacao"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tarefa_id: Mapped[str] = mapped_column(ForeignKey("tarefa.id"), index=True)
    execucao_id: Mapped[str] = mapped_column(String(64))
    acao: Mapped[str] = mapped_column(String(200))
    justificativa: Mapped[str] = mapped_column(Text, default="")
    estado: Mapped[str] = mapped_column(String(32), index=True)
    decidido_por: Mapped[str | None] = mapped_column(String(100), nullable=True)
    decidido_em: Mapped[str | None] = mapped_column(String(40), nullable=True)
    criado_em: Mapped[str] = mapped_column(String(40))


class RecursoLock(Base):
    __tablename__ = "recurso_lock"
    recurso: Mapped[str] = mapped_column(String(300), primary_key=True)
    titular: Mapped[str] = mapped_column(String(64), index=True)
    adquirido_em: Mapped[str] = mapped_column(String(40))
    expira_em: Mapped[str] = mapped_column(String(40))


class Idempotencia(Base):
    __tablename__ = "idempotencia"
    escopo: Mapped[str] = mapped_column(String(200), primary_key=True)
    chave: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int] = mapped_column(Integer)
    resposta: Mapped[Any] = mapped_column(JSON)
    criado_em: Mapped[str] = mapped_column(String(40))


Index("ix_evento_seq_projeto", Evento.projeto_id, Evento.seq)
