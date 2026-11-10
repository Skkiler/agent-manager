"""Configuracao por parte do sistema: modelo de IA de cada parte e nivel de detalhe, com efeito real no comando do Kiro."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from forja.adapters.agentes_mock.mock import AgenteMock
from forja.config import Configuracoes
from forja.dominio.configuracao import PARTES, ConfiguracaoSistema, SalvarConfiguracaoIn
from forja.dominio.erros import ConflitoVersao
from forja.orquestracao.configuracao_servico import ConfiguracaoServico
from forja.servidor.app import criar_app

TOKEN = "token-de-teste-com-tamanho-suficiente"


def salvar(c: ConfiguracaoServico, versao: int, **partes: str) -> dict:
    cfg = ConfiguracaoSistema(partes={k: {"modelo": v} for k, v in partes.items()})
    return c.salvar(SalvarConfiguracaoIn(expected_version=versao, configuracao=cfg))


# ---------------------------------------------------------------- dominio


@pytest.mark.parametrize(
    "ruim",
    [
        {"partes": {"inexistente": {"modelo": "x"}}},
        {"partes": {"contexto": {"modelo": "claude-sonnet"}}},  # parte deterministica nao usa modelo
        {"partes": {"execucao": {"modelo": "com espaco"}}},
        {"partes": {"execucao": {"modelo": "--trust-all-tools"}}},  # nunca vira flag do CLI
        {"partes": {"execucao": {"modelo": "a" * 81}}},
        {"nivel_detalhe": "avancado"},  # agora vive nas preferencias, nao mais aqui
        {"extra": 1},
    ],
)
def test_configuracao_invalida_e_recusada(ruim):
    with pytest.raises(ValidationError):
        ConfiguracaoSistema.model_validate(ruim)


def test_partes_que_usam_modelo_sao_so_as_que_realmente_chamam_um():
    assert {p.id for p in PARTES if p.usa_modelo} == {"execucao", "revisao"}


# ---------------------------------------------------------------- servico


def test_padrao_nunca_salvo_tem_versao_zero_e_herda_o_modelo_global(repo, relogio):
    c = ConfiguracaoServico(repo, relogio, modelo_padrao="modelo-global")
    r = c.obter()
    assert r["versao"] == 0 and r["configuracao"] == {"partes": {}}
    por = {p["id"]: p for p in r["partes"]}
    assert por["execucao"]["modelo_efetivo"] == "modelo-global" and por["contexto"]["modelo_efetivo"] is None
    assert c.modelo_para("execucao") == "modelo-global"


def test_modelo_por_parte_tem_prioridade_sobre_o_global_e_e_independente(repo, relogio):
    c = ConfiguracaoServico(repo, relogio, modelo_padrao="global")
    r = salvar(c, 0, execucao="modelo-rapido")
    assert r["versao"] == 1 and set(r["configuracao"]["partes"]) == {"execucao"}
    assert c.modelo_para("execucao") == "modelo-rapido"
    assert c.modelo_para("revisao") == "global"  # outra parte nao e afetada
    salvar(c, 1, execucao="modelo-rapido", revisao="modelo-profundo")
    assert c.modelo_para("revisao") == "modelo-profundo"
    salvar(c, 2)  # limpar volta ao global
    assert c.modelo_para("execucao") == "global"


def test_salvar_exige_a_versao_atual(repo, relogio):
    c = ConfiguracaoServico(repo, relogio)
    salvar(c, 0, execucao="a")
    with pytest.raises(ConflitoVersao):
        salvar(c, 0, execucao="b")  # outra aba salvou antes
    assert c.modelo_para("execucao") == "a"


def test_valor_corrompido_no_banco_nao_derruba_a_execucao(repo, relogio):
    from forja.adapters.sqlite import tabelas as T

    with repo.escrita() as t:
        t.inserir(T.Configuracao, id="sistema", valor={"partes": {"execucao": {"modelo": "com espaco"}}}, versao=1,
                  atualizado_em="2026")
    assert ConfiguracaoServico(repo, relogio, modelo_padrao="seguro").modelo_para("execucao") == "seguro"


# ---------------------------------------------------------------- API


@pytest.fixture
def cli(tmp_path: Path, _db_migrado: Path) -> Iterator[TestClient]:
    (tmp_path / "data").mkdir()
    shutil.copyfile(_db_migrado, tmp_path / "data" / "forja.sqlite3")
    cfg = Configuracoes(_env_file=None, app_data_dir=tmp_path / "data", app_log_dir=tmp_path / "logs",  # type: ignore[call-arg]
                        app_api_token=TOKEN, app_allowed_hosts="testserver")
    with TestClient(criar_app(cfg, AgenteMock()), headers={"Authorization": f"Bearer {TOKEN}"}) as c:
        yield c


def test_api_le_salva_e_detecta_conflito(cli):
    r = cli.get("/api/v1/configuracao").json()
    assert r["versao"] == 0 and {p["id"] for p in r["partes"]} == {p.id for p in PARTES}
    corpo = {"expected_version": 0, "configuracao": {                                                       "partes": {"execucao": {"modelo": "m1"}}}}
    ok = cli.put("/api/v1/configuracao", json=corpo)
    assert ok.status_code == 200 and ok.json()["versao"] == 1
    assert cli.put("/api/v1/configuracao", json=corpo).status_code == 409
    assert cli.get("/api/v1/configuracao").json()["configuracao"]["partes"]["execucao"]["modelo"] == "m1"


@pytest.mark.parametrize("partes", [{"contexto": {"modelo": "x"}}, {"nada": {}}, {"execucao": {"modelo": "a b"}}])
def test_api_recusa_configuracao_invalida(cli, partes):
    r = cli.put("/api/v1/configuracao", json={"expected_version": 0, "configuracao": {"partes": partes}})
    assert r.status_code == 422


def test_api_exige_autenticacao(cli):
    sem = TestClient(cli.app, headers={"Host": "testserver"})
    assert sem.get("/api/v1/configuracao").status_code in (401, 403)
    assert sem.put("/api/v1/configuracao", json={}).status_code in (401, 403)
