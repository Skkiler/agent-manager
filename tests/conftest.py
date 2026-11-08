"""Fixtures de teste. Usa banco temporario e relogio controlavel; nunca toca em credenciais reais."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from forja.adapters.agentes_mock.mock import AgenteMock
from forja.adapters.sqlite.banco import criar_engines, migrar
from forja.adapters.sqlite.repositorio import RepositorioSqlite
from forja.config import Configuracoes
from forja.orquestracao.servico import Servico


class RelogioFake:
    def __init__(self) -> None:
        self._t = datetime(2026, 1, 1, tzinfo=UTC)

    def agora(self) -> datetime:
        return self._t

    def avancar(self, segundos: float) -> None:
        self._t += timedelta(seconds=segundos)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    p = tmp_path / "data" / "forja.sqlite3"
    migrar(p)
    return p


@pytest.fixture
def repo(db_path: Path) -> Iterator[RepositorioSqlite]:
    w, r = criar_engines(db_path)
    rp = RepositorioSqlite(w, r)
    yield rp
    rp.fechar()


@pytest.fixture
def relogio() -> RelogioFake:
    return RelogioFake()


@pytest.fixture
def servico(repo: RepositorioSqlite, tmp_path: Path, relogio: RelogioFake) -> Iterator[Servico]:
    s = Servico(repo, AgenteMock(), tmp_path / "data" / "artefatos", max_workers=4,
                lock_lease_seconds=900, relogio=relogio)
    yield s
    s.encerrar(timeout=5)


@pytest.fixture
def config(tmp_path: Path) -> Configuracoes:
    return Configuracoes(
        _env_file=None,  # type: ignore[call-arg]
        app_data_dir=tmp_path / "data",
        app_log_dir=tmp_path / "logs",
        app_api_token="token-de-teste-com-tamanho-suficiente",
        app_require_auth=True,
        app_allowed_hosts="testserver",
    )


@pytest.fixture
def client(config: Configuracoes) -> Iterator[TestClient]:
    from forja.servidor.app import criar_app

    app = criar_app(config, AgenteMock())
    with TestClient(app, headers={"Authorization": "Bearer token-de-teste-com-tamanho-suficiente"}) as c:
        yield c
