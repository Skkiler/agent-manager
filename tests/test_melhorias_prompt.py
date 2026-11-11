"""Melhorias da pesquisa: prefixo de prompt fixo (cache), secao Evidencias, citacao web, subagente e contexto por referencia."""

from __future__ import annotations

from pathlib import Path

import pytest

from forja.adapters.kiro_acp.provedor import PROTOCOLO, bloco_projeto, montar_prompt
from forja.adapters.sqlite.repositorio import RepositorioSqlite
from forja.contexto.construtor import ConstrutorContexto
from forja.conversa.briefing import parse
from forja.mcp.servidor import compactar_busca, compactar_ferramenta
from forja.memoria.contratos import IngerirIn
from forja.memoria.modelo import Principal
from forja.orquestracao.memoria_servico import ServicoMemoria

P = Principal("t", frozenset({"publico"}))


def _t(**kw) -> dict:
    return {"id": "T", "titulo": "Analisar fila", "descricao": "d", "criterios_aceite": ["a"], "modo": "analise", **kw}


def test_prefixo_do_prompt_e_identico_entre_usuarios_e_tarefas():
    a = montar_prompt(_t(perfil_texto="\nModo de trabalho:\n- Direto\n"))
    b = montar_prompt(_t(titulo="Outra coisa", perfil_texto="\nModo de trabalho:\n- Pesquisador\n"))
    corte = a.index("Tarefa:")
    assert a[:corte] == b[:corte] == PROTOCOLO + "\n\n"  # tudo que varia vem DEPOIS do protocolo
    assert "Direto" in a[corte:] and "Pesquisador" in b[corte:]


def test_protocolo_pede_evidencias_e_fonte_da_web():
    assert "## Evidências" in PROTOCOLO and "nunca diga que testes passaram sem roda-los" in PROTOCOLO
    assert "endereco da fonte" in PROTOCOLO


def test_secao_evidencias_e_reconhecida():
    b = parse("## Resposta\nfeito\n## Evidências\n- rodei pytest: 3 passed\n")
    assert b.secoes["evidencias"].startswith("- rodei pytest")


def test_muitas_pastas_sugerem_subagente_de_busca():
    pastas = [{"caminho": f"C:/p{i}", "papel": "consulta"} for i in range(3)]
    assert "subagente" in bloco_projeto({"projeto_ctx": {"projeto": "x", "pastas": pastas}})
    assert "subagente" not in bloco_projeto({"projeto_ctx": {"projeto": "x", "pastas": pastas[:2]}})


@pytest.fixture
def construtor(repo: RepositorioSqlite, tmp_path: Path) -> ConstrutorContexto:
    raiz = tmp_path / "repos" / "r"
    raiz.mkdir(parents=True)
    (raiz / "fila.py").write_text("def enfileirar_prioridade(item):\n" + "    # detalhe longo\n" * 40 + "    return item\n",
                                  encoding="utf-8")
    mem = ServicoMemoria(repo, raizes_ingestao=[tmp_path / "repos"])
    mem.ingerir_diretorio(P, IngerirIn(raiz=str(raiz), namespace="publico", repositorio="r"))
    return ConstrutorContexto(mem, P, ["publico"])


def test_contexto_por_referencia_com_mcp_e_bem_menor(construtor):
    t = {"titulo": "enfileirar prioridade", "descricao": "", "criterios_aceite": ["ok"], "politicas": {}, "contexto_refs": []}
    cheio = construtor.construir(t)
    construtor.referencias = True
    ref = construtor.construir(t)
    assert cheio.itens and ref.itens and "fila.py:" in ref.texto and "Referencias:" in ref.texto
    assert sum(i.tokens for i in ref.itens) < 0.6 * sum(i.tokens for i in cheio.itens)  # cada item vira local + 1 linha
    assert "detalhe longo\n    # detalhe longo" not in ref.texto


def test_mcp_devolve_busca_compacta_e_paginada():
    r = {"resultados": [{"origem": "codigo", "caminho": "a.py", "linhas": [1, 9], "trecho": "x" * 900, "namespace": "publico",
                         "sha256": "h", "suspeita_injecao": [], "definicao": {"nome": "f"}} for _ in range(5)], "avisos": []}
    p1 = compactar_busca(r, 2, 1)
    assert len(p1["resultados"]) == 2 and p1["ha_mais"] and "sha256" not in str(p1) and len(p1["resultados"][0]["trecho"]) == 400
    assert compactar_busca(r, 2, 3)["ha_mais"] is False


def test_mcp_omite_dados_grandes_de_ferramenta():
    grande = compactar_ferramenta({"ferramenta": "x", "resumo": "ok", "dados": {"lista": ["y" * 100] * 100}, "avisos": []})
    assert "dados" not in grande and "dados_omitidos" in grande and grande["resumo"] == "ok"
    assert compactar_ferramenta({"ferramenta": "x", "resumo": "ok", "dados": {"n": 1}})["dados"] == {"n": 1}
