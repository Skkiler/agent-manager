"""Parser do briefing: secoes de conversa, decisoes agrupadas com recomendacao, degradacao graciosa."""

from __future__ import annotations

import pytest

from forja.conversa.briefing import parse, resumo_para_retomada

COMPLETO = """## Entendimento
Voce quer saber como organizar o modulo de autenticacao do RPA.

## Resposta
Separe cliente HTTP, servico e rotas (ver [M1]). O login fica no servico.

## Premissas
- Python 3.12; sem framework novo.

## Decisões para você
1. Usar token Bearer ou sessão por cookie? — Recomendo: Bearer (mais simples de testar). Alternativas: cookie de sessão; OAuth.
2. Onde guardar o segredo? Recomendo: variável de ambiente.
3. Publicar a API agora?

## Próximos passos
- Criar o servico
- Escrever testes
"""


def test_briefing_completo_vira_secoes_e_decisoes_agrupadas():
    b = parse(COMPLETO)
    assert b.estruturado and set(b.secoes) == {"entendimento", "resposta", "premissas", "decisoes", "proximos_passos"}
    assert len(b.decisoes) == 3 and b.precisa_do_usuario
    d1, d2, d3 = b.decisoes
    assert d1.pergunta == "Usar token Bearer ou sessão por cookie?"
    assert d1.recomendacao == "Bearer (mais simples de testar)"
    assert d1.alternativas == ["cookie de sessão", "OAuth"]
    assert d2.recomendacao == "variável de ambiente" and d2.alternativas == []
    assert d3.pergunta == "Publicar a API agora?" and d3.recomendacao == ""


@pytest.mark.parametrize("texto", [
    "## Entendimento\nok\n## Resposta\nfeito\n## Decisões para você\nNenhuma decisão necessária.",
    "## Resposta\nfeito\n## Decisoes\nNão há decisões pendentes.",
    "## Resposta\nfeito\n## Decisões\n- Nenhuma",
    "## Resposta\nfeito\n## Decisões\nsem decisões",
])
def test_nenhuma_decisao_nao_vira_pergunta(texto):
    b = parse(texto)
    assert b.decisoes == [] and not b.precisa_do_usuario and "decisoes" not in b.secoes


def test_titulos_com_e_sem_acento_e_sinonimos():
    b = parse("# ENTENDIMENTO\na\n### Próximos Passos\nb\n## Analise\nc\n## Suposições\nd")
    assert set(b.secoes) == {"entendimento", "proximos_passos", "resposta", "premissas"}


def test_modelo_que_ignora_o_formato_nao_perde_conteudo():
    b = parse("Aqui esta a resposta direta, sem secoes.\nSegunda linha.")
    assert not b.estruturado and b.secoes == {"resposta": "Aqui esta a resposta direta, sem secoes.\nSegunda linha."}
    assert not b.precisa_do_usuario
    assert parse("   ").secoes == {} and parse("").decisoes == []


def test_titulo_dentro_de_bloco_de_codigo_nao_cria_secao():
    b = parse("## Resposta\nExemplo:\n```\n## Decisões\n1. falso\n```\nfim")
    assert b.decisoes == [] and "falso" in b.secoes["resposta"]


def test_decisao_em_varias_linhas_e_continuada():
    b = parse("## Decisões para você\n1. Qual banco usar?\n   Recomendo: SQLite (local-first). Alternativas: Postgres\n2. Outra?")
    assert len(b.decisoes) == 2 and b.decisoes[0].recomendacao == "SQLite (local-first)"
    assert b.decisoes[0].alternativas == ["Postgres"]


def test_resumo_para_retomada_e_curto_e_prefere_entendimento():
    b = parse(COMPLETO)
    assert resumo_para_retomada(b).startswith("Voce quer saber")
    longo = parse("## Entendimento\n" + "palavra " * 500)
    r = resumo_para_retomada(longo, limite=100)
    assert len(r) <= 100 and r.endswith("…")
    assert resumo_para_retomada(parse("")) == ""


def test_texto_hostil_nao_quebra_o_parser():
    for lixo in ("#" * 5000, "## Decisões\n" + "- " * 3000, "\x00\x01\x02", "## Decisões\n1." * 200):
        parse(lixo)
