"""Testes do adaptador Kiro ACP contra um agente ACP falso (subprocesso real) + handshake real opcional."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

from forja.adapters.kiro_acp.cliente import (
    AcpAutenticacaoNecessaria,
    AcpCliAusente,
    AcpDesconectado,
    AcpProtocoloNaoSuportado,
    AcpTimeout,
    ClienteAcp,
)
from forja.adapters.kiro_acp.provedor import (
    ProvedorKiroAcp,
    montar_comando,
    resolver_cli,
)
from forja.adapters.sqlite import tabelas as T
from forja.agentes.base import ControleExecucao
from forja.dominio.contratos import ObjetivoIn, ProjetoIn, TarefaIn, TransicaoIn
from forja.dominio.estados import EstadoTarefa
from forja.orquestracao.servico import Servico

FAKE = str(Path(__file__).parent / "fakes" / "fake_acp_agent.py")
ET = EstadoTarefa


def cmd(cenario: str) -> list[str]:
    return [sys.executable, FAKE, cenario]


def _ctl() -> tuple[ControleExecucao, list]:
    eventos: list = []
    return ControleExecucao(lambda cp: None, lambda t, p: eventos.append((t, p))), eventos


def _tarefa(modo: str = "analise") -> dict:
    return {"id": "T-x", "titulo": "Analisar modulo X", "descricao": "d", "criterios_aceite": ["a", "b"], "modo": modo}


def _prov(cenario: str, tmp_path: Path, timeout: float = 20.0) -> ProvedorKiroAcp:
    return ProvedorKiroAcp(cmd(cenario), tmp_path / "ws", timeout_prompt=timeout, timeout_handshake=10)


# ------------------------------------------------------------------ cliente
def test_handshake_e_sessao():
    c = ClienteAcp(cmd("ok"))
    c.iniciar()
    try:
        c.inicializar()
        assert c.agent_info["name"] == "Fake ACP Agent"
        assert c.auth_methods[0]["id"] == "kiro-login"
        assert c.nova_sessao("/tmp") == "sess-fake-1"
    finally:
        c.encerrar()


def test_protocolo_incompativel_rejeitado():
    c = ClienteAcp(cmd("protocolo"))
    c.iniciar()
    try:
        with pytest.raises(AcpProtocoloNaoSuportado):
            c.inicializar()
    finally:
        c.encerrar()


def test_autenticacao_necessaria_tipada():
    c = ClienteAcp(cmd("auth"))
    c.iniciar()
    try:
        c.inicializar()
        with pytest.raises(AcpAutenticacaoNecessaria):
            c.nova_sessao("/tmp")
    finally:
        c.encerrar()


def test_cli_ausente():
    c = ClienteAcp(["executavel-que-nao-existe-forja"])
    with pytest.raises(AcpCliAusente):
        c.iniciar()


def test_timeout_no_handshake():
    c = ClienteAcp(cmd("init_travado"))
    c.iniciar()
    try:
        with pytest.raises(AcpTimeout):
            c.inicializar(timeout=0.5)
    finally:
        c.encerrar()


def test_ruido_em_stdout_nao_derruba_cliente():
    c = ClienteAcp(cmd("ruido"))
    c.iniciar()
    try:
        c.inicializar()
        assert c.nova_sessao("/tmp")
        assert "aviso de debug" in c.stderr_recente()  # stderr separado do protocolo
    finally:
        c.encerrar()


def test_permissao_negada_e_metodo_nao_anunciado_responde_erro():
    textos: list[str] = []

    def upd(_sid, u):
        if u.get("sessionUpdate") == "agent_message_chunk":
            textos.append(u["content"]["text"])

    c = ClienteAcp(cmd("permissao"), on_update=upd)
    c.iniciar()
    try:
        c.inicializar()
        sid = c.nova_sessao("/tmp")
        res = c.chamar("session/prompt", {"sessionId": sid, "prompt": [{"type": "text", "text": "oi"}]}, timeout=10)
        assert res["stopReason"] == "end_turn"
    finally:
        c.encerrar()
    corpo = "".join(textos)
    assert '"optionId": "deny"' in corpo  # escolheu a opcao de rejeicao, nunca 'allow'
    assert "fs_erro=-32601" in corpo  # fs/* nao anunciado => erro, nao pendente
    assert c.permissoes_vistas and c.permissoes_vistas[0]["titulo"] == "Escrever arquivo"


def test_desconexao_falha_pendentes():
    c = ClienteAcp(cmd("crash"))
    c.iniciar()
    try:
        c.inicializar()
        sid = c.nova_sessao("/tmp")
        with pytest.raises(AcpDesconectado):
            c.chamar("session/prompt", {"sessionId": sid, "prompt": []}, timeout=10)
    finally:
        c.encerrar()


def test_comando_nunca_confia_em_tudo():
    comando = montar_comando("kiro-cli", agente="a", modelo="m")
    assert not any("trust" in parte for parte in comando)
    assert comando[:3] == ["kiro-cli", "acp", "--agent-engine=v3"]


# ------------------------------------------------------------------ provedor
def test_provedor_sucesso_com_redacao(tmp_path):
    ctl, eventos = _ctl()
    r = _prov("ok", tmp_path).executar(_tarefa(), {}, ctl)
    assert r.estado == "concluida" and r.mock is False
    assert r.evidencias[0].tipo == "kiro_resposta" and r.evidencias[0].simulada is False
    conteudo = r.artefatos[0].conteudo
    assert "Resumo" in conteudo and "SEGREDO123456" not in conteudo  # segredo redigido
    # o ACP nao expoe contagem do provedor: so ha ESTIMATIVA (~4 car./token), sempre rotulada 'estimado', nunca 'provedor'
    assert r.consumo.fonte == "estimado" and r.consumo.tokens_input > 0 and r.consumo.tokens_output > 0
    assert r.consumo.chamadas_modelo == 1
    tipos = [t for t, _ in eventos]
    assert "kiro.conectado" in tipos and "kiro.ferramenta" in tipos


def test_provedor_auth_vira_bloqueio_com_pendencia(tmp_path):
    ctl, _ = _ctl()
    r = _prov("auth", tmp_path).executar(_tarefa(), {}, ctl)
    assert r.estado == "bloqueada"
    assert any("reautenticacao_necessaria" in p for p in r.pendencias)


def test_provedor_sem_cli_bloqueia(tmp_path):
    ctl, _ = _ctl()
    r = ProvedorKiroAcp(None, tmp_path / "ws").executar(_tarefa(), {}, ctl)
    assert r.estado == "bloqueada" and "kiro_cli_ausente" in r.pendencias[0]


def test_provedor_cli_inexistente_bloqueia(tmp_path):
    ctl, _ = _ctl()
    r = ProvedorKiroAcp(["nao-existe-forja"], tmp_path / "ws").executar(_tarefa(), {}, ctl)
    assert r.estado == "bloqueada"


def test_provedor_recusa_modo_de_escrita(tmp_path):
    ctl, _ = _ctl()
    r = _prov("ok", tmp_path).executar(_tarefa("alteracao_codigo"), {}, ctl)
    assert r.estado == "falhou" and "nao habilitado" in r.resumo


def test_provedor_resposta_vazia_e_recusa_falham(tmp_path):
    ctl, _ = _ctl()
    assert _prov("vazio", tmp_path).executar(_tarefa(), {}, ctl).estado == "falhou"
    assert _prov("recusa", tmp_path).executar(_tarefa(), {}, ctl).estado == "falhou"


def test_provedor_crash_do_agente_falha_sem_travar(tmp_path):
    ctl, _ = _ctl()
    r = _prov("crash", tmp_path).executar(_tarefa(), {}, ctl)
    assert r.estado == "falhou" and "Conexao ACP perdida" in r.resumo


def test_provedor_resposta_longa_e_limitada(tmp_path):
    ctl, _ = _ctl()
    r = _prov("longo", tmp_path).executar(_tarefa(), {}, ctl)
    assert r.estado == "concluida"
    assert len(r.artefatos[0].conteudo) <= 210_000


def test_provedor_cancelamento_cooperativo(tmp_path):
    ctl, _ = _ctl()
    prov = _prov("lento", tmp_path)
    threading.Timer(0.8, ctl.cancelar_ev.set).start()
    t0 = time.monotonic()
    r = prov.executar(_tarefa(), {}, ctl)
    assert r.estado == "cancelada" and time.monotonic() - t0 < 15


def test_provedor_timeout_do_prompt(tmp_path):
    ctl, _ = _ctl()
    r = _prov("lento", tmp_path, timeout=1.0).executar(_tarefa(), {}, ctl)
    assert r.estado == "falhou" and "Timeout" in r.resumo


# ------------------------------------------------------------------ integracao com o orquestrador
def test_orquestrador_com_provedor_acp(repo, tmp_path):
    s = Servico(repo, _prov("ok", tmp_path), tmp_path / "art", max_workers=2)
    try:
        p, _ = s.criar_projeto(ProjetoIn(nome="acp-int"))
        o, _ = s.criar_objetivo(ObjetivoIn(projeto_id=p["id"], titulo="o"))
        t, _ = s.criar_tarefa(TarefaIn(objetivo_id=o["id"], titulo="analisar", criterios_aceite=["ok"]))
        r = s.transicionar(t["id"], TransicaoIn(para=ET.CLASSIFICADA, expected_version=1))[0]
        s.transicionar(t["id"], TransicaoIn(para=ET.PREPARADA, expected_version=r["versao_estado"]))
        ex = s.criar_execucao(t["id"])
        s.iniciar_execucao(ex["id"])
        s.aguardar(ex["id"], 30)
        assert s.obter(T.Tarefa, t["id"])["estado"] == ET.CONCLUIDA.value
        ev = s.listar(T.Evidencia, tarefa_id=t["id"])[0]
        assert ev["tipo"] == "kiro_resposta" and ev["simulada"] is False
        tipos = {e["tipo"] for e in s.eventos_apos(0, 1000)}
        assert {"kiro.conectado", "kiro.ferramenta", "agente.iniciado"} <= tipos
    finally:
        s.encerrar(5)


def test_orquestrador_auth_deixa_tarefa_bloqueada_e_retomavel(repo, tmp_path):
    s = Servico(repo, _prov("auth", tmp_path), tmp_path / "art", max_workers=2)
    try:
        p, _ = s.criar_projeto(ProjetoIn(nome="acp-auth"))
        o, _ = s.criar_objetivo(ObjetivoIn(projeto_id=p["id"], titulo="o"))
        t, _ = s.criar_tarefa(TarefaIn(objetivo_id=o["id"], titulo="analisar", criterios_aceite=["ok"]))
        r = s.transicionar(t["id"], TransicaoIn(para=ET.CLASSIFICADA, expected_version=1))[0]
        s.transicionar(t["id"], TransicaoIn(para=ET.PREPARADA, expected_version=r["versao_estado"]))
        ex = s.criar_execucao(t["id"])
        s.iniciar_execucao(ex["id"])
        s.aguardar(ex["id"], 30)
        tarefa = s.obter(T.Tarefa, t["id"])
        assert tarefa["estado"] == ET.BLOQUEADA.value  # recuperavel apos 'kiro-cli login'
        assert "bloqueada" in tarefa["motivo_estado"]
    finally:
        s.encerrar(5)


# ------------------------------------------------------------------ CLI real (somente handshake; sem login/creditos)
@pytest.mark.skipif(resolver_cli() is None, reason="kiro-cli nao instalado nesta maquina")
def test_handshake_real_com_kiro_cli():
    c = ClienteAcp(montar_comando(resolver_cli() or "kiro-cli"))
    c.iniciar()
    try:
        res = c.inicializar(timeout=30)
        # agentInfo e opcional no ACP: sessao autenticada real nao o envia; so o protocolo e as capacidades sao garantidos.
        assert res["protocolVersion"] == 1
        assert isinstance(c.capacidades, dict) and "promptCapabilities" in c.capacidades
        assert c.auth_methods, "o agente deve anunciar ao menos um metodo de autenticacao"
    finally:
        c.encerrar()
