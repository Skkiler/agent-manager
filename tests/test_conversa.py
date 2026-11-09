"""Comunicacao organica agente <-> desenvolvedor + contexto econonomico no prompt: fluxo completo contra SQLite real."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from forja.adapters.agentes_mock.mock import AgenteMock
from forja.adapters.kiro_acp.provedor import ProvedorKiroAcp
from forja.adapters.sqlite import tabelas as T
from forja.adapters.sqlite.repositorio import RepositorioSqlite
from forja.contexto.construtor import CABECALHO, ConstrutorContexto
from forja.dominio.contratos import ConversaIn, ObjetivoIn, Orcamento, Politicas, ProjetoIn, TarefaIn, TransicaoIn
from forja.dominio.estados import EstadoExecucao, EstadoTarefa
from forja.memoria.contratos import MemoriaIn
from forja.memoria.modelo import Principal
from forja.orquestracao.memoria_servico import ServicoMemoria
from forja.orquestracao.servico import Servico

FAKE = str(Path(__file__).parent / "fakes" / "fake_acp_agent.py")
ET = EstadoTarefa
P = Principal("t", frozenset({"publico"}))


@pytest.fixture
def memoria(repo: RepositorioSqlite) -> ServicoMemoria:
    return ServicoMemoria(repo)


def servico_kiro(repo, tmp_path, memoria, cenario: str, contexto: bool = True, **kw) -> Servico:
    prov = ProvedorKiroAcp([sys.executable, FAKE, cenario], tmp_path / "ws", timeout_prompt=30, timeout_handshake=10)
    construtor = ConstrutorContexto(memoria, P, ["publico"]) if contexto else None
    return Servico(repo, prov, tmp_path / "art", max_workers=2, construtor_contexto=construtor, **kw)


def servico_mock(repo, tmp_path) -> Servico:
    return Servico(repo, AgenteMock(), tmp_path / "art", max_workers=2)


def criar_tarefa(s: Servico, titulo="Definir a autenticacao da API", descricao="", nome="p", **kw) -> dict:
    p, _ = s.criar_projeto(ProjetoIn(nome=f"{nome}-{id(kw)}-{titulo[:8]}"))
    o, _ = s.criar_objetivo(ObjetivoIn(projeto_id=p["id"], titulo="o"))
    t, _ = s.criar_tarefa(TarefaIn(objetivo_id=o["id"], titulo=titulo, descricao=descricao, criterios_aceite=["decidir"], **kw))
    c = s.transicionar(t["id"], TransicaoIn(para=ET.CLASSIFICADA, expected_version=1))[0]
    return s.transicionar(t["id"], TransicaoIn(para=ET.PREPARADA, expected_version=c["versao_estado"]))[0]


def rodar(s: Servico, tarefa: dict) -> dict:
    ex = s.criar_execucao(tarefa["id"])
    s.iniciar_execucao(ex["id"])
    s.aguardar(ex["id"], 40)
    return ex


def tipos(msgs: list[dict]) -> list[tuple[str, str]]:
    return [(m["papel"], m["tipo"]) for m in msgs]


def eco(s: Servico, tarefa_id: str) -> str:
    """Prompt exato recebido pelo agente (cenario 'eco' devolve o que recebeu)."""
    msg = next(m for m in s.conversa(tarefa_id) if m["tipo"] == "resposta")
    return msg["conteudo"].split("<<PROMPT>>\n", 1)[1].split("\n<<FIM>>", 1)[0]


# ================================================================ conversa com o mock (sem Kiro)
def test_fluxo_organico_completo_com_uma_unica_resposta(repo, tmp_path):
    s = servico_mock(repo, tmp_path)
    try:
        tarefa = criar_tarefa(s, entrada={"mock_cenario": "conversa", "mock_passos": 1})
        ex = rodar(s, tarefa)
        # rodada 1: o agente entendeu, propos e PEDIU as decisoes JUNTAS; a tarefa espera o desenvolvedor
        assert s.obter(T.Tarefa, tarefa["id"])["estado"] == ET.BLOQUEADA.value
        assert s.obter(T.Execucao, ex["id"])["estado"] == EstadoExecucao.PAUSADA.value
        conversa = s.conversa(tarefa["id"])
        assert tipos(conversa) == [("agente", "entendimento"), ("agente", "decisoes")]
        decisoes = conversa[1]["dados"]["decisoes"]
        assert len(decisoes) == 2 and decisoes[0]["recomendacao"] == "Bearer"  # recomendacao vem junto da pergunta
        assert [m["ordem"] for m in conversa] == [1, 2]
        # UMA resposta em texto livre cobre as duas decisoes e retoma a execucao
        r = s.responder(tarefa["id"], ConversaIn(conteudo="Bearer. E nao publique ainda; primeiro revisar."))
        assert r["retomada_execucao_id"] == ex["id"] and r["aviso"] is None
        s.aguardar(ex["id"], 20)
        assert s.obter(T.Tarefa, tarefa["id"])["estado"] == ET.CONCLUIDA.value
        final = s.conversa(tarefa["id"])
        assert tipos(final) == [("agente", "entendimento"), ("agente", "decisoes"), ("operador", "resposta_operador"),
                                ("agente", "resposta")]
        assert [m["ordem"] for m in final] == [1, 2, 3, 4]  # ordem monotonica mesmo com relogio parado
        assert "1 resposta" in final[3]["conteudo"]
        assert "conversa.resposta_do_operador" in [e["tipo"] for e in s.eventos_apos(0, 1000)]
    finally:
        s.encerrar(5)


def test_responder_sem_retomar_so_registra(repo, tmp_path):
    s = servico_mock(repo, tmp_path)
    try:
        tarefa = criar_tarefa(s, entrada={"mock_cenario": "conversa", "mock_passos": 1})
        ex = rodar(s, tarefa)
        r = s.responder(tarefa["id"], ConversaIn(conteudo="Ainda pensando.", retomar=False))
        assert r["retomada_execucao_id"] is None
        assert s.obter(T.Tarefa, tarefa["id"])["estado"] == ET.BLOQUEADA.value  # segue esperando
        s.iniciar_execucao(ex["id"])  # retomada explicita depois
        s.aguardar(ex["id"], 20)
        assert s.obter(T.Tarefa, tarefa["id"])["estado"] == ET.CONCLUIDA.value
    finally:
        s.encerrar(5)


def test_responder_quando_nao_ha_o_que_retomar_avisa_sem_erro(repo, tmp_path):
    s = servico_mock(repo, tmp_path)
    try:
        tarefa = criar_tarefa(s, entrada={"mock_cenario": "sucesso", "mock_passos": 1})
        rodar(s, tarefa)
        r = s.responder(tarefa["id"], ConversaIn(conteudo="obrigado"))
        assert r["retomada_execucao_id"] is None and "nao ha execucao aguardando" in r["aviso"]
        assert s.conversa(tarefa["id"])[-1]["papel"] == "operador"  # a mensagem fica registrada
    finally:
        s.encerrar(5)


def test_segundo_clique_em_responder_nao_duplica_a_retomada(repo, tmp_path):
    s = servico_mock(repo, tmp_path)
    try:
        tarefa = criar_tarefa(s, entrada={"mock_cenario": "conversa", "mock_passos": 1})
        ex = rodar(s, tarefa)
        primeiro = s.responder(tarefa["id"], ConversaIn(conteudo="Bearer"))
        segundo = s.responder(tarefa["id"], ConversaIn(conteudo="Bearer (de novo)"))
        s.aguardar(ex["id"], 20)
        assert primeiro["retomada_execucao_id"] == ex["id"]
        assert segundo["retomada_execucao_id"] is None and segundo["aviso"]  # nao retoma duas vezes
        assert s.obter(T.Tarefa, tarefa["id"])["estado"] == ET.CONCLUIDA.value
    finally:
        s.encerrar(5)


def test_resposta_do_operador_tem_segredos_redigidos(repo, tmp_path):
    s = servico_mock(repo, tmp_path)
    try:
        tarefa = criar_tarefa(s, entrada={"mock_cenario": "conversa", "mock_passos": 1})
        rodar(s, tarefa)
        r = s.responder(tarefa["id"], ConversaIn(conteudo="Use o token=abc123segredoXYZ no teste", retomar=False))
        assert "abc123segredoXYZ" not in r["mensagem"]["conteudo"]
        assert "abc123segredoXYZ" not in str(s.conversa(tarefa["id"]))
    finally:
        s.encerrar(5)


def test_tarefa_inexistente_na_conversa(repo, tmp_path):
    from forja.dominio.erros import NaoEncontrado

    s = servico_mock(repo, tmp_path)
    try:
        with pytest.raises(NaoEncontrado):
            s.conversa("T-fantasma")
        with pytest.raises(NaoEncontrado):
            s.responder("T-fantasma", ConversaIn(conteudo="x"))
    finally:
        s.encerrar(5)


# ================================================================ conversa com o protocolo do Kiro (agente ACP falso)
def test_kiro_briefing_com_decisoes_bloqueia_e_retomada_conclui(repo, tmp_path, memoria):
    s = servico_kiro(repo, tmp_path, memoria, "briefing", contexto=False)
    try:
        tarefa = criar_tarefa(s)
        ex = rodar(s, tarefa)
        assert s.obter(T.Tarefa, tarefa["id"])["estado"] == ET.BLOQUEADA.value
        msgs = s.conversa(tarefa["id"])
        assert [m["tipo"] for m in msgs] == ["entendimento", "resposta", "decisoes", "proximos_passos"]
        d = next(m for m in msgs if m["tipo"] == "decisoes")["dados"]["decisoes"]
        assert d[0]["pergunta"] == "Usar token Bearer ou cookie?" and d[0]["alternativas"] == ["cookie"]
        assert d[1]["recomendacao"] == "depois da revisao"
        assert s.obter(T.Execucao, ex["id"])["resultado"]["pendencias"] == ["aguardando_decisoes_do_usuario"]
        s.responder(tarefa["id"], ConversaIn(conteudo="Pode ser Bearer."))
        s.aguardar(ex["id"], 40)
        assert s.obter(T.Tarefa, tarefa["id"])["estado"] == ET.CONCLUIDA.value
        assert s.conversa(tarefa["id"])[-1]["tipo"] == "resposta"
    finally:
        s.encerrar(5)


def test_retomada_envia_muito_menos_que_a_primeira_rodada(repo, tmp_path, memoria, validar_memoria):
    m = memoria.criar(P, MemoriaIn(tipo="procedimental", titulo="Autenticacao da API com token Bearer",
                                   resumo="Receita validada de autenticacao", conteudo="Gerar token Bearer e validar a sessao. " * 30,
                                   namespace="publico"))
    validar_memoria(memoria, P, m)
    s = servico_kiro(repo, tmp_path, memoria, "briefing")
    try:
        tarefa = criar_tarefa(s, descricao="Escolher como autenticar a API com token Bearer ou cookie de sessao.")
        ex = rodar(s, tarefa)
        primeira = next(m for m in s.conversa(tarefa["id"]) if m["tipo"] == "entendimento")["conteudo"]
        n1 = int(re.search(r"prompt de (\d+) caracteres", primeira).group(1))
        uso = s.contexto_da_tarefa(tarefa["id"])[0]
        assert uso["itens"] and uso["tokens_contexto"] > 0  # houve contexto na 1a rodada...
        assert uso["uteis"] == []  # ...mas o agente NAO o citou: nao e repago na retomada
        s.responder(tarefa["id"], ConversaIn(conteudo="Bearer."))
        s.aguardar(ex["id"], 40)
        resposta = next(m for m in s.conversa(tarefa["id"]) if m["papel"] == "agente" and m["tipo"] == "resposta"
                        and "recebi" in m["conteudo"])["conteudo"]
        n2 = int(re.search(r"recebi (\d+) caracteres", resposta).group(1))
        assert n2 < n1 * 0.85, (n1, n2)  # retomada nao reenvia a resposta anterior nem o contexto nao usado
    finally:
        s.encerrar(5)


def test_orcamento_de_chamadas_vale_para_a_tarefa_inteira_nao_por_retomada(repo, tmp_path, memoria):
    s = servico_kiro(repo, tmp_path, memoria, "briefing", contexto=False)
    try:
        tarefa = criar_tarefa(s, orcamento=Orcamento(max_chamadas_modelo=1))
        ex = rodar(s, tarefa)  # 1a chamada: dentro do orcamento (1), fica bloqueada aguardando decisoes
        assert s.obter(T.Tarefa, tarefa["id"])["estado"] == ET.BLOQUEADA.value
        assert s.obter(T.Execucao, ex["id"])["resultado"]["chamadas_acumuladas"] == 1
        s.responder(tarefa["id"], ConversaIn(conteudo="Bearer"))
        s.aguardar(ex["id"], 40)
        final = s.obter(T.Tarefa, tarefa["id"])
        assert final["estado"] == ET.FALHOU.value and "max_chamadas_modelo" in final["motivo_estado"]  # 2a chamada estourou
    finally:
        s.encerrar(5)


def test_briefing_sem_decisoes_conclui_direto_com_secoes_e_evidencia(repo, tmp_path, memoria):
    s = servico_kiro(repo, tmp_path, memoria, "briefing_sem_decisao", contexto=False)
    try:
        tarefa = criar_tarefa(s)
        rodar(s, tarefa)
        assert s.obter(T.Tarefa, tarefa["id"])["estado"] == ET.CONCLUIDA.value
        assert [m["tipo"] for m in s.conversa(tarefa["id"])] == ["entendimento", "resposta", "premissas", "proximos_passos"]
        assert s.listar(T.Evidencia, tarefa_id=tarefa["id"])[0]["tipo"] == "kiro_resposta"
    finally:
        s.encerrar(5)


def test_resposta_longa_nao_e_mais_truncada_em_2000_caracteres(repo, tmp_path, memoria):
    """Regressao: a resposta passava por sanitizar_texto, que corta em 2000 caracteres em silencio."""
    s = servico_kiro(repo, tmp_path, memoria, "briefing_longo", contexto=False)
    try:
        tarefa = criar_tarefa(s)
        rodar(s, tarefa)
        art = s.listar(T.Artefato, tarefa_id=tarefa["id"])[0]
        conteudo = s.obter_artefato(art["id"], com_conteudo=True)["conteudo"]
        assert len(conteudo) > 9000 and "[truncado]" not in conteudo
    finally:
        s.encerrar(5)


def test_consumo_e_estimativa_rotulada_nunca_medicao_do_provedor(repo, tmp_path, memoria):
    s = servico_kiro(repo, tmp_path, memoria, "briefing_sem_decisao", contexto=False)
    try:
        tarefa = criar_tarefa(s)
        ex = rodar(s, tarefa)
        consumo = s.obter(T.Execucao, ex["id"])["resultado"]["consumo"]
        assert consumo["fonte"] == "estimado" and consumo["tokens_input"] > 0 and consumo["tokens_output"] > 0
    finally:
        s.encerrar(5)


# ================================================================ contexto no prompt: relevante entra, o resto nao
def test_contexto_relevante_vai_ao_prompt_com_referencia_e_aviso(repo, tmp_path, memoria, validar_memoria):
    m = memoria.criar(P, MemoriaIn(tipo="procedimental", titulo="Autenticacao da API com token Bearer",
                                   resumo="Receita validada", conteudo="Gerar o token e validar a sessao.", namespace="publico"))
    validar_memoria(memoria, P, m)
    s = servico_kiro(repo, tmp_path, memoria, "eco")
    try:
        tarefa = criar_tarefa(s, descricao="Escolher como autenticar a API com token Bearer.")
        rodar(s, tarefa)
        prompt = eco(s, tarefa["id"])
        assert CABECALHO in prompt and "[M1]" in prompt and "Autenticacao da API com token Bearer" in prompt
        assert "## Decisões para você" in prompt  # protocolo de conversa presente
        uso = s.contexto_da_tarefa(tarefa["id"])[0]
        assert uso["itens"][0]["ref"] == "M1" and uso["tokens_contexto"] > 0
        assert "contexto.montado" in [e["tipo"] for e in s.eventos_apos(0, 1000)]
    finally:
        s.encerrar(5)


def test_sem_memoria_relevante_o_prompt_nao_leva_contexto_algum(repo, tmp_path, memoria, validar_memoria):
    m = memoria.criar(P, MemoriaIn(tipo="procedimental", titulo="Receita de feijoada", resumo="culinaria",
                                   conteudo="Cozinhar o feijao com carne.", namespace="publico"))
    validar_memoria(memoria, P, m)
    s = servico_kiro(repo, tmp_path, memoria, "eco")
    try:
        tarefa = criar_tarefa(s, titulo="Definir a autenticacao da API")
        rodar(s, tarefa)
        prompt = eco(s, tarefa["id"])
        assert "CONTEXTO RECUPERADO" not in prompt and "feijoada" not in prompt
        assert s.contexto_da_tarefa(tarefa["id"])[0]["tokens_contexto"] == 0
    finally:
        s.encerrar(5)


def test_tarefa_pode_desligar_o_contexto(repo, tmp_path, memoria, validar_memoria):
    m = memoria.criar(P, MemoriaIn(tipo="procedimental", titulo="Autenticacao da API com token Bearer", resumo="x",
                                   conteudo="token Bearer", namespace="publico"))
    validar_memoria(memoria, P, m)
    s = servico_kiro(repo, tmp_path, memoria, "eco")
    try:
        tarefa = criar_tarefa(s, descricao="autenticar a API com token Bearer", politicas=Politicas(contexto="nenhum"))
        rodar(s, tarefa)
        assert "CONTEXTO RECUPERADO" not in eco(s, tarefa["id"])
        assert s.contexto_da_tarefa(tarefa["id"])[0]["omitidos"] == {"desligado_pela_tarefa": 1}
    finally:
        s.encerrar(5)


def test_citacao_do_agente_marca_o_contexto_como_util(repo, tmp_path, memoria, validar_memoria):
    m = memoria.criar(P, MemoriaIn(tipo="procedimental", titulo="Backup do banco SQLite com integrity_check",
                                   resumo="Receita validada de backup", conteudo="Usar a API nativa e rodar integrity_check.",
                                   namespace="publico"))
    validar_memoria(memoria, P, m)
    s = servico_kiro(repo, tmp_path, memoria, "briefing_sem_decisao")  # a resposta cita [M1]
    try:
        tarefa = criar_tarefa(s, titulo="Fazer backup do banco SQLite", descricao="backup com integrity_check")
        rodar(s, tarefa)
        uso = s.contexto_da_tarefa(tarefa["id"])[0]
        assert [i["ref"] for i in uso["itens"]] == ["M1"] and uso["uteis"] == ["M1"]
        assert uso["tokens_prompt"] > uso["tokens_contexto"] > 0
        ev = [e for e in s.eventos_apos(0, 1000) if e["tipo"] == "contexto.uteis"][0]
        assert ev["payload"] == {"injetados": 1, "usados": 1}
    finally:
        s.encerrar(5)


def test_contexto_nunca_inclui_namespace_nao_liberado(repo, tmp_path, memoria, validar_memoria):
    privado = Principal("d", frozenset({"empresa/acme"}))
    memoria.criar(privado, MemoriaIn(tipo="procedimental", titulo="Autenticacao interna da API", resumo="segredo-da-empresa",
                                     conteudo="autenticar a API com token Bearer interno", namespace="empresa/acme"))
    s = servico_kiro(repo, tmp_path, memoria, "eco")
    try:
        tarefa = criar_tarefa(s, descricao="autenticar a API com token Bearer")
        rodar(s, tarefa)
        assert "segredo-da-empresa" not in eco(s, tarefa["id"])
    finally:
        s.encerrar(5)


def test_falha_no_construtor_de_contexto_nao_impede_a_tarefa(repo, tmp_path, memoria):
    class Quebrado:
        def construir(self, tarefa):
            raise RuntimeError("falha simulada")

        def so_uteis(self, *a):
            return ""

        def marcar_uteis(self, *a):
            return []

    s = servico_kiro(repo, tmp_path, memoria, "briefing_sem_decisao", contexto=False)
    s.construtor_contexto = Quebrado()
    try:
        tarefa = criar_tarefa(s)
        rodar(s, tarefa)
        assert s.obter(T.Tarefa, tarefa["id"])["estado"] == ET.CONCLUIDA.value  # otimizacao falhou; a tarefa nao
    finally:
        s.encerrar(5)


def test_prompt_inicial_e_compacto(repo, tmp_path, memoria):
    """Sem contexto, o protocolo de conversa + tarefa deve caber em poucas centenas de tokens ESTIMADOS."""
    from forja.adapters.kiro_acp.provedor import montar_prompt
    from forja.memoria.saneamento import estimar_tokens

    t = {"titulo": "Definir a autenticacao da API", "descricao": "Escolher entre Bearer e cookie.", "criterios_aceite": ["decidir"]}
    assert estimar_tokens(montar_prompt(t)) < 420
