"""Melhorias do orquestrador (9.4, 9.7-9.11): telemetria OTel, retomada compacta, subagentes, roteamento que aprende,
painel de custo e regras de controle do usuario."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from forja.adapters.kiro_acp.mediador import MediadorPermissoes
from forja.adapters.kiro_acp.provedor import ProvedorKiroAcp, montar_prompt
from forja.adapters.sqlite import tabelas as T
from forja.agentes.base import ControleExecucao
from forja.agentes.estilo import PerfilTrabalho
from forja.conversa.briefing import extrair_subtarefas
from forja.dominio.contratos import MensagemSaida, ObjetivoIn, ProjetoIn, ResultadoAgente, TarefaIn, TransicaoIn
from forja.dominio.erros import ValidacaoDominio
from forja.dominio.estados import EstadoTarefa
from forja.observabilidade.telemetria import Telemetria, montar_rastro, validar_endpoint
from forja.orquestracao.aprendizado_rotas import AprendizadoRotas, desfecho
from forja.orquestracao.custos import CustosServico
from forja.orquestracao.roteamento import classificar
from forja.orquestracao.servico import Servico
from forja.orquestracao.subtarefas import SubtarefasServico
from forja.seguranca import regras
from tests.test_acp import _ctl, _tarefa
from tests.test_roteamento import _prov, _t

ET = EstadoTarefa
WS = Path("C:/ws") if __import__("os").name == "nt" else Path("/ws")
OPCOES = [{"optionId": "ok", "kind": "allow_once"}, {"optionId": "nao", "kind": "reject_once"}]


def _execucao(s: Servico, nome: str = "t", **kw) -> tuple[dict, dict]:
    p, _ = s.criar_projeto(ProjetoIn(nome=nome))
    o, _ = s.criar_objetivo(ObjetivoIn(projeto_id=p["id"], titulo="o"))
    t, _ = s.criar_tarefa(TarefaIn(objetivo_id=o["id"], titulo=nome, criterios_aceite=["testes passam"],
                                   entrada={"mock_cenario": "sucesso", "mock_passos": 1}, **kw))
    a = s.transicionar(t["id"], TransicaoIn(para=ET.CLASSIFICADA, expected_version=1))[0]
    t = s.transicionar(t["id"], TransicaoIn(para=ET.PREPARADA, expected_version=a["versao_estado"]))[0]
    ex = s.criar_execucao(t["id"])
    s.iniciar_execucao(ex["id"])
    s.aguardar(ex["id"])
    return s.obter(T.Tarefa, t["id"]), s.obter(T.Execucao, ex["id"])


def _eventos(repo, execucao_id: str, *itens: tuple[str, dict]) -> None:
    with repo.escrita() as t:
        for i, (tipo, p) in enumerate(itens):
            t.emitir_evento(tipo, f"2026-01-01T00:00:{i:02d}+00:00", p, execucao_id=execucao_id)


# ------------------------------------------------------------------ 9.4 telemetria
def test_rastro_otlp_com_convencoes_gen_ai_e_sem_conteudo(servico: Servico, repo):
    _t_, ex = _execucao(servico, "tele")
    _eventos(repo, ex["id"], ("kiro.rota", {"nivel": "normal", "parte": "execucao"}),
             ("kiro.configuracao", {"aplicados": {"modelo": "claude-sonnet-5.5", "esforco": "medium"}, "parte": "execucao"}),
             ("kiro.ferramenta", {"titulo": "Read File", "tipo": "read", "status": "pending"}),
             ("kiro.ferramenta", {"titulo": "Read File", "tipo": "read", "status": "completed"}),
             ("kiro.testes_forja", {"ok": False, "segundos": 1.5}))
    with repo.leitura() as t:
        doc = montar_rastro(t.obter(T.Execucao, ex["id"]), t.eventos_da_execucao(ex["id"]))
    spans = doc["resourceSpans"][0]["scopeSpans"][0]["spans"]
    nomes = [s["name"] for s in spans]
    assert nomes[0] == "invoke_agent forja" and "chat claude-sonnet-5.5" in nomes and "execute_tool read" in nomes and "execute_tool forja.testes" in nomes
    raiz = spans[0]
    attrs = {a["key"]: a["value"] for a in raiz["attributes"]}
    assert attrs["gen_ai.operation.name"] == {"stringValue": "invoke_agent"} and attrs["gen_ai.request.model"] == {"stringValue": "claude-sonnet-5.5"}
    assert all(s["traceId"] == raiz["traceId"] and len(s["traceId"]) == 32 for s in spans)
    assert all(s.get("parentSpanId") == raiz["spanId"] for s in spans[1:])
    testes = next(s for s in spans if s["name"] == "execute_tool forja.testes")
    assert testes["status"]["code"] == 2  # falha vira status de erro
    assert "prompt" not in json.dumps(doc).lower()


def test_telemetria_arquivo_e_coletor_so_em_loopback(servico: Servico, repo, tmp_path):
    _t_, ex = _execucao(servico, "tele2")
    enviados = []
    pronto = threading.Event()
    tel = Telemetria(repo, tmp_path / "logs", "http://127.0.0.1:4318/v1/traces", enviar=lambda u, c: (enviados.append((u, c)), pronto.set()))
    tel.ao_finalizar(ex["id"])
    assert not (tmp_path / "logs" / "telemetria").exists()  # desligada por padrao
    tel.definir_modo("otlp_local")
    tel.ao_finalizar(ex["id"])
    [arquivo] = list((tmp_path / "logs" / "telemetria").glob("rastros-*.jsonl"))
    assert json.loads(arquivo.read_text(encoding="utf-8").splitlines()[0])["resourceSpans"]
    assert pronto.wait(5) and enviados[0][0].startswith("http://127.0.0.1")
    for ruim in ("http://exemplo.com:4318/v1/traces", "ftp://127.0.0.1/x", "http://10.0.0.5:4318"):
        with pytest.raises(ValidacaoDominio):
            validar_endpoint(ruim)
    tel2 = Telemetria(repo, tmp_path / "l2", "http://exemplo.com/v1/traces", enviar=lambda u, c: enviados.append(u))
    tel2.definir_modo("otlp_local")
    tel2.ao_finalizar(ex["id"])  # endpoint remoto: nada sai (falha segura, sem excecao)
    assert len(enviados) == 1


# ------------------------------------------------------------------ 9.7 retomada compacta
def test_resumo_de_progresso_e_sessao_nova_quando_o_contexto_ficou_grande(servico: Servico, repo, tmp_path):
    _t_, ex = _execucao(servico, "ctx")
    _eventos(repo, ex["id"], ("kiro.ferramenta", {"titulo": "Edit src/a.py", "tipo": "edit", "status": "completed"}),
             ("kiro.ferramenta", {"titulo": "Read src/b.py", "tipo": "read", "status": "completed"}),
             ("kiro.testes_forja", {"ok": False, "falhas": 2}), ("kiro.contexto", {"total": 150_000}))
    with repo.leitura() as t:
        progresso, contexto = servico._progresso_anterior(t, ex["id"])
    assert "edit x1" in progresso and "read x1" in progresso and "Edit src/a.py" in progresso and "falharam (2" in progresso
    assert contexto == 150_000
    retomada = {"entendimento": "E", "decisoes": [], "respostas": ["siga"], "progresso": progresso, "contexto_anterior": contexto}
    assert "O que ja foi feito antes" in montar_prompt({**_tarefa(), "retomada": retomada})
    assert "O que ja foi feito antes" not in montar_prompt({**_tarefa(), "retomada": retomada}, sessao_carregada=True)
    p = ProvedorKiroAcp(__import__("tests.test_acp", fromlist=["cmd"]).cmd("carregavel"), tmp_path / "ws", timeout_prompt=20, timeout_handshake=10)
    ctl, eventos = _ctl()
    r = p.executar({**_tarefa(), "retomada": retomada}, {"session_id": "sess-antiga"}, ctl)
    tipos = [x for x, _ in eventos]
    assert r.estado == "concluida" and "kiro.contexto_compactado" in tipos and "kiro.sessao_carregada" not in tipos
    assert "carregada=False" in r.artefatos[0].conteudo


# ------------------------------------------------------------------ 9.8 subagentes
def test_extrair_subtarefas_tolerante():
    assert extrair_subtarefas("1. **Sessao**: trocar por token\n- Testes: cobrir\n") == [
        {"titulo": "Sessao", "descricao": "trocar por token"}, {"titulo": "Testes", "descricao": "cobrir"}]
    assert extrair_subtarefas("1. so uma: parte") == [] and extrair_subtarefas("Nenhuma") == []
    assert len(extrair_subtarefas("\n".join(f"{i}. parte {i}: x" for i in range(1, 9)))) == 4


def test_plano_dividido_para_antes_de_executar(tmp_path, repo, relogio):
    t = _t("Refatorar a arquitetura de autenticacao", "migrar sessoes e revisar seguranca", modo="alteracao_codigo", criterios=list("abcd"))
    ctl, eventos = _ctl()
    r = _prov(tmp_path, repo, relogio, cenario="planeja_subtarefas").executar(t, {}, ctl)
    assert r.estado == "bloqueada" and r.consumo.chamadas_modelo == 1 and r.pendencias[0].startswith("subtarefas_propostas: 2")
    [m] = [m for m in r.mensagens if m.tipo == "subtarefas"]
    assert [s["titulo"] for s in m.dados["subtarefas"]] == ["Modulo de sessao", "Testes de auth"]
    assert dict(eventos)["kiro.plano"]["subtarefas"] == 2
    p = _prov(tmp_path, repo, relogio, cenario="planeja_subtarefas")
    p.subagentes = "desligado"
    ctl2, _ = _ctl()
    r2 = p.executar(t, {}, ctl2)
    assert r2.estado == "concluida" and r2.consumo.chamadas_modelo == 2  # desligado: nem pede a divisao


def _res_subtarefas() -> ResultadoAgente:
    return ResultadoAgente(estado="bloqueada", resumo="plano dividido", agente_id="kiro", mensagens=[MensagemSaida(
        tipo="subtarefas", conteudo="1. a\n2. b", dados={"subtarefas": [{"titulo": "parte A", "descricao": "faz A"},
                                                                         {"titulo": "parte B", "descricao": "faz B"}]})])


def test_subtarefas_propostas_ficam_no_backlog(servico: Servico):
    pai, ex = _execucao(servico, "pai-propor")
    sub = SubtarefasServico(servico)
    sub.ao_finalizar(ex["id"], _res_subtarefas())
    sub.ao_finalizar(ex["id"], _res_subtarefas())  # idempotente
    filhos = [t for t in servico.listar(T.Tarefa, objetivo_id=pai["objetivo_id"]) if (t["entrada"] or {}).get("subtarefa_de") == pai["id"]]
    assert len(filhos) == 3 and {t["estado"] for t in filhos} == {ET.CLASSIFICADA.value}
    cons = next(t for t in filhos if (t["entrada"] or {}).get("consolida"))
    assert len(cons["dependencias"]) == 2 and cons["criterios_aceite"] == pai["criterios_aceite"]
    assert all(t["politicas"]["complexidade"] == "normal" for t in filhos)  # subtarefa nunca se divide de novo
    assert classificar({**cons, "titulo": "Refatorar arquitetura de seguranca migrar"}).nivel == "normal"


def test_subtarefas_executam_em_paralelo_e_consolidam(servico: Servico):
    pai, ex = _execucao(servico, "pai-exec")
    sub = SubtarefasServico(servico)
    sub.modo = "executar"
    servico.ao_finalizar.append(sub.ao_finalizar)
    sub.ao_finalizar(ex["id"], _res_subtarefas())
    for _ in range(400):
        filhos = [t for t in servico.listar(T.Tarefa, objetivo_id=pai["objetivo_id"]) if (t["entrada"] or {}).get("subtarefa_de")]
        if len(filhos) == 3 and all(t["estado"] == ET.CONCLUIDA.value for t in filhos):
            break
        threading.Event().wait(0.05)
    assert len(filhos) == 3 and all(t["estado"] == ET.CONCLUIDA.value for t in filhos), [t["estado"] for t in filhos]


# ------------------------------------------------------------------ 9.9 roteamento que aprende
def test_desfecho_conta_so_o_que_diz_algo_da_rota():
    assert desfecho({"estado": "concluida"}) is True and desfecho({"estado": "falhou"}) is False
    assert desfecho({"estado": "pausada", "resultado": {"pendencias": ["testes_falhando: pytest"]}}) is False
    assert desfecho({"estado": "pausada", "resultado": {"pendencias": ["aguardando_decisoes_do_usuario"]}}) is None
    assert desfecho({"estado": "cancelada"}) is None


def test_nivel_que_falha_sobe_um_degrau_e_nivel_forcado_nao_muda(repo, relogio):
    a = AprendizadoRotas(repo, relogio)
    tarefa = _t("O que faz a funcao enfileirar?")
    rota = classificar(tarefa)
    assert rota.nivel == "simples" and a.ajustar(rota, tarefa) == rota  # sem historico: regra fixa
    for _ in range(4):
        a.registrar("simples", "rapida", "claude-haiku-5.5", False)
    assert a.ajustar(rota, tarefa) == rota  # menos de 5 execucoes: ainda nao decide
    a.registrar("simples", "rapida", "claude-haiku-5.5", False)
    nova = a.ajustar(rota, tarefa)
    assert nova.nivel == "normal" and nova.parte == "execucao" and "aprendido" in nova.motivos[-1]
    forcada = {**tarefa, "politicas": {"complexidade": "simples"}}
    assert a.ajustar(classificar(forcada), forcada).nivel == "simples"
    a.ativo = False
    assert a.ajustar(rota, tarefa) == rota
    a.ativo = True
    for _ in range(10):
        a.registrar("simples", "rapida", "claude-haiku-5.5", True)
    assert a.ajustar(rota, tarefa) == rota  # recuperou a taxa: volta a regra fixa


def test_provedor_usa_a_rota_aprendida(tmp_path, repo, relogio):
    a = AprendizadoRotas(repo, relogio)
    for _ in range(5):
        a.registrar("simples", "rapida", "x", False)
    p = _prov(tmp_path, repo, relogio)
    p.ajustar_rota = a.ajustar
    ctl, eventos = _ctl()
    p.executar(_t("O que faz a funcao enfileirar?"), {}, ctl)
    assert dict(eventos)["kiro.rota"]["nivel"] == "normal"


# ------------------------------------------------------------------ 9.10 custo
class _Catalogo:
    def listar(self) -> dict:
        return {"modelos": [{"id": "claude-opus-5.5", "custo": 2.2}, {"id": "claude-sonnet-5.5", "custo": 1.3}]}


def test_painel_de_custo_estima_creditos_por_modelo_e_parte(servico: Servico, repo, relogio):
    _t1, ex = _execucao(servico, "custo")  # mock: custo zero
    with repo.escrita() as t:
        t.atualizar(T.Execucao, ex["id"], resultado={"mock": False, "chamadas_acumuladas": 3,
                                                      "consumo": {"chamadas_modelo": 3, "tokens_input": 100, "tokens_output": 50}})
    _eventos(repo, ex["id"], ("kiro.configuracao", {"aplicados": {"modelo": "claude-opus-5.5"}, "parte": "planejamento"}),
             ("kiro.configuracao", {"aplicados": {"modelo": "claude-sonnet-5.5"}, "parte": "execucao"}))
    _t2, mock = _execucao(servico, "custo-mock")
    p = CustosServico(repo, _Catalogo(), relogio).painel(30)
    assert p["estimativa"] and p["catalogo_disponivel"] and p["total"]["execucoes"] == 2 and p["total"]["simuladas"] == 1
    assert p["total"]["creditos_estimados"] == round(2.2 + 1.3 + 1.3, 2)  # plano no opus; execucao + 1 turno extra no sonnet
    assert p["por_modelo"]["claude-opus-5.5"]["turnos"] == 1 and p["por_parte"]["execucao"]["turnos"] == 2
    assert p["total"]["tokens_entrada"] == 100 and p["mais_caras"][0]["titulo"] == "custo"
    assert CustosServico(repo, None, relogio).painel(1)["catalogo_disponivel"] is False


# ------------------------------------------------------------------ 9.11 regras de controle do usuario
def _mediador(rs: list[dict], nivel: str = "liberado"):
    eventos, perguntas = [], []
    ctl = ControleExecucao(lambda cp: None, lambda t, p: eventos.append((t, p)), aprovar=lambda itens: perguntas.append(itens) or {"aprovados": []})
    perfil = PerfilTrabalho(nivel=nivel, regras=regras.carregar(regras.validar_regras(rs)))
    return MediadorPermissoes(ctl, WS, janela=0.01, perfil=perfil), eventos, perguntas


def test_validacao_das_regras():
    ok = regras.validar_regras([{"nome": "pytest", "categoria": "executar_comando", "comando_contem": "pytest", "acao": "aprovar"}])
    assert ok[0]["ativa"] is True
    for ruim in ([{"nome": "x", "acao": "aprovar"}], [{"nome": "x", "acao": "talvez", "categoria": "ler"}],
                 [{"nome": "x", "acao": "negar", "categoria": "inventada"}], "nao-e-lista", [{"nome": "", "acao": "negar", "categoria": "ler"}]):
        with pytest.raises(ValidacaoDominio):
            regras.validar_regras(ruim)
    with pytest.raises(ValidacaoDominio):
        regras.validar_regras([{"nome": f"r{i}", "categoria": "ler", "acao": "negar"} for i in range(regras.MAX_REGRAS + 1)])


def test_regra_negar_vence_e_aprovar_nao_libera_acao_protegida():
    m, eventos, perguntas = _mediador([
        {"nome": "pytest livre", "categoria": "executar_comando", "comando_contem": "pytest", "acao": "aprovar"},
        {"nome": "sem pytest lento", "comando_contem": "pytest --slow", "acao": "negar"},
        {"nome": "proteger migracoes", "categoria": "modificar_arquivos", "caminho_glob": "*migrations*", "acao": "perguntar"},
        {"nome": "tudo excluir", "categoria": "excluir", "acao": "aprovar"},
    ])
    exec_ = lambda c: {"toolCall": {"toolCallId": c, "kind": "execute", "rawInput": {"command": c}}, "options": OPCOES}  # noqa: E731
    assert m.decidir(exec_("pytest -q")) == "ok" and not perguntas  # regra aprova (nivel liberado sozinho perguntaria)
    assert m.decidir(exec_("pytest --slow")) == "nao" and not perguntas  # negar vence aprovar
    editar = {"toolCall": {"toolCallId": "e", "kind": "edit", "locations": [{"path": str(WS / "app" / "migrations" / "0001.py")}]}, "options": OPCOES}
    assert m.decidir(editar) == "nao" and len(perguntas) == 1  # 'perguntar' tira a aprovacao automatica do nivel liberado
    assert m.decidir(exec_("rm -rf build")) == "nao" and len(perguntas) == 2  # 'aprovar' nunca libera excluir: pergunta
    segredo = {"toolCall": {"toolCallId": "s", "kind": "read", "locations": [{"path": str(WS / ".env")}]}, "options": OPCOES}
    m2, _e, p2 = _mediador([{"nome": "ler tudo", "categoria": "ler", "acao": "aprovar"}])
    assert m2.decidir(segredo) == "nao" and not p2  # segredo: negado antes de qualquer regra
    assert [p["regra"] for t, p in eventos if t == "kiro.regra_aplicada"][:2] == ["pytest livre", "sem pytest lento"]


def test_regras_pela_tela_valem_no_perfil(client):
    prefs = client.get("/api/v1/preferencias").json()
    r = client.put("/api/v1/preferencias", json={"expected_version": prefs["versao"], "valores": {
        "regras_controle": [{"nome": "migracoes", "categoria": "modificar_arquivos", "caminho_glob": "*migrations*", "acao": "perguntar"}]}})
    assert r.status_code == 200, r.text
    perfil = client.app.state.prefs.perfil_trabalho()
    assert perfil.regras[0].nome == "migracoes" and perfil.isolamento_testes == "basico"
    ruim = client.put("/api/v1/preferencias", json={"expected_version": r.json()["versao"], "valores": {"regras_controle": [{"nome": "x", "acao": "negar"}]}})
    assert ruim.status_code == 422 or ruim.status_code == 400
