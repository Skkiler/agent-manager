"""Fixtures de teste. Usa banco temporario e relogio controlavel; nunca toca em credenciais reais."""

from __future__ import annotations

import shutil
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


@pytest.fixture(scope="session")
def _db_migrado(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Banco ja migrado ate 'head', criado UMA vez por sessao (as migracoes custam ~1 s por teste)."""
    p = tmp_path_factory.mktemp("template") / "forja.sqlite3"
    migrar(p)
    return p


def _copiar_banco(origem: Path, destino: Path) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(origem, destino)
    return destino


@pytest.fixture
def db_path(tmp_path: Path, _db_migrado: Path) -> Path:
    return _copiar_banco(_db_migrado, tmp_path / "data" / "forja.sqlite3")


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
def config(tmp_path: Path, _db_migrado: Path) -> Configuracoes:
    _copiar_banco(_db_migrado, tmp_path / "data" / "forja.sqlite3")  # criar_app so confirma que ja esta em 'head'
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


@pytest.fixture
def validar_memoria(repo):
    """Leva uma memoria de 'candidato' a 'validado' com evidencia REAL sintetica (para testes de contexto/conversa)."""
    from forja.adapters.sqlite import tabelas as T
    from forja.memoria.contratos import TransicaoMemoriaIn, ValidarIn

    def _validar(memoria_servico, principal, m):
        with repo.escrita() as t:
            n = t.s.query(T.Projeto).count() + 1
            t.inserir(T.Projeto, id=f"VP{n}", nome=f"vp{n}", descricao="", estado="ativo", criado_em="2026")
            t.inserir(T.Objetivo, id=f"VO{n}", projeto_id=f"VP{n}", titulo="o", descricao="", prioridade=3,
                      criterios_sucesso=[], orcamento={}, criado_em="2026")
            t.inserir(T.Tarefa, id=f"VT{n}", objetivo_id=f"VO{n}", projeto_id=f"VP{n}", titulo="t", descricao="",
                      criterios_aceite=["x"], dependencias=[], especialidade="g", modo="analise", recursos={}, orcamento={},
                      politicas={}, entrada={}, contexto_refs=[], estado="concluida", versao_estado=1, tentativas=1,
                      motivo_estado="", correlation_id="c", criado_em="2026", atualizado_em="2026")
            t.inserir(T.Evidencia, id=f"VEV{n}", tarefa_id=f"VT{n}", execucao_id=None, tipo="teste", resumo="ok",
                      artefato_id=None, simulada=False, criado_em="2026")
        memoria_servico.vincular_evidencia(principal, m["id"], f"VEV{n}")
        v = memoria_servico.transicionar(principal, m["id"], TransicaoMemoriaIn(para="verificado",
                                                                               expected_version=m["versao"]))
        return memoria_servico.validar(principal, m["id"], ValidarIn(expected_version=v["versao"], validado_por="teste"))

    return _validar
