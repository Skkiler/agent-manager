"""Nivel de autonomia, metodos de acao (tags) e observacoes guia: regra pura, prompt, mediador e integracao com o Kiro (fake)."""

from __future__ import annotations

from pathlib import Path

import pytest

from forja.adapters.kiro_acp.mediador import MediadorPermissoes
from forja.adapters.kiro_acp.provedor import ProvedorKiroAcp, montar_prompt
from forja.agentes.base import ControleExecucao
from forja.agentes.estilo import (
    METODOS,
    NIVEIS,
    SEMPRE_PERGUNTA,
    PerfilTrabalho,
    catalogo,
    validar_metodos,
    validar_observacoes,
)
from forja.dominio.erros import ValidacaoDominio
from forja.seguranca.acoes import descrever_acao
from tests.test_acp import _ctl, _tarefa, cmd

WS = Path("C:/ws") if __import__("os").name == "nt" else Path("/ws")
OPCOES = [{"optionId": "ok", "kind": "allow_once"}, {"optionId": "nao", "kind": "reject_once"}]


def _item(**tc):
    return descrever_acao(tc, WS)


# ------------------------------------------------------------------ regra pura
@pytest.mark.parametrize("nivel,tc,esperado", [
    ("restrito", dict(kind="read", locations=[{"path": str(WS / "a.py")}]), False),
    ("liberado", dict(kind="read", locations=[{"path": str(WS / "a.py")}]), True),
    ("liberado", dict(kind="edit", locations=[{"path": str(WS / "a.py")}]), True),
    ("liberado", dict(kind="execute", rawInput={"command": "pytest -q"}), False),
    ("total", dict(kind="execute", rawInput={"command": "pytest -q"}), True),
    ("total", dict(kind="execute", rawInput={"command": "rm -rf build"}), False),  # destrutivo: sempre pergunta
    ("total", dict(kind="execute", rawInput={"command": "git push origin main"}), False),
    ("total", dict(kind="execute", rawInput={"command": "pip install requests"}), False),
    ("total", dict(kind="execute", rawInput={"command": "curl https://exemplo.com"}), False),
    ("total", dict(kind="edit", locations=[{"path": str(WS.parent / "fora" / "a.py")}]), False),  # fora do workspace
    ("total", dict(kind="read", locations=[{"path": str(WS / ".env")}]), False),  # segredo
    ("total", dict(title="algo estranho"), False),  # nao identificado
    ("total", dict(title="@forja/forja_quadro_ler", kind="other", _meta={"kiro": {"serverName": "forja"}}), True),
])
def test_aprovacao_automatica_respeita_invariantes(nivel, tc, esperado):
    assert PerfilTrabalho(nivel=nivel).aprova_sozinho(_item(**tc)) is esperado


def test_nenhum_nivel_aprova_categorias_que_sempre_perguntam():
    assert all(not (n.automaticas & SEMPRE_PERGUNTA) for n in NIVEIS)
    assert NIVEIS[0].id == "restrito" and not NIVEIS[0].automaticas and "alteracao_codigo" not in NIVEIS[0].modos


def test_validacao_de_tags_e_observacoes():
    assert validar_metodos(["cauteloso", "testador", "cauteloso"]) == ["cauteloso", "testador"]
    for ruim in (["inexistente"], ["direto", "pesquisador"], ["economico", "didatico"], "cauteloso", [1]):
        with pytest.raises(ValidacaoDominio):
            validar_metodos(ruim)
    assert validar_observacoes("  use pytest  ") == "use pytest"
    with pytest.raises(ValidacaoDominio):
        validar_observacoes("api_key = 'sk-abcdefghijklmnopqrstuvwx0123456789'")
    with pytest.raises(ValidacaoDominio):
        validar_observacoes("x" * 2001)


def test_instrucoes_curtas_e_vazias_no_padrao():
    assert PerfilTrabalho().instrucoes() == ""  # perfil padrao nao custa token nenhum
    t = PerfilTrabalho("total", ("cauteloso", "testador"), "Commits em portugues.").instrucoes()
    assert "Acesso total" in t and "Cauteloso:" in t and "Testes:" in t and "Commits em portugues." in t
    todas = PerfilTrabalho("total", tuple(m.id for m in METODOS if m.id not in ("direto", "didatico"))).instrucoes()
    assert len(todas) < 1500  # todas as tags juntas continuam baratas
    assert PerfilTrabalho(metodos=("economico",)).fator_contexto() == 0.5 and PerfilTrabalho().fator_contexto() == 1.0


def test_catalogo_explica_cada_tag_e_nivel():
    c = catalogo()
    assert {m["id"] for m in c["metodos"]} == {m.id for m in METODOS} and all(m["descricao"] for m in c["metodos"])
    assert [n["id"] for n in c["niveis"]] == ["restrito", "liberado", "total"]


# ------------------------------------------------------------------ mediador
def _mediador(nivel):
    eventos, perguntas = [], []
    ctl = ControleExecucao(lambda cp: None, lambda t, p: eventos.append((t, p)), aprovar=lambda itens: perguntas.append(itens) or {"aprovados": []})
    return MediadorPermissoes(ctl, WS, janela=0.01, perfil=PerfilTrabalho(nivel=nivel)), eventos, perguntas


def test_mediador_aprova_sozinho_e_registra_evento():
    m, eventos, perguntas = _mediador("total")
    escolha = m.decidir({"toolCall": {"kind": "execute", "rawInput": {"command": "pytest -q"}, "toolCallId": "1"}, "options": OPCOES})
    assert escolha == "ok" and perguntas == [] and eventos[0][0] == "kiro.permissao_automatica" and eventos[0][1]["nivel"] == "total"


def test_mediador_no_restrito_pergunta_e_destrutivo_pergunta_em_qualquer_nivel():
    m, _e, perguntas = _mediador("restrito")
    assert m.decidir({"toolCall": {"kind": "read", "locations": [{"path": str(WS / "a.py")}], "toolCallId": "1"}, "options": OPCOES}) == "nao"
    assert len(perguntas) == 1
    m, _e, perguntas = _mediador("total")
    assert m.decidir({"toolCall": {"kind": "execute", "rawInput": {"command": "rm -rf src"}, "toolCallId": "2"}, "options": OPCOES}) == "nao"
    assert len(perguntas) == 1


# ------------------------------------------------------------------ provedor (Kiro fake)
def _prov(tmp_path, perfil):
    return ProvedorKiroAcp(cmd("eco"), tmp_path / "ws", timeout_prompt=20, timeout_handshake=10, perfil_de=lambda: perfil)


def test_modo_de_escrita_so_com_autonomia(tmp_path):
    ctl, _ = _ctl()
    r = _prov(tmp_path, PerfilTrabalho()).executar(_tarefa("alteracao_codigo"), {}, ctl)
    assert r.estado == "falhou" and "Configuracoes > Agentes" in r.resumo
    ctl, _ = _ctl()
    r = _prov(tmp_path, PerfilTrabalho("liberado")).executar(_tarefa("alteracao_codigo"), {}, ctl)
    texto = r.artefatos[0].conteudo
    assert r.estado == "concluida" and "agente de DESENVOLVIMENTO" in texto and "somente leitura" not in texto


def test_prompt_leva_tags_e_observacoes_ao_agente_real(tmp_path):
    ctl, _ = _ctl()
    perfil = PerfilTrabalho("restrito", ("pesquisador",), "Prefira bibliotecas da stdlib.")
    texto = _prov(tmp_path, perfil).executar(_tarefa(), {}, ctl).artefatos[0].conteudo
    assert "Pesquisador:" in texto and "Prefira bibliotecas da stdlib." in texto


def test_perfil_quebrado_cai_no_restrito(tmp_path):
    def quebra():
        raise RuntimeError("preferencias indisponiveis")

    ctl, _ = _ctl()
    p = ProvedorKiroAcp(cmd("eco"), tmp_path / "ws", timeout_prompt=20, timeout_handshake=10, perfil_de=quebra)
    assert p.executar(_tarefa("alteracao_codigo"), {}, ctl).estado == "falhou"  # fail-closed


def test_retomada_curta_tambem_leva_o_perfil():
    t = {**_tarefa(), "perfil_texto": PerfilTrabalho(metodos=("testador",)).instrucoes(), "retomada": {"respostas": ["ok"]}}
    assert "Testes:" in montar_prompt(t)


# ------------------------------------------------------------------ preferencias / API
def test_preferencias_validam_e_compoem_o_perfil(client):
    e = client.get("/api/v1/preferencias").json()
    agentes = next(c for c in e["categorias"] if c["id"] == "agentes")
    ids = {i["id"]: i for i in agentes["itens"]}
    assert ids["nivel_autonomia"]["valor"] == "restrito" and ids["metodos_acao"]["detalhes"]
    r = client.put("/api/v1/preferencias", json={"expected_version": e["versao"], "valores": {"metodos_acao": ["direto", "pesquisador"]}})
    assert r.status_code == 422
    r = client.put("/api/v1/preferencias", json={"expected_version": e["versao"], "valores": {
        "nivel_autonomia": "liberado", "metodos_acao": ["cauteloso"], "observacoes_guia": "Use type hints."}})
    assert r.status_code == 200
    perfil = client.app.state.prefs.perfil_trabalho()
    assert perfil == PerfilTrabalho("liberado", ("cauteloso",), "Use type hints.")
    assert client.app.state.servico.perfil_de() == perfil
