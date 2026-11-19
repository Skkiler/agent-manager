"""Rodada 3 da avaliacao (ADR-025): Codex no nivel do Kiro (instrucoes + ambiente), MCP da Forja no Codex, privacidade do Kiro,
coordenacao (consulta filtrada, trava, bloqueada antiga), laco A/B, roteamento e melhorias das ferramentas."""

from __future__ import annotations

import dataclasses
import json
import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest

from forja.adapters.codex_acp.provedor import ENV_EXCLUIR, REGRA_PASTAS, ProvedorCodexAcp, configuracao_sessao
from forja.adapters.kiro_acp import perfil_kiro
from forja.adapters.kiro_acp.provedor import ProvedorKiroAcp
from forja.adapters.sqlite import tabelas as T
from forja.dominio.tempo import iso
from forja.ferramentas import estrutura as E
from forja.ferramentas.amostra import amostra_arquivo
from forja.ferramentas.catalogo import Catalogo, FerramentaFalhou
from forja.ferramentas.outline import outline_arquivo
from forja.orquestracao.coordenacao import CoordenacaoServico
from forja.orquestracao.roteamento import classificar
from forja.seguranca.acoes import _ferramenta_forja
from forja.seguranca.sensiveis import GLOBS
from tests.test_acp import _ctl, _tarefa, cmd


# ------------------------------------------------------------------ Codex: regras como instrucao de desenvolvedor
def test_configuracao_do_codex_leva_regras_e_ambiente_minimo():
    c = configuracao_sessao()
    instr = c["developer_instructions"]
    assert perfil_kiro.ESCOPO in instr and REGRA_PASTAS in instr and "NAO tente contornar" in instr
    assert c["shell_environment_policy"] == {"inherit": "core", "exclude": ENV_EXCLUIR}
    assert {"FORJA_*", "APP_*", "*TOKEN*", "*SECRET*"} <= set(ENV_EXCLUIR)
    assert "approval_policy" not in c  # recusado pelo codex-acp 2.7.0 (ADR-025)
    # perfil de permissao nativo (ADR-026): estende ':workspace', nega todos os globs de segredo e as pastas de credenciais
    assert c["default_permissions"] == "forja"
    perfil = c["permissions"]["forja"]
    assert perfil["extends"] == ":workspace"
    fs = perfil["filesystem"]
    assert fs[":workspace_roots"] == {g: "deny" for g in GLOBS} and "**/.env" in fs[":workspace_roots"]
    assert fs["~/.ssh"] == "deny" and fs["~/.aws"] == "deny"
    assert ":root" not in fs and "~" not in fs  # ':root' deny derruba a sessao; '~' deny trava o session/new (sondado)


def test_processo_do_codex_recebe_config_e_ambiente_limpo(monkeypatch, tmp_path):
    monkeypatch.setenv("FORJA_INT_GITHUB_TOKEN", "x")
    env = ProvedorCodexAcp(None, tmp_path)._ambiente_processo()
    assert env is not None and "FORJA_INT_GITHUB_TOKEN" not in env
    assert json.loads(env["CODEX_CONFIG"]) == configuracao_sessao()


@pytest.mark.parametrize(("titulo", "esperado"), [("@forja/forja_buscar_memoria", "forja_buscar_memoria"),
                                                  ("mcp.forja.forja_buscar_memoria", "forja_buscar_memoria"),
                                                  ("mcp__forja__forja_buscar_memoria", "forja_buscar_memoria"),
                                                  ("mcp.forja.nao_existe", None), ("mcp.outro.forja_buscar_memoria", None)])
def test_titulo_das_ferramentas_mcp_da_forja_no_kiro_e_no_codex(titulo, esperado):
    assert _ferramenta_forja({"title": titulo}) == esperado


# ------------------------------------------------------------------ Kiro: coleta de conteudo desligada
class _ClienteFalso:
    def __init__(self, opcoes, falhar=False):
        self.opcoes_sessao = opcoes
        self.definidas: list = []
        self.falhar = falhar

    def definir_opcao(self, sid, opcao, valor, timeout):
        from forja.adapters.kiro_acp.cliente import AcpErro
        if self.falhar:
            raise AcpErro("Internal error", -32603)
        self.definidas.append((opcao, valor))


def test_privacidade_desliga_coleta_quando_oferecida(tmp_path):
    ctl, eventos = _ctl()
    cli = _ClienteFalso([{"id": "contentCollection", "options": [{"value": "enabled"}, {"value": "disabled"}]}])
    ProvedorKiroAcp(None, tmp_path)._privacidade(cli, "s1", ctl)
    assert cli.definidas == [("contentCollection", "disabled")]
    assert ("kiro.privacidade", {"coleta_de_conteudo": "desligada"}) in eventos


def test_privacidade_sem_opcao_ou_com_erro_segue(tmp_path):
    ctl, eventos = _ctl()
    sem = _ClienteFalso([{"id": "model", "options": [{"value": "x"}]}])
    ProvedorKiroAcp(None, tmp_path)._privacidade(sem, "s1", ctl)
    assert sem.definidas == [] and not eventos
    erro = _ClienteFalso([{"id": "contentCollection", "options": [{"value": "disabled"}]}], falhar=True)
    ProvedorKiroAcp(None, tmp_path)._privacidade(erro, "s1", ctl)
    assert eventos[-1][1]["coleta_de_conteudo"] == "nao_alterada"


# ------------------------------------------------------------------ laco A/B
def test_duas_chamadas_se_alternando_sao_laco(tmp_path):
    ctl, _ = _ctl()
    r = ProvedorKiroAcp(cmd("alterna"), tmp_path / "ws", timeout_prompt=30, timeout_handshake=10).executar(_tarefa(), {}, ctl)
    assert r.estado == "bloqueada" and r.pendencias[0].startswith("laco_detectado: duas chamadas")


# ------------------------------------------------------------------ roteamento
def _t(titulo, modo="analise", **kw):
    return {"titulo": titulo, "descricao": "", "modo": modo, "criterios_aceite": kw.get("criterios", [])}


def test_pedido_amplo_de_leitura_continua_simples():
    assert classificar(_t("Liste todos os arquivos de teste")).nivel == "simples"


def test_mudanca_minima_de_codigo_pode_ser_simples():
    assert classificar(_t("Corrija o typo na docstring de soma", "alteracao_codigo")).nivel == "simples"
    assert classificar(_t("Renomeie a variavel x para total", "alteracao_codigo")).nivel == "simples"
    assert classificar(_t("Adicione validacao de entrada", "alteracao_codigo")).nivel == "normal"


def test_migracao_e_complexa():
    r = classificar(_t("Migre o banco de dados e refatore a camada de autenticacao", "alteracao_codigo"))
    assert r.nivel == "complexa" and any("migre" in m for m in r.motivos)


# ------------------------------------------------------------------ ferramentas
def test_amostra_com_busca_abre_a_janela_na_ocorrencia(tmp_path: Path):
    (tmp_path / "t.txt").write_text("\n".join(f"linha {i}" for i in range(1, 201)) + "\nALVO aqui\n", encoding="utf-8")
    r = amostra_arquivo(tmp_path, "t.txt", linhas=10, buscar="alvo")
    assert "201: ALVO aqui" in r.resumo and "1: linha 1\n" not in r.resumo
    nada = amostra_arquivo(tmp_path, "t.txt", buscar="inexistente")
    assert "nao encontrado" in nada.resumo


def test_outline_de_css(tmp_path: Path):
    (tmp_path / "a.css").write_text(":root { --c: #000; }\n.botao,\n.link { color: red; }\n@media (max-width: 600px) {\n"
                                    "  .botao { display: none; }\n}\n@keyframes giro { from { opacity: 0; } }\n", encoding="utf-8")
    r = outline_arquivo(tmp_path, "a.css")
    tipos = {(s["tipo"], s["linha"]) for s in r.dados["simbolos"]}
    assert ("regra", 1) in tipos and ("media", 4) in tipos and ("keyframes", 7) in tipos and r.dados["linguagem"] == "css"


def test_fim_das_funcoes_js_pelas_chaves(tmp_path: Path):
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "m.js").write_text(
        "function a(x) {\n  const s = '}';\n  if (x) {\n    return 1;\n  }\n  return 2;\n}\n\nconst b = () => 3;\n", encoding="utf-8")
    E.limpar_cache()
    a = E.estrutura_codigo(tmp_path, ".", "definicao", "a").dados["definicoes"][0]
    assert a["linha"] == 1 and a["fim"] == 7  # a chave dentro da string nao fecha a funcao
    b = E.estrutura_codigo(tmp_path, ".", "definicao", "b").dados["definicoes"][0]
    assert b["fim"] == b["linha"] == 9


def test_ferramenta_lenta_estoura_o_tempo(tmp_path: Path, monkeypatch):
    (tmp_path / "x.txt").write_text("oi\n", encoding="utf-8")
    c = Catalogo((tmp_path,))
    c.tempo_maximo_s = 0.2
    f = c.ferramentas["texto.amostra"]

    def lenta(e, ctx):
        time.sleep(1.0)
        return f.rodar(e, ctx)

    monkeypatch.setitem(c.ferramentas, "texto.amostra", dataclasses.replace(f, rodar=lenta))
    t0 = time.monotonic()
    with pytest.raises(FerramentaFalhou, match="tempo maximo"):
        c.executar("texto.amostra", {"caminho": "x.txt"})
    assert time.monotonic() - t0 < 0.9


# ------------------------------------------------------------------ coordenacao
def _inserir_tarefa(t, id_, entrada, estado="pronta", atualizado="2026-01-01T00:00:00.000+00:00"):
    t.inserir(T.Tarefa, id=id_, objetivo_id="O1", projeto_id="P1", titulo="t", descricao="", criterios_aceite=["x"], dependencias=[],
              especialidade="g", modo="analise", recursos={}, orcamento={}, politicas={}, entrada=entrada, contexto_refs=[],
              estado=estado, versao_estado=1, tentativas=0, motivo_estado="", correlation_id="c", criado_em="2026",
              atualizado_em=atualizado)


def test_tarefas_por_entrada_filtra_no_banco(repo):
    with repo.escrita() as t:
        t.inserir(T.Projeto, id="P1", nome="p1", descricao="", estado="ativo", criado_em="2026")
        t.inserir(T.Objetivo, id="O1", projeto_id="P1", titulo="o", descricao="", prioridade=3, criterios_sucesso=[], orcamento={},
                  criado_em="2026")
        _inserir_tarefa(t, "T1", {"coordenador": "C1"})
        _inserir_tarefa(t, "T2", {"coordenador": "C2"})
        _inserir_tarefa(t, "T3", {"outro": "C1"})
    with repo.leitura() as t:
        assert [x["id"] for x in t.tarefas_por_entrada("coordenador", "C1")] == ["T1"]
        assert t.tarefas_por_entrada("coordenador", "C9") == []


def test_bloqueada_antiga_nao_segura_o_lote(servico, relogio):
    c = CoordenacaoServico(servico, relogio=relogio)
    agora = relogio.agora()
    recente = {"estado": "bloqueada", "atualizado_em": iso(agora - timedelta(hours=1))}
    antiga = {"estado": "bloqueada", "atualizado_em": iso(agora - timedelta(hours=c.PRAZO_BLOQUEADA_H + 1))}
    assert c._parada({"estado": "concluida"}) and c._parada(antiga) and not c._parada(recente)
    assert not c._parada({"estado": "executando", "atualizado_em": antiga["atualizado_em"]})


def test_consolidacao_tem_trava_unica(servico, relogio, monkeypatch):
    c = CoordenacaoServico(servico, relogio=relogio)
    dentro, maximo = [0], [0]

    def fake(_c):
        dentro[0] += 1
        maximo[0] = max(maximo[0], dentro[0])
        time.sleep(0.05)
        dentro[0] -= 1

    monkeypatch.setattr(c, "_talvez_consolidar_travado", fake)
    ths = [threading.Thread(target=c._talvez_consolidar, args=({},)) for _ in range(4)]
    for th in ths:
        th.start()
    for th in ths:
        th.join()
    assert maximo[0] == 1
