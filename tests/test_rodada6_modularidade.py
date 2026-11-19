"""Rodada 6 (ADR-028): acesso livre dos agentes ao segundo cerebro, saude/modularidade do grafo, repeticoes entre notas e
"organizar e deduplicar" (plano da IA -> fila de revisao -> aplicar). Dados sinteticos."""

from __future__ import annotations

import json

from forja.adapters.sqlite import tabelas as T
from forja.memoria.contratos import MemoriaIn
from forja.memoria.modelo import Principal
from forja.orquestracao.modularidade import REGRAS_NOTA, avaliar_nota, palavras, remover_trecho
from forja.orquestracao.organizacao import termos
from forja.preferencias.registro import POR_ID

M = "/api/v1/memorias"
P = Principal("teste", frozenset({"publico", "pessoal"}))
REGRA = "O sistema Funcao exige que automacoes sejam feitas por chamadas HTTP autenticadas em vez de navegacao pela tela."


def _nota(app, titulo: str, conteudo: str, ns: str = "pessoal/projetos/loja", tags=("projeto-loja",)) -> dict:
    return app.state.memoria.criar(P, MemoriaIn(tipo="procedimental", titulo=titulo, resumo=titulo, conteudo=conteudo, namespace=ns,
                                                tags=list(tags)), "teste")


def _automacoes(app) -> list[dict]:
    notas = []
    for i, alvo in enumerate(("pedidos", "estoque", "faturamento")):
        notas.append(_nota(app, f"Automacao de {alvo} no Funcao", f"# Automacao {alvo}\n\nPassos especificos de {alvo} numero {i}: "
                           f"exportar a planilha e conferir os totais.\n\n- {REGRA}\n- Rodar toda segunda-feira as 8h.",
                           tags=("sistema-funcao", "automacao")))
    return notas


# ------------------------------------------------------------------ acesso dos agentes
def test_agentes_tem_acesso_livre_ao_segundo_cerebro(client):
    _nota(client.app, "Decisao de cache no projeto loja", "Usar cache de 5 minutos nas consultas de catalogo da loja virtual.")
    so_publico = client.get(f"{M}/buscar", params={"q": "cache catalogo loja"}).json()["resultados"]
    todos = client.get(f"{M}/buscar", params={"q": "cache catalogo loja", "todos": True}).json()["resultados"]
    assert not [r for r in so_publico if r.get("namespace", "").startswith("pessoal")]
    assert any(r.get("titulo") == "Decisao de cache no projeto loja" for r in todos)  # o MCP dos agentes usa todos=true
    assert POR_ID["kiro_mcp_ativo"].padrao is True and POR_ID["contexto_memoria_ampla"].padrao is True
    assert client.app.state.servico.provedor is not None


def test_contexto_inicial_ve_todas_as_notas_permitidas(client):
    n = _nota(client.app, "Relatorios mensais: armadilha do fuso horario",
              "Relatorios mensais quebram no fuso horario de verao. Gere os relatorios mensais em UTC e converta o fuso horario so na tela.",
              ns="pessoal/estudos", tags=("relatorios", "fuso-horario", "armadilha"))
    with client.app.state.servico.repo.escrita() as t:  # revisada pelo usuario (candidatas so entram com casamento forte)
        t.atualizar(T.Memoria, n["id"], estado="validado")
    ctx = client.app.state.servico.construtor_contexto
    assert ctx.namespaces_da_tarefa is not None, "preferencia contexto_memoria_ampla nao aplicada"
    tarefa = {"id": "T-x", "projeto_id": "", "titulo": "Relatorios mensais com fuso horario", "descricao": "", "politicas": {}}
    assert "pessoal" in ctx.namespaces_da_tarefa(tarefa)
    assert any("fuso horario" in i.texto for i in ctx.construir(tarefa).itens)
    ctx.namespaces_da_tarefa = None  # preferencia desligada: so as publicas
    assert not any("fuso horario" in i.texto for i in ctx.construir(tarefa).itens)


# ------------------------------------------------------------------ qualidade de uma nota
def test_avaliar_nota_aponta_tamanho_ligacoes_tags_e_titulo():
    assert avaliar_nota("Sistema Funcao: automacoes por HTTP", "palavra " * 120, ["sistema-funcao", "procedimento"]) == []
    longa = avaliar_nota("Tudo", "palavra " * 900, [])
    assert any("longa" in a for a in longa) and any("tags" in a for a in longa) and any("titulo" in a for a in longa)
    assert any("curta" in a for a in avaliar_nota("Nota curtinha sobre X", "so isso", ["x"]))
    assert avaliar_nota("Nota curtinha sobre X", "veja [[Outra nota]]", ["x"]) == []  # curta mas ligada: ok
    assert "UM assunto por nota" in REGRAS_NOTA


def test_rota_avaliar(client):
    r = client.post(f"{M}/avaliar", json={"titulo": "x", "conteudo": "a b c", "tags": []}).json()
    assert len(r["avisos"]) == 3


# ------------------------------------------------------------------ saude e repeticoes
def test_saude_mede_modularidade_e_acha_trecho_repetido(client):
    app = client.app
    notas = _automacoes(app)
    _nota(app, "Nota enorme sobre tudo do projeto", "texto " * 800, tags=())
    _nota(app, "Nota com link quebrado", "Detalhes em [[Nota que nao existe]] e mais alguns detalhes do projeto loja.")
    s = client.get(f"{M}/saude", params={"namespace": "pessoal"}).json()
    assert s["notas"] == 5 and s["pontuacao"] < 100 and s["contagem"]["longas"] == 1 and s["contagem"]["links_fantasmas"] == 1
    assert s["contagem"]["sem_tags"] == 1 and s["contagem"]["orfas"] >= 4
    rep = s["repeticoes"][0]
    assert set(rep["notas"]) == {n["id"] for n in notas} and "HTTP" in rep["trecho"] and rep["entidade"] == "sistema-funcao"
    assert rep["economia_caracteres"] > 100 and s["percentual_repetido"] > 0
    base = client.get(f"{M}/saude", params={"namespace": "publico", "base": True}).json()
    assert base["notas"] > 0  # a base curada tambem pode ser auditada (somente leitura)


def test_remover_trecho_preserva_a_estrutura_markdown():
    texto = f"# Titulo\n\nFrase propria que fica.\n\n## Regra\n\n- {REGRA}\n- Outro item que fica.\n\n## Vazia\n\n{REGRA}\n"
    novo = remover_trecho(texto, [frozenset(termos(REGRA))])
    assert "HTTP" not in novo and "# Titulo" in novo and "- Outro item que fica." in novo and "Frase propria" in novo
    assert "## Vazia" not in novo  # secao que so tinha o trecho repetido sai


# ------------------------------------------------------------------ organizar com IA: plano -> revisao -> aplicar
def _plano(notas: list[dict], extra: dict | None = None) -> str:
    plano = {"modulos": [{"titulo": "Sistema Funcao: automacoes por HTTP", "entidade": "Sistema Funcao", "tags": ["sistema-funcao", "regra"],
                          "conteudo": f"{REGRA} Navegar pela tela quebra com mudancas de layout e nao tem trilha de auditoria.",
                          "trecho_repetido": REGRA, "notas": [n["id"] for n in notas] + ["MEM-inexistente"]}],
             "ligacoes": [{"origem": notas[0]["id"], "destino": notas[1]["id"], "tipo": "RELACIONADO_A", "motivo": "mesmo sistema"},
                          {"origem": notas[0]["id"], "destino": notas[1]["id"], "tipo": "INVENTADO"}],
             "tags": [{"nota": notas[2]["id"], "tags": ["Faturamento", "rotina semanal"]}], **(extra or {})}
    return "Plano:\n```json\n" + json.dumps(plano) + "\n```"


def test_plano_da_ia_vira_sugestoes_e_modulo_tira_a_repeticao(client):
    app = client.app
    notas = _automacoes(app)
    with app.state.servico.repo.escrita() as t:  # nota validada nao e editada: so ligada ao modulo
        t.atualizar(T.Memoria, notas[2]["id"], estado="validado")
    r = app.state.modularidade.importar_plano(P, "T-plano", _plano(notas))
    assert r["novas"] == {"modularizar": 1, "ligacao": 1, "tags": 1}
    assert app.state.modularidade.importar_plano(P, "T-plano", _plano(notas))["total"] == 0  # idempotente
    fila = client.get(f"{M}/revisao", params={"limite": 100}).json()["sugestoes"]
    mod = next(s for s in fila if s["tipo"] == "modularizar")
    assert set(mod["memorias"]) == {n["id"] for n in notas} and mod["dados"]["entidade"] == "Sistema Funcao"
    antes = sum(len(n["conteudo"]) for n in notas[:2])
    res = client.post(f"{M}/sugestoes/{mod['id']}/decidir", json={"aceitar": True}).json()["resultado"]
    assert res["editadas"] == 2 and res["ligadas"] == 1 and res["caracteres_economizados"] > 0
    modulo = client.get(f"{M}/{res['modulo']}").json()
    assert "modulo" in modulo["tags"] and "HTTP" in modulo["conteudo"]
    for n in notas[:2]:
        novo = client.get(f"{M}/{n['id']}").json()["conteudo"]
        assert REGRA not in novo and "[[Sistema Funcao: automacoes por HTTP]]" in novo and "Rodar toda segunda-feira" in novo
    assert sum(len(client.get(f"{M}/{n['id']}").json()["conteudo"]) for n in notas[:2]) < antes
    assert REGRA in client.get(f"{M}/{notas[2]['id']}").json()["conteudo"]  # validada intacta
    links_mod = client.get(f"{M}/{res['modulo']}/links").json()
    assert any(x["tipo"] == "SUBTOPICO_DE" and x["titulo"] == "Sistema Funcao" for x in links_mod["saida"])  # entidade acha o modulo
    assert any(x["tipo"] == "BASEADO_EM" and x["id"] == notas[2]["id"] for x in links_mod["entrada"])
    busca = client.get(f"{M}/buscar", params={"q": "sistema Funcao automacoes HTTP", "todos": True}).json()["resultados"]
    assert res["modulo"] in [b["id"] for b in busca[:3]]  # pesquisar o sistema acha o modulo
    tags = next(s for s in client.get(f"{M}/revisao").json()["sugestoes"] if s["tipo"] == "tags")
    client.post(f"{M}/sugestoes/{tags['id']}/decidir", json={"aceitar": True})
    assert {"faturamento", "rotina-semanal"} <= set(client.get(f"{M}/{notas[2]['id']}").json()["tags"])


def test_dividir_nota_longa_em_subtopicos(client):
    app = client.app
    longa = _nota(app, "Guia completo do deploy", "palavra " * 700)
    plano = {"dividir": [{"nota": longa["id"], "partes": [{"titulo": "Deploy: preparar o ambiente", "conteudo": "Instalar dependencias e variaveis."},
                                                           {"titulo": "Deploy: publicar e conferir", "conteudo": "Publicar e conferir a saude."}]}]}
    app.state.modularidade.importar_plano(P, "T-div", "```json\n" + json.dumps(plano) + "\n```")
    s = next(x for x in client.get(f"{M}/revisao").json()["sugestoes"] if x["tipo"] == "dividir")
    r = client.post(f"{M}/sugestoes/{s['id']}/decidir", json={"aceitar": True}).json()["resultado"]
    assert len(r["partes"]) == 2
    indice = client.get(f"{M}/{longa['id']}").json()
    assert "[[Deploy: preparar o ambiente]]" in indice["conteudo"] and palavras(indice["conteudo"]) < 60


def test_pedido_de_organizacao_cria_tarefa_e_plano_entra_sozinho_ao_concluir(client):
    app = client.app
    notas = _automacoes(app)
    r = client.post(f"{M}/organizar-ia", json={"namespaces": ["pessoal"], "foco": "sistema Funcao", "executar": False}).json()
    t = app.state.servico.obter(T.Tarefa, r["tarefa_id"])
    assert t["modo"] == "analise" and "Trechos REPETIDOS" in t["descricao"] and notas[0]["id"] in t["descricao"] and "UM assunto" in t["descricao"]

    class _Res:
        estado = "concluida"
        artefatos = [type("A", (), {"conteudo": _plano(notas)})()]
        mensagens: list = []

    with app.state.servico.repo.escrita() as tx:
        ex = tx.inserir(T.Execucao, id="EX-org", tarefa_id=t["id"], estado="concluida", agente_id="mock", tentativa=0, checkpoint={},
                        resultado=None, deadline=None, iniciado_em=None, finalizado_em=None, correlation_id="c", criado_em="2026-11-19T00:00:00Z")
    app.state.modularidade.ao_finalizar(ex["id"], _Res())
    assert any(s["tipo"] == "modularizar" for s in client.get(f"{M}/revisao").json()["sugestoes"])
    assert client.post(f"{M}/organizar-ia", json={"namespaces": ["publico"], "executar": False}).status_code in (200, 422)
