"""Relogio UTC injetavel (testes controlam o tempo)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Relogio(Protocol):
    def agora(self) -> datetime: ...


class RelogioSistema:
    def agora(self) -> datetime:
        return datetime.now(UTC)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="milliseconds")


def somar(dt: datetime, segundos: float) -> datetime:
    return dt + timedelta(seconds=segundos)
