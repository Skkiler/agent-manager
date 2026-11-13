"""Perfis por papel (2.8), controle de escopo (anti 'esticar'), caderno + renovacao de sessao, status barato, roteador Kiro/Codex."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from forja.adapters.agentes_mock.mock import AgenteMock
from forja.adapters.codex_acp.provedor import ProvedorCodexAcp, segredos_nas_pastas
from forja.adapters.kiro_acp import perfil_kiro
from forja.adapters.kiro_acp.mediador import MediadorPermissoes
from forja.adapters.kiro_acp.provedor import ProvedorKiroAcp
from forja.adapters.sqlite import tabelas as T
from forja.agentes.estilo import PerfilTrabalho
from forja.agentes.roteador import ProvedoresRoteados
from forja.dominio.contratos import ConsumoMedicao, EvidenciaSaida, MensagemSaida, ResultadoAgente
from forja.dominio.erros import NaoEncontrado, ValidacaoDominio
from forja.dominio.estados import EstadoTarefa
from forja.mcp import servidor as mcp
from forja.orquestracao import escopo
from forja.orquestracao.caderno import Caderno
from forja.orquestracao.restauracao import PontosRestauracao
from forja.orquestracao.servico import Servico
from forja.orquestracao.status import StatusServico, linha_do_tempo
from tests.test_acp import _ctl, cmd
from tests.test_orquestrador_melhorias import _Projetos, _pronta

ET = EstadoTarefa


def _t(titulo="Analisar", descricao="", modo="analise", criterios=None, **kw) -> dict:
    return {"id": "T-teste", "titulo": titulo, "descricao": descricao, "modo": modo, "criterios_aceite": criterios or ["ok"], **kw}


# ------------------------------------------------------------------ 2.8 perfis por papel
def test_perfis_por_papel_tem_as_mesmas_regras_de_segredo_e_escopo(tmp_path):
    base = perfil_kiro.montar([tmp_path / "dados"])
    perfil_kiro.garantir(tmp_path / "agents", [tmp_path / "dados"])
    gravados = sorted(p.stem for p in (tmp_path / "agents").glob("*.json"))
    assert gravados == ["forja", "forja-coordenador", "forja-estudo", "forja-executor", "forja-planejador", "forja-revisor"]
    for papel in perfil_kiro.PAPEIS:
        p = perfil_kiro.montar([tmp_path / "dados"], papel)
        assert p["permissions"] == base["permissions"] and p["prompt"].startswith(perfil_kiro.ESCOPO)
    assert "write" not in perfil_kiro.montar(None, "revisor")["tools"] and "shell" not in perfil_kiro.montar(None, "planejador")["tools"]
    assert perfil_kiro.montar(None, "coordenador")["tools"] == ["read"]
    antes = (tmp_path / "agents" / "forja-executor.json").stat().st_mtime_ns
    perfil_kiro.garantir(tmp_path / "agents", [tmp_path / "dados"])  # idempotente
    assert (tmp_path / "agents" / "forja-executor.json").stat().st_mtime_ns == antes


@pytest.mark.parametrize("parte,disponiveis,esperado", [
    ("execucao", ["vibe", "forja", "forja-executor"], "forja-executor"),
    ("planejamento", ["vibe", "forja", "forja-executor"], "forja"),  # papel ausente: cai no perfil base
    ("revisao", ["vibe", "spec"], None),  # nenhum perfil da Forja: falha fechada
    ("desconhecida", ["forja"], "forja"),
])
def test_modo_para(parte, disponiveis, esperado):
    assert perfil_kiro.modo_para(parte, disponiveis) == esperado


def test_eh_modo_forja():
    assert perfil_kiro.eh_modo_forja("forja") and perfil_kiro.eh_modo_forja("forja-revisor")
    assert not perfil_kiro.eh_modo_forja("forjado") and not perfil_kiro.eh_modo_forja(None) and not perfil_kiro.eh_modo_forja("vibe")


def test_kiro_usa_o_perfil_do_papel_quando_existe(tmp_path):
    ctl, eventos = _ctl()
    r = ProvedorKiroAcp(cmd("perfil_papeis"), tmp_path / "ws", timeout_prompt=20, timeout_handshake=10).executar(
        _t("O que faz a funcao x?"), {}, ctl)
    assert r.estado == "concluida" and "modo=forja-executor" in r.artefatos[0].conteudo
    ctl, _ = _ctl()
    r = ProvedorKiroAcp(cmd("perfil"), tmp_path / "ws2", timeout_prompt=20, timeout_handshake=10).executar(_t("O que faz x?"), {}, ctl)
    assert "modo=forja " in r.artefatos[0].conteudo  # sem perfis por papel: o base continua valendo


# ------------------------------------------------------------------ controle de escopo
def test_avaliar_escopo():
    t = _t("Corrigir validacao do email", modo="alteracao_codigo")
    ok = escopo.avaliar(t, "normal", [{"alterados": ["src/a.py"], "adicionados": []}], "1. alterar src/a.py")
    assert not ok.saiu
    muitos = escopo.avaliar(t, "simples", [{"alterados": [f"f{i}.py" for i in range(5)]}], "")
    assert muitos.saiu and "limite" in muitos.motivos[0]
    doc = escopo.avaliar(t, "normal", [{"adicionados": ["RESUMO.md"]}], "")
    assert doc.docs_nao_pedidos == ["RESUMO.md"] and doc.saiu
    pedido = escopo.avaliar(_t("Atualizar o README", modo="alteracao_codigo"), "normal", [{"adicionados": ["README.md"]}], "")
    assert not pedido.saiu  # documentacao pedida nao conta
    fora = escopo.avaliar(t, "complexa", [{"alterados": ["src/a.py", "x/b.py", "y/c.py", "z/d.py"]}], "Plano: mexer em src/a.py")
    assert fora.fora_do_plano == ["x/b.py", "y/c.py", "z/d.py"] and fora.saiu
    assert escopo.arquivos_do_plano("ver https://x.io/a.html e `pkg/mod.py`") == {"pkg/mod.py"}


def test_mediador_pergunta_ao_passar_do_limite():
    ctl, eventos = _ctl()
    m = MediadorPermissoes(ctl, Path("."))
    m.limite_arquivos = 2
    assert not m._conferir_escopo({"categoria": "modificar_arquivos", "alvos": ["a.py"]})
    assert not m._conferir_escopo({"categoria": "modificar_arquivos", "alvos": ["b.py"]})
    assert not m._conferir_escopo({"categoria": "ler", "alvos": ["c.py"]})  # leitura nao conta
    assert m._conferir_escopo({"categoria": "modificar_arquivos", "alvos": ["c.py"]})
    assert not m._conferir_escopo({"categoria": "modificar_arquivos", "alvos": ["a.py"]})  # arquivo ja escrito: nao pergunta de novo
    assert m._conferir_escopo({"categoria": "excluir", "alvos": ["d.py"]})
    assert [t for t, _ in eventos].count("kiro.escopo_excedido") == 1


class _Esticador:
    """Provedor de teste: faz o pedido (src/a.py) e 'estica' criando documentacao nao pedida."""

    id, mock = "teste.esticador", False

    def executar(self, tarefa, checkpoint, ctl):  # noqa: ANN001, ANN201
        pasta = Path(tarefa["projeto_ctx"]["pastas"][0]["caminho"])
        (pasta / "src").mkdir(exist_ok=True)
        (pasta / "src" / "a.py").write_text("a = 2\n", encoding="utf-8")
        (pasta / "RESUMO_DAS_MUDANCAS.md").write_text("# resumo nao pedido\n", encoding="utf-8")
        return ResultadoAgente(estado="concluida", resumo="ok", agente_id=self.id,
                               evidencias=[EvidenciaSaida(tipo="teste", resumo="arquivos escritos")])


@pytest.mark.parametrize("modo,estado", [("pausar", ET.BLOQUEADA.value), ("avisar", ET.CONCLUIDA.value), ("desligado", ET.CONCLUIDA.value)])
def test_servico_confere_escopo_depois_da_execucao(repo, tmp_path, relogio, modo, estado):
    pasta = tmp_path / "trabalho"
    pasta.mkdir()
    s = Servico(repo, _Esticador(), tmp_path / "artefatos", max_workers=2, relogio=relogio)
    s.projetos = _Projetos(pasta)
    s.restauracao = PontosRestauracao(repo, tmp_path / "pontos", relogio=relogio)
    s.controle_escopo = modo
    try:
        t = _pronta(s, f"corrigir-{modo}")
        ex = s.criar_execucao(t["id"])
        s.iniciar_execucao(ex["id"])
        s.aguardar(ex["id"])
        assert s.obter(T.Tarefa, t["id"])["estado"] == estado
        res = s.obter(T.Execucao, ex["id"])["resultado"]
        tem = any(p.startswith("fora_do_escopo") for p in res["pendencias"])
        assert tem == (modo != "desligado")
        if modo == "pausar":
            with s.repo.leitura() as tx:
                msgs = tx.listar(T.Mensagem, tarefa_id=t["id"], limite=50)
            assert any(m["tipo"] == "verificacao" and "RESUMO_DAS_MUDANCAS.md" in m["conteudo"] for m in msgs)
    finally:
        s.encerrar(timeout=5)


# ------------------------------------------------------------------ caderno, ficha e renovacao de sessao
@pytest.fixture
def servico_mock(repo, tmp_path, relogio):
    s = Servico(repo, AgenteMock(), tmp_path / "artefatos", max_workers=2, relogio=relogio)
    yield s
    s.encerrar(timeout=5)


def test_caderno_salva_sem_duplicar_redige_e_monta_ficha(servico_mock, relogio):
    s = servico_mock
    t = _pronta(s, "cad", modo="analise")
    c = Caderno(s.repo, relogio)
    a = c.salvar(t["id"], "resolvido", "  erro de import   corrigido em src/a.py ")
    assert a["texto"] == "erro de import corrigido em src/a.py"
    assert c.salvar(t["id"], "resolvido", "erro de import corrigido em src/a.py")["id"] == a["id"]  # idempotente
    c.salvar(t["id"], "decisao", "usar Bearer; token=ghp_abcdefghijklmnopqrstuvwxyz0123456789", ref="M1")
    assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in json.dumps(c.listar(t["id"]))
    assert [i["tipo"] for i in c.listar(t["id"], tipo="decisao")] == ["decisao"] and len(c.listar(t["id"], q="IMPORT")) == 1
    with pytest.raises(ValidacaoDominio):
        c.salvar(t["id"], "invalido", "x")
    with pytest.raises(NaoEncontrado):
        c.salvar("T-nao-existe", "fato", "x")
    with s.repo.leitura() as tx:
        ficha = c.ficha(tx, s.obter(T.Tarefa, t["id"]))
    assert ficha.startswith("Objetivo: cad") and "Decidido:" in ficha and "Ja resolvido:" in ficha and "(M1)" in ficha
    with s.repo.leitura() as tx:
        assert len(c.ficha(tx, s.obter(T.Tarefa, t["id"]), limite=40)) == 40


def test_ferramentas_mcp_do_caderno_usam_a_tarefa_da_sessao(monkeypatch):
    chamadas = []

    class Cli:
        def chamar(self, metodo, caminho, json_=None, params=None):  # noqa: ANN001, ANN201
            chamadas.append((metodo, caminho, json_, params))
            return {"id": "CAD-1"} if metodo == "POST" else [{"tipo": "fato", "texto": "x", "ref": ""}]

    monkeypatch.delenv("FORJA_TAREFA_ID", raising=False)
    with pytest.raises(mcp.ErroFerramenta):
        mcp._caderno_salvar(Cli(), {"tipo": "fato", "texto": "x"})
    monkeypatch.setenv("FORJA_TAREFA_ID", "T-abc123")
    assert mcp._caderno_salvar(Cli(), {"tipo": "fato", "texto": "y" * 900})["ok"]
    assert chamadas[-1][1] == "/tarefas/T-abc123/caderno" and len(chamadas[-1][2]["texto"]) == 600
    assert mcp._caderno_consultar(Cli(), {"q": "x"}) == [{"tipo": "fato", "texto": "x", "ref": None}]
    with pytest.raises(mcp.ErroFerramenta):
        mcp._caderno_salvar(Cli(), {"tipo": "outro", "texto": "x"})
    monkeypatch.setenv("FORJA_TAREFA_ID", "../../etc")
    with pytest.raises(mcp.ErroFerramenta):
        mcp._caderno_salvar(Cli(), {"tipo": "fato", "texto": "x"})


def test_sessao_grande_e_trocada_por_uma_nova_com_a_ficha(tmp_path):
    ctl, eventos = _ctl()
    p = ProvedorKiroAcp(cmd("planeja_contexto"), tmp_path / "ws", timeout_prompt=20, timeout_handshake=10,
                        perfil_de=lambda: PerfilTrabalho(nivel="liberado", correcao="desligada"))
    p.ficha_de = lambda tarefa: "Objetivo: refatorar\nDecidido:\n- CADERNO-OK usar tokens"
    t = _t("Refatorar a arquitetura de autenticacao", "migrar sessoes e revisar seguranca", modo="alteracao_codigo", criterios=list("abcd"))
    r = p.executar(t, {}, ctl)
    tipos = dict(eventos)
    assert r.estado == "concluida" and "kiro.sessao_renovada" in tipos and "kiro.contexto_inicial_alto" in tipos
    assert tipos["kiro.sessao_renovada"]["antes_de"] == "execucao do plano"
    assert "[sessao=sess-fake-2 ficha=True caderno=True]" in r.artefatos[0].conteudo
    p2 = ProvedorKiroAcp(cmd("planeja_contexto"), tmp_path / "ws2", timeout_prompt=20, timeout_handshake=10,
                         perfil_de=lambda: PerfilTrabalho(nivel="liberado", correcao="desligada"))
    p2.limite_contexto_sessao = 0  # desligado: mesma sessao
    ctl, eventos = _ctl()
    r = p2.executar(t, {}, ctl)
    assert "kiro.sessao_renovada" not in dict(eventos) and "sessao=sess-fake-1" in r.artefatos[0].conteudo


# ------------------------------------------------------------------ status barato
def _executada(s: Servico, nome: str) -> tuple[dict, dict]:
    t = _pronta(s, nome, modo="analise")
    ex = s.criar_execucao(t["id"])
    s.iniciar_execucao(ex["id"])
    s.aguardar(ex["id"])
    return s.obter(T.Tarefa, t["id"]), s.obter(T.Execucao, ex["id"])


def _res(**kw) -> ResultadoAgente:
    return ResultadoAgente(estado="concluida", resumo="Analisei o modulo.", agente_id="kiro.acp", consumo=ConsumoMedicao(), **kw)


def _status_msgs(s: Servico, tarefa_id: str) -> list[dict]:
    with s.repo.leitura() as t:
        return [m for m in t.listar(T.Mensagem, tarefa_id=tarefa_id, limite=50) if m["tipo"] == "status"]


def test_status_em_lote_com_modelo_barato_e_reserva(servico_mock, relogio):
    s = servico_mock
    (t1, e1), (t2, e2) = _executada(s, "um"), _executada(s, "dois")
    pedidos = []

    def turno(texto: str, parte: str) -> str:
        pedidos.append((texto, parte))
        return f"### {t1['id']}\nAnalisei o modulo um e nao falta nada.\n### {t2['id']}\nTudo certo no dois."

    st = StatusServico(s.repo, turno, relogio)
    st.ao_finalizar(e1["id"], _res())
    st.ao_finalizar(e2["id"], _res())
    if st._timer:
        st._timer.cancel()
    assert st.processar() == 2 and len(pedidos) == 1 and pedidos[0][1] == "status"  # UMA chamada para o lote
    assert "<<TAREFAS" in pedidos[0][0] or "TAREFAS" in pedidos[0][0]
    m1 = _status_msgs(s, t1["id"])
    assert m1[0]["conteudo"] == "Analisei o modulo um e nao falta nada." and m1[0]["dados"]["origem"] == "modelo"

    def quebra(texto: str, parte: str) -> str:
        raise RuntimeError("sem kiro")

    st2 = StatusServico(s.repo, quebra, relogio)
    st2.ao_finalizar(e1["id"], _res())
    if st2._timer:
        st2._timer.cancel()
    st2.processar()
    ultimo = _status_msgs(s, t1["id"])[-1]
    assert ultimo["dados"]["origem"] == "deterministico" and "concluída" in ultimo["conteudo"]


def test_status_nao_duplica_conversa_e_respeita_modo(servico_mock, relogio):
    s = servico_mock
    t, e = _executada(s, "tres")
    st = StatusServico(s.repo, None, relogio)
    antes = len(_status_msgs(s, t["id"]))
    st.ao_finalizar(e["id"], _res(mensagens=[MensagemSaida(tipo="resposta", conteudo="ja falei")]))
    assert len(_status_msgs(s, t["id"])) == antes  # o agente ja falou na conversa
    st.modo = "desligado"
    st.ao_finalizar(e["id"], _res())
    assert len(_status_msgs(s, t["id"])) == antes
    st.modo = "deterministico"
    st.ao_finalizar(e["id"], _res())
    assert len(_status_msgs(s, t["id"])) == antes + 1
    lt = linha_do_tempo(s.repo, e["id"])
    assert lt["tarefa_id"] == t["id"] and isinstance(lt["linha"], list) and linha_do_tempo(s.repo, "EX-nada") == {}


def test_status_tem_teto_por_hora(servico_mock, relogio, monkeypatch):
    from forja.orquestracao import status as mod

    monkeypatch.setattr(mod, "MAX_POR_HORA", 1)
    st = StatusServico(servico_mock.repo, lambda *_: "", relogio)
    assert st._pode_chamar() and not st._pode_chamar()


# ------------------------------------------------------------------ roteador Kiro/Codex
class _Ag:
    def __init__(self, id_: str, res: ResultadoAgente | None = None, comando: list[str] | None = None) -> None:
        self.id, self.mock, self.comando = id_, False, comando or ["x"]
        self.res = res or ResultadoAgente(estado="concluida", resumo=f"feito por {id_}", agente_id=id_)
        self.chamadas: list[dict] = []

    def executar(self, tarefa, checkpoint, ctl):  # noqa: ANN001, ANN201
        self.chamadas.append(checkpoint)
        ctl.registrar_checkpoint({"session_id": f"s-{self.id}"})
        return self.res

    def turno_rapido(self, texto, parte="status", timeout=120.0):  # noqa: ANN001, ANN201
        return f"rapido {self.id}"


def _ctl_cp():
    cps: list = []
    eventos: list = []
    from forja.agentes.base import ControleExecucao

    return ControleExecucao(cps.append, lambda t, p: eventos.append((t, p))), cps, eventos


def test_roteador_so_kiro_por_padrao_e_codex_desligado():
    k, c = _Ag("kiro.acp"), _Ag("codex.acp")
    r = ProvedoresRoteados(k, c)
    ctl, cps, _ = _ctl_cp()
    assert r.executar(_t(), {}, ctl).agente_id == "kiro.acp" and not c.chamadas
    assert cps[-1]["provedor"] == "kiro.acp"  # a sessao fica carimbada com o agente
    r.modo = "codex_primeiro"
    assert r.executar(_t(), {}, ctl).agente_id == "kiro.acp"  # Codex desligado (codex_ativo=False)
    r.codex_ativo = True
    assert r.executar(_t(), {}, ctl).agente_id == "codex.acp"
    assert {a["id"]: a["ativo"] for a in r.estado()["agentes"]} == {"kiro.acp": True, "codex.acp": True}


def test_reserva_so_quando_o_agente_nao_produziu_trabalho():
    fora = ResultadoAgente(estado="bloqueada", resumo="Kiro CLI nao encontrado.", agente_id="kiro.acp", pendencias=["kiro_cli_ausente"])
    k, c = _Ag("kiro.acp", fora), _Ag("codex.acp")
    r = ProvedoresRoteados(k, c)
    r.codex_ativo, r.modo = True, "auto"
    ctl, _, eventos = _ctl_cp()
    assert r.executar(_t(), {}, ctl).agente_id == "codex.acp"
    assert "provedor.reserva" in dict(eventos) and r.estado()["agentes"][0]["resfriando_s"] > 0
    assert r.ordem(_t())[0] is c  # Kiro em resfriamento
    trabalhou = ResultadoAgente(estado="falhou", resumo="rate limit", agente_id="kiro.acp",
                                consumo=ConsumoMedicao(tokens_output=50))
    r2 = ProvedoresRoteados(_Ag("kiro.acp", trabalhou), c2 := _Ag("codex.acp"))
    r2.codex_ativo, r2.modo = True, "auto"
    ctl, _, _ = _ctl_cp()
    assert r2.executar(_t(), {}, ctl).estado == "falhou" and not c2.chamadas  # ja produziu: nunca repete noutro agente


def test_retomada_volta_para_o_agente_que_comecou():
    k, c = _Ag("kiro.acp"), _Ag("codex.acp")
    r = ProvedoresRoteados(k, c)
    r.codex_ativo, r.modo = True, "auto"
    ctl, _, _ = _ctl_cp()
    r.executar({**_t(), "retomada": {"respostas": ["ok"]}}, {"provedor": "codex.acp", "session_id": "s1"}, ctl)
    assert c.chamadas == [{"provedor": "codex.acp", "session_id": "s1"}] and not k.chamadas
    r.executar(_t(), {"provedor": "codex.acp", "session_id": "s1"}, ctl)
    assert k.chamadas == [{}]  # outro agente nunca recebe a sessao do primeiro


def test_codex_nao_e_elegivel_em_pasta_com_segredo(tmp_path):
    (tmp_path / "proj").mkdir()
    (tmp_path / "proj" / "app.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "proj" / "node_modules").mkdir()
    (tmp_path / "proj" / "node_modules" / ".env").write_text("A=1\n", encoding="utf-8")  # dependencias nao contam
    assert segredos_nas_pastas([tmp_path / "proj"]) == ([], True)
    (tmp_path / "proj" / ".env").write_text("A=1\n", encoding="utf-8")
    assert segredos_nas_pastas([tmp_path / "proj"]) == (["proj/.env"], True)
    assert segredos_nas_pastas([tmp_path / "proj"], limite=1)[1] is False
    k, c = _Ag("kiro.acp"), _Ag("codex.acp")
    r = ProvedoresRoteados(k, c)
    r.codex_ativo, r.modo = True, "codex_primeiro"
    ctl, _, _ = _ctl_cp()
    t = _t(projeto_ctx={"pastas": [{"caminho": str(tmp_path / "proj"), "papel": "trabalho"}]})
    assert r.executar(t, {}, ctl).agente_id == "kiro.acp" and not c.chamadas
    assert r.turno_rapido("x") == "rapido codex.acp"


# ------------------------------------------------------------------ Codex pelo ACP (agente falso)
def test_codex_roda_com_ambiente_limpo_e_modo_seguro(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_TESTE_VAZAMENTO", "1")
    monkeypatch.setenv("MEU_API_TOKEN", "segredo")
    ctl, eventos = _ctl()
    r = ProvedorCodexAcp(cmd("codex"), tmp_path / "ws", timeout_prompt=20, timeout_handshake=10).executar(_t("O que faz x?"), {}, ctl)
    texto = r.artefatos[0].conteudo
    assert r.estado == "concluida" and r.agente_id == "codex.acp" and "modo=auto" in texto and "vazou=[]" in texto
    ctl, _ = _ctl()
    r = ProvedorCodexAcp(cmd("codex"), tmp_path / "ws", timeout_prompt=20, timeout_handshake=10).executar(
        {**_t("Revisar x"), "entrada": {"revisao": True}}, {}, ctl)
    assert "modo=read-only" in r.artefatos[0].conteudo  # revisao: somente leitura


def test_codex_falha_fechado(tmp_path):
    ctl, _ = _ctl()
    r = ProvedorCodexAcp(cmd("codex_estranho"), tmp_path / "ws", timeout_prompt=20, timeout_handshake=10).executar(_t(), {}, ctl)
    assert r.estado == "bloqueada" and "codex_modo_desconhecido" in r.pendencias[0]
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".env").write_text("A=1\n", encoding="utf-8")
    ctl, eventos = _ctl()
    t = _t(projeto_ctx={"projeto": "p", "pastas": [{"caminho": str(proj), "papel": "consulta"}], "anexos": []})
    r = ProvedorCodexAcp(cmd("codex"), tmp_path / "ws2", timeout_prompt=20, timeout_handshake=10).executar(t, {}, ctl)
    assert r.estado == "bloqueada" and r.pendencias[0].startswith("codex_bloqueado_segredos") and "codex.bloqueado_segredos" in dict(eventos)
    r = ProvedorCodexAcp(None, tmp_path / "ws3").executar(_t(), {}, ctl)
    assert r.estado == "bloqueada" and r.pendencias[0].startswith("codex_ausente")


def test_turno_rapido_do_kiro_sem_ferramentas(tmp_path):
    p = ProvedorKiroAcp(cmd("ok"), tmp_path / "ws", timeout_prompt=20, timeout_handshake=10)
    t0 = time.monotonic()
    assert "Analise concluida" in p.turno_rapido("resuma", "status") and time.monotonic() - t0 < 20
