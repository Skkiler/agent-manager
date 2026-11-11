"""Modelos da conta (kiro-cli chat --list-models) e esforco por parte, aplicados ao comando do Kiro."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from forja.adapters.agentes_mock.mock import AgenteMock
from forja.adapters.kiro_acp.modelos import CatalogoModelos, parse_modelos
from forja.adapters.kiro_acp.provedor import ProvedorKiroAcp
from forja.config import Configuracoes
from forja.dominio.configuracao import ConfiguracaoSistema
from forja.servidor.app import criar_app

TOKEN = "token-de-teste-com-tamanho-suficiente"
# Formato real observado no kiro-cli 3.1.0 (ids/descricoes de exemplo da propria saida do CLI)
SAIDA_CLI = """Available models (* = default):
* auto                 1.00x credits      Models chosen by task for optimal usage and consistent quality
  claude-haiku-5.5     0.06x credits      Claude Haiku 5.5 model with 1M context window
  gpt-5.6-sol          4.40x credits      OpenAI GPT 5.6 Sol with 1M context window
linha-estranha sem custo
"""


def test_parse_modelos_le_id_custo_descricao_e_padrao_e_ignora_ruido():
    m = parse_modelos(SAIDA_CLI)
    assert [x["id"] for x in m] == ["auto", "claude-haiku-5.5", "gpt-5.6-sol"]
    assert m[0]["padrao"] and not m[1]["padrao"] and m[1]["custo"] == 0.06 and m[2]["custo"] == 4.4
    assert m[1]["descricao"].startswith("Claude Haiku")
    assert parse_modelos("") == [] and parse_modelos("erro: nao autenticado") == []


def test_catalogo_cacheia_e_expira(monkeypatch):
    chamadas = []
    relogio = [0.0]
    c = CatalogoModelos("kiro-cli", executar=lambda cli: chamadas.append(cli) or SAIDA_CLI, agora=lambda: relogio[0])
    assert len(c.listar()["modelos"]) == 3 and len(c.listar()["modelos"]) == 3
    assert chamadas == ["kiro-cli"]  # segunda chamada veio do cache
    relogio[0] = 601
    c.listar()
    assert len(chamadas) == 2  # TTL expirou


def test_catalogo_degrada_com_aviso_sem_cli_com_falha_e_sem_modelos():
    assert CatalogoModelos(None).listar() == {"modelos": [], "aviso": "Kiro CLI nao encontrado: informe o modelo manualmente."}

    def quebra(_: str) -> str:
        raise subprocess.TimeoutExpired("kiro-cli", 20)

    assert "Nao foi possivel" in CatalogoModelos("kiro-cli", executar=quebra).listar()["aviso"]
    assert "login" in CatalogoModelos("kiro-cli", executar=lambda _: "Not logged in").listar()["aviso"]


def test_comando_do_catalogo_e_fixo_e_sem_shell(monkeypatch):
    visto = {}

    def falso(cmd, **kw):
        visto.update(cmd=cmd, kw=kw)
        return subprocess.CompletedProcess(cmd, 0, SAIDA_CLI, "")

    monkeypatch.setattr(subprocess, "run", falso)
    CatalogoModelos("C:/x/kiro-cli.exe").listar()
    assert visto["cmd"] == ["C:/x/kiro-cli.exe", "chat", "--list-models"]
    assert not visto["kw"].get("shell") and visto["kw"]["timeout"] <= 30


# ---------------------------------------------------------------- esforco


def test_esforco_so_aceita_valores_do_cli_e_nao_em_partes_deterministicas():
    ok = ConfiguracaoSistema.model_validate({"partes": {"revisao": {"modelo": "claude-opus-5", "esforco": "high"}}})
    assert ok.partes["revisao"].esforco == "high"
    for ruim in ({"revisao": {"esforco": "enorme"}}, {"contexto": {"esforco": "low"}}, {"revisao": {"esforco": "--trust-all-tools"}}):
        with pytest.raises(ValidationError):
            ConfiguracaoSistema.model_validate({"partes": ruim})


# ---------------------------------------------------------------- API


@pytest.fixture
def cli(tmp_path: Path, _db_migrado: Path) -> Iterator[TestClient]:
    (tmp_path / "data").mkdir()
    shutil.copyfile(_db_migrado, tmp_path / "data" / "forja.sqlite3")
    cfg = Configuracoes(_env_file=None, app_data_dir=tmp_path / "data", app_log_dir=tmp_path / "logs",  # type: ignore[call-arg]
                        app_api_token=TOKEN, app_allowed_hosts="testserver")
    with TestClient(criar_app(cfg, AgenteMock()), headers={"Authorization": f"Bearer {TOKEN}"}) as c:
        c.app.state.modelos = CatalogoModelos("kiro-cli", executar=lambda _: SAIDA_CLI)
        yield c


def test_api_lista_modelos_e_exige_autenticacao(cli: TestClient):
    r = cli.get("/api/v1/configuracao/modelos").json()
    assert [m["id"] for m in r["modelos"]][:2] == ["auto", "claude-haiku-5.5"] and r["aviso"] is None
    assert TestClient(cli.app, headers={"Host": "testserver"}).get("/api/v1/configuracao/modelos").status_code in (401, 403)


def test_api_salva_e_devolve_esforco(cli: TestClient):
    corpo = {"expected_version": 0, "configuracao": {"partes": {"execucao": {"modelo": "claude-haiku-5.5", "esforco": "low"}}}}
    assert cli.put("/api/v1/configuracao", json=corpo).status_code == 200
    p = next(x for x in cli.get("/api/v1/configuracao").json()["partes"] if x["id"] == "execucao")
    assert p["esforco"] == "low" and p["modelo"] == "claude-haiku-5.5"
    ruim = {"expected_version": 1, "configuracao": {"partes": {"contexto": {"esforco": "low"}}}}
    assert cli.put("/api/v1/configuracao", json=ruim).status_code == 422


# ---------------------------------------------------------------- aplicacao por sessao (ACP v3)

FAKE = str(Path(__file__).parent / "fakes" / "fake_acp_agent.py")


def _prov(tmp_path: Path, modelo: str = "", esforco: str = "") -> ProvedorKiroAcp:
    import sys

    return ProvedorKiroAcp([sys.executable, FAKE, "modelos"], tmp_path / "ws", timeout_prompt=20, timeout_handshake=10,
                           modelo_de=lambda parte: modelo, esforco_de=lambda parte: esforco)


def _ctl():
    from forja.agentes.base import ControleExecucao

    eventos: list = []
    return ControleExecucao(lambda cp: None, lambda t, p: eventos.append((t, p))), eventos


def _tarefa(revisao: bool = False) -> dict:
    return {"id": "T1", "titulo": "t", "descricao": "d", "criterios_aceite": ["x"], "modo": "analise",
            "entrada": {"revisao": True} if revisao else {}, "especialidade": "g"}


def test_modelo_e_esforco_chegam_a_sessao_do_agente(tmp_path):
    ctl, eventos = _ctl()
    r = _prov(tmp_path, "claude-haiku-5.5", "low").executar(_tarefa(), {}, ctl)
    assert r.estado == "concluida" and "model=claude-haiku-5.5 effort=low" in r.artefatos[0].conteudo
    ev = dict(eventos)["kiro.configuracao"]
    assert ev["aplicados"] == {"modelo": "claude-haiku-5.5", "esforco": "low"} and ev["avisos"] == []


def test_sem_configuracao_nada_e_alterado(tmp_path):
    ctl, eventos = _ctl()
    r = _prov(tmp_path).executar(_tarefa(), {}, ctl)
    assert "model=auto effort=-" in r.artefatos[0].conteudo and "kiro.configuracao" not in dict(eventos)


def test_esforco_em_modelo_que_nao_o_oferece_e_ignorado_com_aviso(tmp_path):
    ctl, eventos = _ctl()
    r = _prov(tmp_path, "deepseek-3.2", "high").executar(_tarefa(), {}, ctl)
    assert r.estado == "concluida" and "model=deepseek-3.2 effort=-" in r.artefatos[0].conteudo
    assert dict(eventos)["kiro.configuracao"]["avisos"]


def test_modelo_inexistente_bloqueia_a_execucao_em_vez_de_rodar_em_outro(tmp_path):
    """O agente real aceita qualquer nome em silencio: sem validar, a tarefa rodaria no modelo errado."""
    ctl, _ = _ctl()
    r = _prov(tmp_path, "modelo-que-nao-existe").executar(_tarefa(), {}, ctl)
    assert r.estado == "bloqueada" and not r.artefatos
    assert any("modelo_indisponivel" in p for p in r.pendencias)


def test_modelo_ausente_usa_a_reserva_explicita_e_registra(tmp_path):
    ctl, eventos = _ctl()
    p = _prov(tmp_path, "modelo-que-nao-existe")
    p.alternativas_de = lambda parte: ["outro-inexistente", "claude-haiku-5.5"]
    r = p.executar(_tarefa(), {}, ctl)
    assert r.estado == "concluida" and "model=claude-haiku-5.5" in r.artefatos[0].conteudo
    ev = dict(eventos)["kiro.configuracao"]
    assert ev["aplicados"]["modelo_alternativo"] == "claude-haiku-5.5" and "indisponivel" in ev["avisos"][0]


def test_reserva_tambem_ausente_continua_bloqueando(tmp_path):
    ctl, _ = _ctl()
    p = _prov(tmp_path, "modelo-que-nao-existe")
    p.alternativas_de = lambda parte: ["outro-inexistente"]
    assert p.executar(_tarefa(), {}, ctl).estado == "bloqueada"


def test_parte_deterministica_recusa_reserva():
    from forja.dominio.configuracao import ConfiguracaoSistema

    with pytest.raises(ValueError):
        ConfiguracaoSistema.model_validate({"partes": {"contexto": {"alternativas": ["auto"]}}})


def test_tarefa_de_revisao_usa_a_configuracao_da_parte_revisao(tmp_path):
    ctl, _ = _ctl()
    import sys

    prov = ProvedorKiroAcp([sys.executable, FAKE, "modelos"], tmp_path / "ws", timeout_handshake=10,
                           modelo_de=lambda parte: {"execucao": "auto", "revisao": "claude-opus-5.5"}[parte],
                           esforco_de=lambda parte: "")
    r = prov.executar(_tarefa(revisao=True), {}, ctl)
    assert "model=claude-opus-5.5" in r.artefatos[0].conteudo
    assert "model=auto" in prov.executar(_tarefa(), {}, _ctl()[0]).artefatos[0].conteudo


def test_falha_ao_ler_a_configuracao_nao_impede_a_execucao(tmp_path):
    import sys

    def quebra(_: str) -> str:
        raise RuntimeError("banco indisponivel")

    ctl, _ = _ctl()
    prov = ProvedorKiroAcp([sys.executable, FAKE, "modelos"], tmp_path / "ws", timeout_handshake=10, modelo_de=quebra)
    assert prov.executar(_tarefa(), {}, ctl).estado == "concluida"


def test_aplicar_configuracao_ordem_modelo_antes_do_esforco():
    """As opcoes de esforco so existem depois do modelo ser escolhido (observado no agente real)."""
    from forja.adapters.kiro_acp.sessao_config import aplicar_configuracao

    class Falso:
        def __init__(self) -> None:
            self.opcoes_sessao = [{"id": "model", "options": [{"value": "m1"}]}]
            self.chamadas: list[tuple[str, str]] = []

        def definir_opcao(self, sid, cid, valor, timeout=20.0):
            self.chamadas.append((cid, valor))
            if cid == "model":
                self.opcoes_sessao = [*self.opcoes_sessao, {"id": "effortLevel", "options": [{"value": "low"}]}]
            return self.opcoes_sessao

    c = Falso()
    r = aplicar_configuracao(c, "S", "m1", "low")
    assert c.chamadas == [("model", "m1"), ("effortLevel", "low")] and r["aplicados"] == {"modelo": "m1", "esforco": "low"}
