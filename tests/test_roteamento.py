"""Roteamento adaptativo: simples = rapido e barato; complexa = plano (modelo mestre) + execucao; hierarquia de modelos."""

from __future__ import annotations

from pathlib import Path

import pytest

from forja.adapters.kiro_acp.provedor import ProvedorKiroAcp
from forja.agentes.estilo import PerfilTrabalho
from forja.orquestracao.configuracao_servico import ConfiguracaoServico
from forja.orquestracao.roteamento import classificar
from tests.test_acp import _ctl, cmd


def _t(titulo="Analisar", descricao="", modo="analise", criterios=None, **kw) -> dict:
    return {"id": "T", "titulo": titulo, "descricao": descricao, "modo": modo, "criterios_aceite": criterios or ["ok"], **kw}


@pytest.mark.parametrize("tarefa,nivel", [
    (_t("O que faz a funcao enfileirar?"), "simples"),
    (_t("Explique o README"), "simples"),
    (_t("Corrigir validacao do email", "o campo aceita espacos", modo="alteracao_codigo"), "normal"),
    (_t("Refatorar a arquitetura de autenticacao", "migrar sessoes para tokens e revisar seguranca", modo="alteracao_codigo",
        criterios=["a", "b", "c", "d"]), "complexa"),
    (_t("Planejar migracao do banco de dados", "x" * 700), "complexa"),
    (_t("Explique", politicas={"complexidade": "complexa"}), "complexa"),
    (_t("Refatorar tudo", modo="alteracao_codigo", politicas={"complexidade": "simples"}), "simples"),
])
def test_classificacao(tarefa, nivel):
    assert classificar(tarefa).nivel == nivel


def test_rotas_por_nivel():
    s = classificar(_t("O que faz a funcao x?"))
    assert (s.parte, s.planejar, s.fator_contexto, s.corrigir) == ("rapida", False, 0.5, False)
    c = classificar(_t("Refatorar arquitetura de seguranca e migrar o esquema", modo="alteracao_codigo", criterios=list("abcd")))
    assert (c.parte, c.planejar, c.fator_contexto, c.corrigir) == ("execucao", True, 1.5, True) and c.motivos
    assert classificar({**_t(), "entrada": {"revisao": True}}).parte == "revisao"
    assert classificar(_t(modo="estudo")).parte == "estudo"


# ------------------------------------------------------------------ provedor (Kiro fake) + configuracao real (padroes da Forja)
def _prov(tmp_path: Path, repo, relogio, cenario="planeja", nivel="liberado") -> ProvedorKiroAcp:
    c = ConfiguracaoServico(repo, relogio)
    p = ProvedorKiroAcp(cmd(cenario), tmp_path / "ws", timeout_prompt=20, timeout_handshake=10,
                        modelo_de=c.modelo_para, esforco_de=c.esforco_para, perfil_de=lambda: PerfilTrabalho(nivel=nivel, correcao="desligada"))
    p.alternativas_de = c.alternativas_para
    return p


def test_tarefa_simples_usa_o_modelo_rapido_em_um_turno(tmp_path, repo, relogio):
    ctl, eventos = _ctl()
    r = _prov(tmp_path, repo, relogio).executar(_t("O que faz a funcao enfileirar?"), {}, ctl)
    assert r.estado == "concluida" and r.consumo.chamadas_modelo == 1
    assert "direto (modelo=claude-haiku-5.5 esforco=medium" in r.artefatos[0].conteudo
    assert dict(eventos)["kiro.rota"]["nivel"] == "simples"


def test_tarefa_complexa_planeja_com_o_mestre_e_executa_com_o_executor(tmp_path, repo, relogio):
    ctl, eventos = _ctl()
    t = _t("Refatorar a arquitetura de autenticacao", "migrar sessoes e revisar seguranca", modo="alteracao_codigo", criterios=list("abcd"))
    r = _prov(tmp_path, repo, relogio).executar(t, {}, ctl)
    texto = r.artefatos[0].conteudo
    assert r.estado == "concluida" and r.consumo.chamadas_modelo == 2
    assert "## Plano" in texto and "(modelo=claude-opus-5.5 esforco=high)" in texto  # plano: mestre
    assert "executado conforme o plano (modelo=claude-sonnet-5.5 esforco=high)" in texto  # execucao: executor, esforco minimo alto
    assert any(m.tipo == "plano" for m in r.mensagens)
    configs = [d for t_, d in eventos if t_ == "kiro.configuracao"]
    assert [c["parte"] for c in configs] == ["planejamento", "execucao"]


def test_plano_com_decisao_para_antes_de_executar(tmp_path, repo, relogio):
    ctl, _ = _ctl()
    t = _t("Refatorar a arquitetura de autenticacao", "migrar e revisar seguranca", modo="alteracao_codigo", criterios=list("abcd"))
    r = _prov(tmp_path, repo, relogio, cenario="planeja_decisao").executar(t, {}, ctl)
    assert r.estado == "bloqueada" and r.consumo.chamadas_modelo == 1 and "executado" not in "".join(m.conteudo for m in r.mensagens)


def test_grafo_de_funcoes_entra_no_preparo_de_tarefa_com_pasta(tmp_path, repo, relogio):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "app.py").write_text("def somar(a: int, b: int) -> int:\n    return a + b\n\n\ndef total(xs):\n    return somar(xs[0], xs[1])\n",
                                 encoding="utf-8")
    ctl, eventos = _ctl()
    t = _t("Corrigir total", "o total ignora itens", modo="alteracao_codigo",
           projeto_ctx={"projeto": "P", "pastas": [{"caminho": str(proj), "papel": "trabalho"}], "anexos": []})
    r = _prov(tmp_path, repo, relogio, cenario="planeja_x").executar(t, {}, ctl)
    assert "grafo=True" in r.artefatos[0].conteudo
    assert dict(eventos)["kiro.grafo_funcoes"]["gerado"] is True


def test_benchmark_de_tarefas_tem_roteamento_esperado_e_projetos_validos():
    """O conjunto do item 0.6 e coerente: cada tarefa cai no nivel esperado e os projetos de codigo tem testes."""
    from forja.avaliacao.tarefas import carregar

    tarefas = carregar()
    assert len(tarefas) >= 10 and {t["nivel"] for t in tarefas} == {"simples", "normal", "complexa"}
    for t in tarefas:
        assert classificar({**t, "criterios_aceite": t["criterios"]}).nivel == t["nivel"], t["id"]
        if t["modo"] == "alteracao_codigo":
            assert any(k.startswith("tests/") for k in t["arquivos"]) and "testes passam" in t["criterios"]
