"""2.9: retomada com `session/load` (so se o agente anunciar `loadSession`), com queda segura para sessao nova."""

from __future__ import annotations

from pathlib import Path

import pytest

from forja.adapters.kiro_acp.cliente import AcpMetodoNaoSuportado, ClienteAcp
from forja.adapters.kiro_acp.provedor import ProvedorKiroAcp, montar_prompt
from tests.test_acp import _ctl, _tarefa, cmd

RETOMADA = {"entendimento": "ENTENDIMENTO-ANTIGO", "decisoes": [{"numero": 1, "pergunta": "PERGUNTA-ANTIGA"}],
            "respostas": ["adote cookie assinado"]}


def _prov(cenario: str, tmp_path: Path, **kw) -> ProvedorKiroAcp:
    return ProvedorKiroAcp(cmd(cenario), tmp_path / "ws", timeout_prompt=20, timeout_handshake=10, **kw)


def _retomar(prov: ProvedorKiroAcp, checkpoint: dict):
    ctl, eventos = _ctl()
    t = {**_tarefa(), "retomada": RETOMADA}
    return prov.executar(t, checkpoint, ctl), eventos


def test_cliente_anuncia_load_session_so_quando_o_agente_anuncia():
    c = ClienteAcp(cmd("ok"))
    c.iniciar()
    try:
        c.inicializar()
        assert c.suporta_carregar_sessao is False
        with pytest.raises(AcpMetodoNaoSuportado):
            c.carregar_sessao("x", "/tmp")
    finally:
        c.encerrar()


def test_retomada_reabre_a_sessao_e_envia_prompt_curto(tmp_path):
    r, eventos = _retomar(_prov("carregavel", tmp_path), {"session_id": "sess-antiga"})
    texto = r.artefatos[0].conteudo
    assert "sessao=sess-antiga carregada=True" in texto
    assert "adote cookie assinado" in texto  # a resposta nova do desenvolvedor vai
    assert "ENTENDIMENTO-ANTIGO" not in texto and "PERGUNTA-ANTIGA" not in texto  # o agente ja tem o historico
    assert "HISTORICO-REPRODUZIDO" not in texto  # o replay NAO vira resposta nova
    tipos = [t for t, _ in eventos]
    assert "kiro.sessao_carregada" in tipos and "kiro.ferramenta" not in tipos  # nem as ferramentas antigas viram eventos


def test_sessao_inexistente_cai_para_sessao_nova_com_prompt_completo(tmp_path):
    r, eventos = _retomar(_prov("carregavel_falha", tmp_path), {"session_id": "sess-antiga"})
    texto = r.artefatos[0].conteudo
    assert r.estado == "concluida" and "carregada=False" in texto and "sessao=sess-fake-1" in texto
    assert "ENTENDIMENTO-ANTIGO" in texto  # sem historico no agente: o prompt completo e necessario
    assert ("kiro.sessao_carregada", {"reaproveitada": False, "motivo": next(p for t, p in eventos if t == "kiro.sessao_carregada")["motivo"]}) in eventos


def test_sem_checkpoint_ou_sem_retomada_nao_tenta_carregar(tmp_path):
    r, eventos = _retomar(_prov("carregavel", tmp_path), {})
    assert "carregada=False" in r.artefatos[0].conteudo and "kiro.sessao_carregada" not in [t for t, _ in eventos]
    ctl, eventos2 = _ctl()
    r2 = _prov("carregavel", tmp_path).executar(_tarefa(), {"session_id": "sess-antiga"}, ctl)  # 1a rodada, nao retomada
    assert "carregada=False" in r2.artefatos[0].conteudo and "kiro.sessao_carregada" not in [t for t, _ in eventos2]


def test_agente_sem_load_session_usa_sessao_nova(tmp_path):
    ctl, eventos = _ctl()
    r = _prov("ok", tmp_path).executar({**_tarefa(), "retomada": RETOMADA}, {"session_id": "sess-antiga"}, ctl)
    assert r.estado == "concluida" and "kiro.sessao_carregada" not in [t for t, _ in eventos]


def test_reuso_pode_ser_desligado(tmp_path):
    r, eventos = _retomar(_prov("carregavel", tmp_path, reusar_sessao=False), {"session_id": "sess-antiga"})
    assert "carregada=False" in r.artefatos[0].conteudo and "kiro.sessao_carregada" not in [t for t, _ in eventos]


def test_checkpoint_guarda_o_id_da_sessao(tmp_path):
    guardados: list[dict] = []
    from forja.agentes.base import ControleExecucao

    ctl = ControleExecucao(guardados.append, lambda t, p: None)
    _prov("ok", tmp_path).executar(_tarefa(), {}, ctl)
    assert guardados and guardados[-1]["session_id"] == "sess-fake-1" and guardados[-1]["sessao"] == "criada"


def test_prompt_com_sessao_carregada_e_menor_que_o_completo():
    t = {**_tarefa(), "retomada": RETOMADA}
    assert len(montar_prompt(t, sessao_carregada=True)) < len(montar_prompt(t))


# ------------------------------------------------------------------ 4.7c: MCP anexado a sessao
MCP = [{"name": "forja", "command": "python", "args": ["-m", "forja.mcp"], "env": []}]


def test_mcp_so_e_anexado_com_opt_in(tmp_path):
    p = _prov("mcp", tmp_path, mcp_servers=MCP)
    ctl, eventos = _ctl()
    r = p.executar(_tarefa(), {}, ctl)
    assert "servidores=[]" in r.artefatos[0].conteudo and "kiro.mcp" not in [t for t, _ in eventos]  # desligado por padrao


def test_com_mcp_espera_o_servidor_conectar_antes_do_prompt(tmp_path):
    p = _prov("mcp", tmp_path, mcp_servers=MCP)
    p.usar_mcp = True
    ctl, eventos = _ctl()
    texto = p.executar(_tarefa(), {}, ctl).artefatos[0].conteudo
    assert "mcp_pronto_no_prompt=True" in texto and "servidores=['forja']" in texto and "dica=True" in texto
    ev = next(d for t, d in eventos if t == "kiro.mcp")
    # sinal real (_kiro/mcp/status), mesmo com o 'breakdown' DIMINUINDO (como apos trocar para o modo 'forja')
    assert ev["pronto"] is True and ev["sinal"] == "mcp_status" and ev["servidores"]["forja"]["ferramentas"] == 1
    assert ev["espera_ms"] < 5000


def test_mcp_que_falha_nao_espera_o_teto(tmp_path):
    import time

    p = _prov("mcp_falha", tmp_path, mcp_servers=MCP, espera_mcp_s=20)
    p.usar_mcp = True
    ctl, eventos = _ctl()
    t0 = time.monotonic()
    assert p.executar(_tarefa(), {}, ctl).estado == "concluida"
    ev = next(d for t, d in eventos if t == "kiro.mcp")
    assert ev["pronto"] is False and ev["sinal"] == "mcp_falhou" and time.monotonic() - t0 < 10


def test_sem_sinal_de_prontidao_segue_apos_o_teto(tmp_path):
    p = _prov("mcp_mudo", tmp_path, mcp_servers=MCP, espera_mcp_s=0.5)
    p.usar_mcp = True
    ctl, eventos = _ctl()
    import time

    t0 = time.monotonic()
    r = p.executar(_tarefa(), {}, ctl)
    ev = next(d for t, d in eventos if t == "kiro.mcp")
    assert r.estado == "concluida" and ev["pronto"] is False and ev["sinal"] == "sem_sinal" and time.monotonic() - t0 < 10
