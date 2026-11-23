"""Rodada 7 (ADR-029): pastas do segundo cerebro (criar, mover, renomear, propostas dos agentes), busca padrao em todo o
segundo cerebro, notas de estudo por escopo (projeto/entidade/generico) e alimentacao em lote de uma pasta de projetos.
Dados sinteticos."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from forja.adapters.sqlite import tabelas as T
from forja.dominio.erros import Conflito, ValidacaoDominio
from forja.memoria.contratos import MemoriaIn
from forja.memoria.modelo import AcessoNegado, Principal, validar_namespace
from forja.orquestracao.alimentacao import LoteIn, nome_projeto, slug
from forja.orquestracao.estudos import extrair_notas

M = "/api/v1/memorias"
P = Principal("teste", frozenset({"publico", "pessoal"}))


def _nota(app, titulo: str, conteudo: str, ns: str) -> dict:
    return app.state.memoria.criar(P, MemoriaIn(tipo="semantica", titulo=titulo, resumo=titulo, conteudo=conteudo, namespace=ns), "teste")


def _prefs(client, **valores):
    v = client.get("/api/v1/preferencias").json()["versao"]
    r = client.put("/api/v1/preferencias", json={"expected_version": v, "valores": valores})
    assert r.status_code == 200, r.text


# ------------------------------------------------------------------ pastas
def test_namespace_aceita_pastas_mais_fundas():
    assert validar_namespace("pessoal/empresa/trabalho/projetos/gateway/front-v2")
    with pytest.raises(ValidacaoDominio):
        validar_namespace("pessoal/a/b/c/d/e/f/g")


def test_criar_mover_e_arvore_de_pastas(client):
    app = client.app
    a = _nota(app, "Fila de cobranca: reprocessamento", "Reprocessar a fila de cobranca a cada hora com backoff.", "pessoal/estudos")
    b = _nota(app, "Outra nota solta", "Texto qualquer sobre relatorios semanais da equipe.", "pessoal/estudos")
    r = client.post(f"{M}/pastas", json={"namespace": "pessoal/empresa/acme/projetos", "descricao": "automacoes da acme"})
    assert r.status_code == 201, r.text
    ligacao = app.state.grafo.ligar(P, a["id"], b["id"], "RELACIONADO_A")
    r = client.post(f"{M}/pastas/mover", json={"ids": [a["id"], "MEM-nao-existe"], "destino": "pessoal/empresa/acme/projetos/cobranca"}).json()
    assert r["movidas"] == 1 and r["puladas"][0]["motivo"] == "nao encontrada"
    movida = client.get(f"{M}/{a['id']}").json()
    assert movida["namespace"] == "pessoal/empresa/acme/projetos/cobranca" and movida["sensibilidade"] == "pessoal" and movida["versao"] == 2
    achou = client.get(f"{M}/buscar", params={"q": "reprocessar fila cobranca", "namespace": "pessoal/empresa"}).json()["resultados"]
    assert a["id"] in [x["id"] for x in achou]  # busca reindexada no novo lugar
    with app.state.servico.repo.leitura() as t:
        assert t.obter(T.LigacaoGrafo, ligacao["id"])["namespace"] == "pessoal/empresa/acme/projetos/cobranca"
        assert any(v["motivo"].startswith("movida de pessoal/estudos") for v in t.listar(T.MemoriaVersao, memoria_id=a["id"], limite=5))
    arvore = {x["namespace"]: x for x in client.get(f"{M}/pastas").json()["pastas"]}
    assert arvore["pessoal/empresa/acme/projetos"]["declarada"] and arvore["pessoal/empresa/acme/projetos"]["total"] == 1
    assert arvore["pessoal"]["somente_leitura"] and arvore["pessoal"]["total"] >= 2
    assert client.delete(f"{M}/pastas", params={"namespace": "pessoal/empresa/acme/projetos"}).status_code == 409  # tem nota dentro


def test_renomear_pasta_migra_notas_subpastas_e_indice_de_codigo(client, tmp_path):
    app = client.app
    raiz = tmp_path / "codigo"
    raiz.mkdir()
    (raiz / "robo.py").write_text("def consultar_margem(cpf_hash):\n    return 42\n", encoding="utf-8")
    _prefs(client, ferramentas_arquivos_ativas=True, pastas_permitidas=[str(raiz)])
    assert client.post(f"{M}/ingerir", json={"namespace": "pessoal/empresa/velha/projetos/robo", "raiz": str(raiz),
                                             "repositorio": "robo"}).status_code == 200
    n = _nota(app, "Robo de margem: visao geral", "Consulta a margem consignavel e grava o resultado.", "pessoal/empresa/velha/projetos/robo")
    r = client.post(f"{M}/pastas/renomear", json={"origem": "pessoal/empresa/velha", "destino": "pessoal/empresa/nova"}).json()
    assert r["notas"] == 1 and r["arquivos"] == 1
    assert client.get(f"{M}/{n['id']}").json()["namespace"] == "pessoal/empresa/nova/projetos/robo"
    codigo = client.get(f"{M}/buscar", params={"q": "consultar_margem", "fonte": "codigo", "namespace": "pessoal/empresa/nova"}).json()
    assert codigo["resultados"], "indice de codigo nao migrou"
    assert client.post(f"{M}/pastas/renomear", json={"origem": "pessoal", "destino": "pessoal/x"}).status_code == 422
    assert client.post(f"{M}/pastas/renomear", json={"origem": "pessoal/empresa/nova", "destino": "pessoal/empresa/nova/sub"}).status_code == 422


def test_base_da_forja_nao_e_movida(client):
    with client.app.state.servico.repo.leitura() as t:
        base = next(m for m in t.listar(T.Memoria, limite=500) if m["namespace"].startswith("publico/forja-base"))
    r = client.post(f"{M}/pastas/mover", json={"ids": [base["id"]], "destino": "pessoal/x"}).json()
    assert r["movidas"] == 0 and "somente leitura" in r["puladas"][0]["motivo"]
    with pytest.raises(AcessoNegado):
        client.app.state.pastas.criar(P, "publico/forja-base/minha")


def test_agente_so_propoe_e_usuario_decide(client):
    app = client.app
    n = _nota(app, "Cadalfa: autenticacao por token", "O Cadalfa exige token renovado a cada 30 minutos.", "pessoal/estudos")
    r = client.post(f"{M}/pastas/propor", json={"acao": "mover", "destino": "pessoal/empresa/acme/entidades", "ids": [n["id"]],
                                                "motivo": "nota de entidade compartilhada"})
    assert r.status_code == 201 and r.json()["criada"]
    assert client.get(f"{M}/{n['id']}").json()["namespace"] == "pessoal/estudos"  # nada mudou sem o usuario
    assert client.post(f"{M}/pastas/propor", json={"acao": "mover", "destino": "pessoal/empresa/acme/entidades", "ids": [n["id"]]}).json()["criada"] is False
    sug = next(s for s in client.get(f"{M}/revisao").json()["sugestoes"] if s["tipo"] == "pasta")
    assert client.post(f"{M}/sugestoes/{sug['id']}/decidir", json={"aceitar": True}).status_code == 200
    assert client.get(f"{M}/{n['id']}").json()["namespace"] == "pessoal/empresa/acme/entidades"
    from forja.mcp.servidor import FERRAMENTAS

    assert "forja_pasta_propor" in FERRAMENTAS and len(FERRAMENTAS["forja_pasta_propor"][0]) < 200


def test_busca_padrao_e_em_todo_o_segundo_cerebro(client):
    _nota(client.app, "Gateway: limite de requisicoes", "O gateway limita a 50 requisicoes por segundo por cliente.", "pessoal/empresa/a/projetos/gw")
    padrao = client.get(f"{M}/buscar", params={"q": "gateway limite requisicoes"}).json()["resultados"]
    assert any(x.get("titulo") == "Gateway: limite de requisicoes" for x in padrao)


# ------------------------------------------------------------------ estudo por escopo
TEXTO_ESTUDO = """## Resposta
Estudo do robo.
## Notas
### Nota: Projeto Robo A: visao geral
Topico pai:
Escopo: projeto
Tags: robo-a
Robo que consulta o Cadalfa e grava o retorno numa planilha de controle. Classificacao: automacao empresarial.
### Nota: Cadalfa: autenticacao
Escopo: entidade
Entidade: Cadalfa
Tags: cadalfa, autenticacao
O Cadalfa exige token de sessao renovado a cada 30 minutos e recusa chamadas paralelas acima de 5 conexoes.
### Nota: Retry com backoff exponencial
Escopo: generico
Tags: retry
Repetir a chamada com espera dobrando a cada falha (1 s, 2 s, 4 s) ate 5 tentativas, registrando cada erro.
"""


def _estudo(app, texto: str, projeto: str, ns_proj: str, hub: str) -> dict:
    tarefa = {"id": f"T-{projeto}", "titulo": f"Estudo {projeto}", "entrada": {"estudo": {
        "tipo": "pasta", "alvo": f"C:/x/{projeto}", "namespace": ns_proj, "assunto": projeto, "raiz_id": hub, "projeto_nome": projeto,
        "ns_entidade": "pessoal/empresa/acme/entidades", "ns_generico": "pessoal/geral"}}}
    res = SimpleNamespace(artefatos=[], mensagens=[SimpleNamespace(conteudo=texto, tipo="resposta")])
    return app.state.estudos.criar_notas(tarefa, res)


def test_extrair_notas_le_escopo_e_entidade():
    notas = {n.titulo: n for n in extrair_notas(TEXTO_ESTUDO)}
    assert notas["Cadalfa: autenticacao"].escopo == "entidade" and notas["Cadalfa: autenticacao"].entidade == "Cadalfa"
    assert notas["Retry com backoff exponencial"].escopo == "generico" and notas["Projeto Robo A: visao geral"].escopo == "projeto"


def test_campos_em_negrito_ou_depois_do_corpo_nao_vazam_para_o_texto():
    texto = "### Nota: Robo Z: fluxo\nEscopo: projeto\nO robo abre o portal e baixa os arquivos do dia.\n- **Topico pai:** Projeto Robo Z\n**Tags:** robo-z, fluxo\n"
    n = extrair_notas(texto)[0]
    assert n.pai == "Projeto Robo Z" and n.tags == ["robo-z", "fluxo"] and "Topico pai" not in n.corpo and "Tags" not in n.corpo


def test_notas_de_entidade_ficam_uma_so_e_ligadas_a_cada_projeto(client):
    app = client.app
    hub_a = _nota(app, "Projeto: Robo A", "Hub do robo A.", "pessoal/empresa/acme/projetos/robo-a")
    hub_b = _nota(app, "Projeto: Robo B", "Hub do robo B.", "pessoal/empresa/acme/projetos/robo-b")
    r1 = _estudo(app, TEXTO_ESTUDO, "Robo A", "pessoal/empresa/acme/projetos/robo-a", hub_a["id"])
    assert len(r1["criadas"]) == 3
    texto_b = TEXTO_ESTUDO.replace("Projeto Robo A", "Projeto Robo B").replace(
        "recusa chamadas paralelas acima de 5 conexoes.", "devolve erro 429 quando o lote passa de 200 contratos por minuto, entao divida "
        "os lotes em blocos menores e aguarde a janela seguinte antes de reenviar os contratos restantes.")
    r2 = _estudo(app, texto_b, "Robo B", "pessoal/empresa/acme/projetos/robo-b", hub_b["id"])
    assert len(r2["criadas"]) == 1 and len(r2["completadas"]) == 2  # entidade completada, generica ja dizia o mesmo
    with app.state.servico.repo.leitura() as t:
        cred = [m for m in t.listar(T.Memoria, titulo="Cadalfa: autenticacao", limite=10)]
        hub_ent = t.listar(T.Memoria, titulo="Cadalfa", namespace="pessoal/empresa/acme/entidades", limite=5)
        retry = t.listar(T.Memoria, titulo="Retry com backoff exponencial", limite=5)
        ligs = t.listar(T.LigacaoGrafo, limite=500)
    assert len(cred) == 1 and cred[0]["namespace"] == "pessoal/empresa/acme/entidades" and "## Visto em Robo B" in cred[0]["conteudo"]
    assert len(hub_ent) == 1 and len(retry) == 1 and retry[0]["namespace"] == "pessoal/geral"
    dependem = {lg["origem"] for lg in ligs if lg["tipo"] == "DEPENDE_DE" and lg["destino"] == hub_ent[0]["id"]}
    assert dependem == {hub_a["id"], hub_b["id"]}  # a entidade e uma so, ligada aos dois projetos
    assert {lg["destino"] for lg in ligs if lg["tipo"] == "REUTILIZAVEL_EM" and lg["origem"] == retry[0]["id"]} == {hub_a["id"], hub_b["id"]}


def test_copia_da_nota_feita_pelo_agente_e_absorvida(client):
    app = client.app
    hub = _nota(app, "Projeto: Robo C", "Hub do robo C.", "pessoal/empresa/acme/projetos/robo-c")
    copia = app.state.memoria.criar(P, MemoriaIn(tipo="semantica", titulo="Tecnica: retry com backoff", namespace="pessoal/aprendizados",
                                                 conteudo="Repetir a chamada com espera dobrando a cada falha (1 s, 2 s, 4 s) ate 5 tentativas, "
                                                          "registrando cada erro.", refs=["tarefa:T-Robo C"]), "agente:mcp")
    nova = app.state.memoria.criar(P, MemoriaIn(tipo="semantica", titulo="Planilha de controle diaria", namespace="pessoal/aprendizados",
                                                conteudo="O operador confere a planilha toda manha antes das 9h.", refs=["tarefa:T-Robo C"]), "agente:mcp")
    r = _estudo(app, TEXTO_ESTUDO.replace("Projeto Robo A", "Projeto Robo C"), "Robo C", "pessoal/empresa/acme/projetos/robo-c", hub["id"])
    assert r["criadas"]
    assert client.get(f"{M}/{copia['id']}").json()["estado"] == "substituido"  # repetia a nota do estudo
    assert client.get(f"{M}/{nova['id']}").json()["estado"] == "candidato"  # trazia algo novo: fica, ligada ao projeto
    with app.state.servico.repo.leitura() as t:
        assert t.listar(T.LigacaoGrafo, origem=nova["id"], destino=hub["id"], limite=2)


def test_organizar_com_ia_cabe_no_limite_da_tarefa_com_centenas_de_notas(client):
    """Achado no lote real: com 611 notas o pedido passava de 4000 caracteres e a tarefa nem era criada."""
    app = client.app
    regra = "O portal exige token de sessao renovado a cada trinta minutos antes de qualquer consulta de contrato."
    for i in range(260):
        _nota(app, f"Robo {i}: consulta de contratos", f"Passos do robo {i} para exportar a planilha numero {i}. {regra}",
              f"pessoal/empresa/acme/projetos/robo-{i % 40}")
    r = app.state.modularidade.pedir_ia(P, ["pessoal/empresa/acme"], "foco de teste", executar=False)
    with app.state.servico.repo.leitura() as t:
        desc = t.obter(T.Tarefa, r["tarefa_id"])["descricao"]
    assert len(desc) <= 4000 and "REPETIDOS" in desc and "```json" in desc and "forja_buscar_memoria" in desc


def test_ligacao_sugerida_ignora_tags_de_estrutura_e_irmas_do_mesmo_topico(client):
    app = client.app
    org = app.state.organizador
    ns = "pessoal/empresa/acme/projetos/robo-x"

    def nota(titulo, tags):
        return app.state.memoria.criar(P, MemoriaIn(tipo="semantica", titulo=titulo, conteudo=f"{titulo}: texto proprio da nota.",
                                                    namespace=ns, tags=tags), "teste")

    hub = nota("Projeto: robo-x", ["projeto", "escopo-empresa"])
    a = nota("Robo X: login no portal", ["estudo", "robo-x", "escopo-empresa", "selenium", "login"])
    b = nota("Robo X: exportar planilha", ["estudo", "robo-x", "escopo-empresa", "planilha"])
    c = nota("Robo X: sessao do portal", ["estudo", "selenium", "login"])
    for x in (a, b):
        app.state.grafo.ligar(P, x["id"], hub["id"], "SUBTOPICO_DE")
    assert org.tags_uteis(["estudo", "escopo-empresa", "entidade", "Selenium"]) == {"selenium"}
    novas = [s for s in org._ligacoes(ns, [hub, a, b, c], set(), {(a["id"], hub["id"]), (b["id"], hub["id"])})]
    pares = {frozenset(s["memorias"]) for s in novas}
    assert frozenset({a["id"], c["id"]}) in pares  # assunto em comum (selenium + login) e soltas uma da outra
    assert frozenset({a["id"], b["id"]}) not in pares  # irmas sob o mesmo projeto: o hub ja liga


def test_tags_e_entidades_com_grafias_diferentes_viram_uma_so(client):
    from forja.memoria.modelo import normalizar_tag
    from forja.orquestracao.modularidade import pasta_do_modulo

    assert {normalizar_tag(x) for x in ("Técnica", "tecnica", "tipo:tecnica", "tipo/técnica", " #Tecnica ")} == {"tecnica"}
    assert normalizar_tag("Assunto: Concorrência em Python") == "concorrencia-em-python" and normalizar_tag("c#") == "c#"
    assert pasta_do_modulo(["pessoal/empresa/a/projetos/x", "pessoal/empresa/a/projetos/y"]) == "pessoal/empresa/a/entidades"
    assert pasta_do_modulo(["pessoal/geral", "pessoal/geral"]) == "pessoal/geral" and pasta_do_modulo(["publico/x", "pessoal/y"]) is None
    app = client.app
    hub_a = _nota(app, "Projeto: Robo D", "Hub do robo D.", "pessoal/empresa/acme/projetos/robo-d")
    hub_b = _nota(app, "Projeto: Robo E", "Hub do robo E.", "pessoal/empresa/acme/projetos/robo-e")
    _estudo(app, TEXTO_ESTUDO, "Robo D", "pessoal/empresa/acme/projetos/robo-d", hub_a["id"])
    outro = TEXTO_ESTUDO.replace("Entidade: Cadalfa", "Entidade: CadAlfa").replace("Cadalfa: autenticacao", "CadAlfa: limites de lote")
    _estudo(app, outro, "Robo E", "pessoal/empresa/acme/projetos/robo-e", hub_b["id"])
    with app.state.servico.repo.leitura() as t:
        hubs = [m for m in t.listar(T.Memoria, namespace="pessoal/empresa/acme/entidades", limite=50) if "topico" in (m["tags"] or [])]
    assert [m["titulo"] for m in hubs] == ["Cadalfa"]  # 'CadAlfa' achou o hub existente
    org = app.state.organizador
    a = _nota(app, "API RPA de Lotes", "Entidade API RPA de Lotes: o que vale para todos os projetos que a usam.", "pessoal/empresa/acme/entidades")
    b = _nota(app, "API interna RPA", "Entidade API interna RPA: o que vale para todos os projetos que a usam.", "pessoal/empresa/acme/entidades")
    assert not org._duplicatas("pessoal/empresa/acme/entidades", [a, b])  # so o texto padrao dos hubs era igual


def test_mcp_busca_notas_antes_do_codigo(client, tmp_path):
    """Achado no uso real: com 40+ projetos indexados a busca do agente so devolvia trechos de codigo e nenhuma nota."""
    import httpx

    from forja.mcp.servidor import ClienteForja, ServidorMcp

    raiz = tmp_path / "proj"
    raiz.mkdir()
    for i in range(30):
        (raiz / f"robo_{i}.py").write_text(f"def login_portal_{i}():\n    '''login no portal com retry'''\n    return 'login portal retry'\n",
                                          encoding="utf-8")
    _prefs(client, ferramentas_arquivos_ativas=True, pastas_permitidas=[str(raiz)])
    client.post(f"{M}/ingerir", json={"namespace": "pessoal/empresa/acme/projetos/robo", "raiz": str(raiz), "repositorio": "robo"})
    _nota(client.app, "Portal: login com retry", "O login no portal usa retry com espera crescente e renova a sessao.", "pessoal/empresa/acme/entidades")

    class Ponte(httpx.BaseTransport):
        def handle_request(self, request):
            r = client.request(request.method, request.url.raw_path.decode(), headers={"Authorization": request.headers["Authorization"]})
            return httpx.Response(r.status_code, content=r.content, headers={"content-type": "application/json"})

    mcp = ServidorMcp(ClienteForja("http://127.0.0.1:8787", "token-de-teste-com-tamanho-suficiente", transporte=Ponte()))
    r = mcp.tratar({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "forja_buscar_memoria",
                                                                                  "arguments": {"consulta": "login portal retry", "limite": 3}}})
    dados = json.loads(r["result"]["content"][0]["text"])
    assert dados["resultados"][0]["origem"] == "memoria" and dados["resultados"][0]["titulo"] == "Portal: login com retry"
    assert any(x["origem"] == "codigo" for x in dados["resultados"])  # o codigo continua vindo, depois das notas


# ------------------------------------------------------------------ alimentacao em lote
def _arvore(raiz):
    def arq(caminho: str, texto: str = "x = 1\n") -> None:
        p = raiz / caminho
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(texto, encoding="utf-8")

    arq("1.0. Cod - rpa-margem/requirements.txt", "selenium==4.1\nrequests>=2\n--index-url https://usuario:segredo@pypi.interno/simple\n"
        "git+https://x@github.com/y/z.git\n")
    arq("1.0. Cod - rpa-margem/src/main.py", "def consultar_margem_consignavel(matricula):\n    return matricula\n")
    arq("1.0. Cod - rpa-margem/README.md", "# RPA Margem\n\nRobo que consulta a margem consignavel no portal e grava o retorno.\n")
    arq("1.0. Cod - rpa-margem/logs/execucao.md", "erro_do_log_sintetico ocorreu\n")
    arq("1.0. Cod - rpa-margem/dados/clientes.md", "cliente_sintetico_fulano 000.000.000-00\n")
    arq("1.0. Cod - rpa-margem/.env", "TOKEN=nao-pode-ler\n")
    arq("2.4. Cod - rpa-gateway/front-gateway/package.json", json.dumps({"dependencies": {"react": "18"}}))
    arq("2.4. Cod - rpa-gateway/front-gateway/src/app.js", "export function iniciarGateway() {}\n")
    arq("2.4. Cod - rpa-gateway/control-gateway/requirements.txt", "fastapi\n")
    arq("2.4. Cod - rpa-gateway/control-gateway/app/main.py", "def rota_gateway():\n    pass\n")
    arq(".0. Historico/0.1. Cod - rpa-calculadora/main.py", "def calcular_juros():\n    pass\n")
    arq(".0. Historico/0.3. Cod - assistente-integracao/requirements.txt", "pandas\n")
    arq(".0. Estudos e projetos pessoais/1.2. Cod - pinterest-downloader/main.py", "def baixar_pin():\n    pass\n")
    (raiz / "1.6. Cod - vazio").mkdir()


def test_descobrir_projetos_escopos_grupos_e_dependencias(client, tmp_path):
    raiz = tmp_path / "Codigos"
    _arvore(raiz)
    _prefs(client, ferramentas_arquivos_ativas=True, pastas_permitidas=[str(raiz)])
    d = client.post("/api/v1/estudos/lote/descobrir", json={"raiz": str(raiz), "empresa_id": "acme",
                                                           "interno_contem": ["Estudos e projetos pessoais"]}).json()
    por_slug = {p["slug"]: p for p in d["projetos"]}
    assert set(por_slug) == {"rpa-margem", "front-gateway", "control-gateway", "rpa-calculadora", "assistente-integracao", "pinterest-downloader"}
    assert por_slug["rpa-margem"]["namespace"] == "pessoal/empresa/acme/projetos/rpa-margem"
    assert por_slug["front-gateway"]["grupo"] == "rpa-gateway"
    assert por_slug["front-gateway"]["namespace"] == "pessoal/empresa/acme/projetos/rpa-gateway/front-gateway"
    assert por_slug["rpa-calculadora"]["grupo"] == ""  # "Historico" e pasta de categoria, nao um sistema
    assert por_slug["pinterest-downloader"]["escopo"] == "interno"
    assert por_slug["pinterest-downloader"]["namespace"] == "pessoal/interno/proprios/projetos/pinterest-downloader"
    assert por_slug["rpa-margem"]["dependencias"] == ["selenium", "requests"]  # sem indice privado nem URL com credencial
    assert "Robo que consulta a margem" in por_slug["rpa-margem"]["readme"]
    assert any(i["motivo"] == "sem codigo" for i in d["ignorados"])
    assert d["por_escopo"] == {"empresa": 5, "interno": 1}
    assert nome_projeto("2.4. Cod - control-gateway-v2") == "control-gateway-v2" and slug("rpa-extração-print") == "rpa-extracao-print"


def test_lote_indexa_cria_hubs_e_ignora_logs_dados_e_segredos(client, tmp_path):
    app = client.app
    raiz = tmp_path / "Codigos"
    _arvore(raiz)
    assert client.post("/api/v1/estudos/lote", json={"raiz": str(raiz)}).status_code in (400, 422)  # pasta ainda nao permitida
    _prefs(client, ferramentas_arquivos_ativas=True, pastas_permitidas=[str(raiz)])
    lote = app.state.alimentacao
    e = lote.iniciar(LoteIn(raiz=str(raiz), empresa_id="acme", interno_contem=["Estudos e projetos pessoais"], estudar=False), esperar=True)
    assert e["situacao"] == "concluido" and all(p["etapa"] == "indexado" for p in e["projetos"])
    busca = lambda q, f="codigo": client.get(f"{M}/buscar", params={"q": q, "fonte": f}).json()["resultados"]  # noqa: E731
    assert busca("consultar_margem_consignavel") and busca("iniciarGateway")
    assert not busca("erro_do_log_sintetico") and not busca("cliente_sintetico_fulano") and not busca("nao-pode-ler")
    with app.state.servico.repo.leitura() as t:
        hub = t.listar(T.Memoria, titulo="Projeto: rpa-margem", limite=2)[0]
        grupo = t.listar(T.Memoria, titulo="Grupo: rpa-gateway", limite=2)
        indice = t.listar(T.Memoria, titulo="Projetos: empresa acme", limite=2)
        ligs = t.listar(T.LigacaoGrafo, origem=hub["id"], limite=10)
    assert hub["namespace"] == "pessoal/empresa/acme/projetos/rpa-margem" and "selenium" in hub["conteudo"] and "segredo" not in hub["conteudo"]
    assert "escopo-empresa" in hub["tags"] and grupo and indice
    assert any(lg["destino"] == indice[0]["id"] and lg["tipo"] == "SUBTOPICO_DE" for lg in ligs)
    e2 = lote.iniciar(LoteIn(raiz=str(raiz), empresa_id="acme", estudar=False), esperar=True)  # de novo: idempotente
    with app.state.servico.repo.leitura() as t:
        assert len(t.listar(T.Memoria, titulo="Projeto: rpa-margem", limite=5)) == 1
    assert e2["situacao"] == "concluido"


def test_lote_com_estudo_respeita_paralelo_e_teto(client, tmp_path, monkeypatch):
    app = client.app
    raiz = tmp_path / "Codigos"
    _arvore(raiz)
    _prefs(client, ferramentas_arquivos_ativas=True, pastas_permitidas=[str(raiz)])
    lote = app.state.alimentacao
    lote.intervalo = 0.01
    pedidos: list[dict] = []

    def falso(d, extras):
        pedidos.append({"alvo": d.alvo, "ns": d.namespace, **extras})
        return {"tarefa": {"id": f"T-{len(pedidos)}"}}

    monkeypatch.setattr(app.state.estudos, "solicitar", falso)
    monkeypatch.setattr(lote, "_situacao_tarefa", lambda _t: "concluida")
    creditos = iter([0.0, 0.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0])
    monkeypatch.setattr(lote, "_creditos", lambda _t: next(creditos, 5.0))
    e = lote.iniciar(LoteIn(raiz=str(raiz), empresa_id="acme", indexar=False, paralelo=2, teto_creditos=4), esperar=True)
    assert 1 <= len(pedidos) <= 4 and e.get("teto_atingido")
    assert any(p["etapa"] == "teto_de_creditos" for p in e["projetos"])
    p0 = pedidos[0]
    assert p0["ns_entidade"] == "pessoal/empresa/acme/entidades" and p0["ns_generico"] == "pessoal/geral" and "logs" in p0["ignorar"]
    assert "forja_buscar_memoria" in p0["pedido"] and p0["raiz_id"].startswith("MEM")


def test_mediador_nega_leitura_em_pasta_ignorada(tmp_path):
    from forja.adapters.kiro_acp.mediador import MediadorPermissoes

    eventos = []
    ctl = SimpleNamespace(evento=lambda tipo, dados: eventos.append(tipo))
    med = MediadorPermissoes(ctl, tmp_path, consulta=[tmp_path / "proj"])
    med.ignorar_dirs = frozenset({"logs", "dados"})
    assert med._ignorada({"categoria": "ler", "alvos": [str(tmp_path / "proj" / "logs" / "x.log")]})
    assert med._ignorada({"categoria": "ler", "alvos": [str(tmp_path / "proj" / "dados")]})
    assert not med._ignorada({"categoria": "ler", "alvos": [str(tmp_path / "proj" / "src" / "dados.py")]})
    (tmp_path / "proj" / "src").mkdir(parents=True)
    (tmp_path / "ws").mkdir()
    med = MediadorPermissoes(ctl, tmp_path / "ws", consulta=[tmp_path / "proj"])  # como no real: workspace isolado, pasta estudada fora
    med.ignorar_dirs = frozenset({"logs", "dados"})
    from forja.seguranca.acoes import descrever_acao

    ler = descrever_acao({"kind": "read", "title": "Ler", "locations": [{"path": str(tmp_path / "proj" / "src" / "main.py")}]},
                         tmp_path / "ws", [], [tmp_path / "proj"])
    fora = descrever_acao({"kind": "read", "title": "Ler", "locations": [{"path": str(tmp_path / "outra" / "x.py")}]}, tmp_path / "ws", [], [tmp_path / "proj"])
    assert med._leitura_em_consulta(ler) and not med._leitura_em_consulta({**ler, "varredura": True}) and not med._leitura_em_consulta(fora)
    med.leitura_consulta_livre = True
    pedido = {"options": [{"kind": "allow_once", "optionId": "sim"}, {"kind": "reject_once", "optionId": "nao"}],
              "toolCall": {"kind": "read", "title": "Ler main.py", "locations": [{"path": str(tmp_path / "proj" / "src" / "main.py")}]}}
    assert med.decidir(pedido) == "sim" and "kiro.permissao_automatica" in eventos  # estudo le a pasta estudada sem perguntar
    pedido_log = {**pedido, "toolCall": {"kind": "read", "title": "Ler log", "locations": [{"path": str(tmp_path / "proj" / "logs" / "a.log")}]}}
    assert med.decidir(pedido_log) == "nao"


def test_conflito_ao_remover_pasta_inexistente(client):
    assert client.delete(f"{M}/pastas", params={"namespace": "pessoal/nao-existe"}).status_code == 404
    with pytest.raises(Conflito):
        _nota(client.app, "x nota", "conteudo da nota x para a pasta.", "pessoal/tem-nota")
        client.app.state.pastas.remover(P, "pessoal/tem-nota")
