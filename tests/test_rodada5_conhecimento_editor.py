"""Rodada 5 (ADR-027): reciclagem de sessoes antigas, caderno <-> segundo cerebro <-> grafo, catalogo de autocompletar de codigo,
LSP (servidor falso por subprocesso) e acesso dos agentes fora das pastas do projeto. Dados sinteticos."""

from __future__ import annotations

import re
import sys
import textwrap
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from forja.adapters.kiro_acp.mediador import MediadorPermissoes
from forja.adapters.lsp.gerente import snippet_lsp
from forja.adapters.sqlite import tabelas as T
from forja.agentes.base import ControleExecucao
from forja.agentes.estilo import PerfilTrabalho
from forja.assistente.codigo import LINGUAGENS, CatalogoCodigo, CodigoServico, linguagem_catalogo
from forja.dominio.contratos import ObjetivoIn, ProjetoIn, TarefaIn
from forja.dominio.tempo import iso
from forja.memoria.modelo import Principal
from forja.preferencias.registro import POR_ID
from forja.preferencias.servico import validar_valor
from forja.seguranca.pastas import caminhos_citados, dentro_de_citado

A = "/api/v1/area"


# ------------------------------------------------------------------ helpers
def _tarefa(app, projeto: str, titulo: str, descricao: str = "", estado: str = "concluida", dias: int = 40,
            caderno: tuple[tuple[str, str], ...] = (), respostas: tuple[str, ...] = ()) -> dict:
    s = app.state.servico
    proj = next(iter(s.listar(T.Projeto, nome=projeto)), None) or s.criar_projeto(ProjetoIn(nome=projeto))[0]
    obj, _ = s.criar_objetivo(ObjetivoIn(projeto_id=proj["id"], titulo=f"obj {titulo}"[:200], prioridade=3, criterios_sucesso=["ok"]))
    t, _ = s.criar_tarefa(TarefaIn(objetivo_id=obj["id"], titulo=titulo, descricao=descricao or titulo, criterios_aceite=["ok"],
                                   especialidade="geral", modo="analise"))
    for tipo, texto in caderno:
        app.state.caderno.salvar(t["id"], tipo, texto)
    velho = iso(datetime.now(UTC) - timedelta(days=dias))
    with s.repo.escrita() as tx:
        for n, r in enumerate(respostas):
            tx.inserir(T.Mensagem, id=f"MSG-{uuid.uuid4().hex[:10]}", tarefa_id=t["id"], ordem=n + 1, execucao_id=None, papel="operador",
                       tipo="resposta_operador", conteudo=r, dados=None, criado_em=velho)
        tx.atualizar(T.Tarefa, t["id"], estado=estado, atualizado_em=velho)
    return {**t, "projeto_id": proj["id"]}


def _notas(app, ns: str) -> list[dict]:
    with app.state.servico.repo.leitura() as t:
        return [m for m in t.listar(T.Memoria, namespace=ns, limite=200) if m["estado"] not in ("revogado", "substituido")]


CADERNO = (("decisao", "Usar fila de retentativas com backoff exponencial para o envio de notas fiscais"),
           ("resolvido", "Timeout do provedor de notas fiscais corrigido aumentando o limite para 30 s"),
           ("erro", "Duplicidade de envio quando o worker reiniciava; corrigido com chave de idempotencia"),
           ("fato", "O provedor de notas fiscais aceita no maximo 10 requisicoes por segundo"))


# ------------------------------------------------------------------ reciclagem
def test_reciclagem_destila_sessao_com_valor_liga_ao_topico_e_nao_duplica(client):
    app = client.app
    t1 = _tarefa(app, "Loja Fiscal", "Envio de notas fiscais com retentativa", caderno=CADERNO,
                 respostas=("Pode usar backoff exponencial, maximo 5 tentativas",))
    trivial = _tarefa(app, "Loja Fiscal", "Ajustar texto do botao", caderno=(("resolvido", "texto trocado"),))
    nova = _tarefa(app, "Loja Fiscal", "Tarefa recente", dias=1, caderno=CADERNO)

    previa = client.get("/api/v1/reciclagem/previa").json()
    acoes = {i["id"]: i["acao"] for i in previa["itens"]}
    assert acoes[t1["id"]] == "criar" and acoes[trivial["id"]] == "sem_valor" and nova["id"] not in acoes  # recente fica
    assert not _notas(app, "pessoal/projetos/loja-fiscal")  # previa nao grava

    r = client.post("/api/v1/reciclagem", json={}).json()
    por_alvo = {i["alvo_id"]: i for i in r["itens"]}
    assert por_alvo[t1["id"]]["resultado"] == "criada" and por_alvo[trivial["id"]]["resultado"] == "sem_valor"
    notas = {m["titulo"]: m for m in _notas(app, "pessoal/projetos/loja-fiscal")}
    nota = notas["Registro: Envio de notas fiscais com retentativa"]
    for secao in ("## Decisões", "## Resolvido", "## Erros e correções", "## Fatos", "## Decisões do desenvolvedor"):
        assert secao in nota["conteudo"]
    assert "tarefa:" + t1["id"] in nota["refs"] and "reciclada" in nota["tags"]
    assert "Registro: Ajustar texto do botao" not in notas  # sem valor: so arquivada
    # grafo: pendurada no topico do projeto, e o topico aparece nos links (ligacao tipada)
    links = client.get(f"/api/v1/memorias/{nota['id']}/links").json()
    assert any(x["tipo"] == "SUBTOPICO_DE" and x["titulo"] == "Projeto: Loja Fiscal" for x in links["saida"])
    # idempotente: rodar de novo nao recicla o que ja foi
    assert client.post("/api/v1/reciclagem", json={}).json()["reciclados"] == 0
    assert client.post("/api/v1/reciclagem", json={"alvo_id": t1["id"]}).status_code == 422

    # sessao parecida do mesmo projeto: vira SECAO da nota existente (sem nota nova)
    t2 = _tarefa(app, "Loja Fiscal", "Retentativa do envio de notas fiscais no provedor",
                 caderno=(("decisao", "Manter backoff exponencial para o envio de notas fiscais no provedor"),
                          ("erro", "Timeout do provedor de notas fiscais voltou com 10 requisicoes por segundo"),
                          ("resolvido", "Fila de retentativas de notas fiscais com chave de idempotencia")),
                 respostas=("ok, pode seguir",))
    r2 = client.post("/api/v1/reciclagem", json={"alvo_id": t2["id"]}).json()["itens"][0]
    assert r2["resultado"] == "enriquecida" and r2["memoria_id"] == nota["id"]
    depois = client.get(f"/api/v1/memorias/{nota['id']}").json()
    assert "## Também: Retentativa do envio" in depois["conteudo"] and f"tarefa:{t2['id']}" in depois["refs"]
    assert len([m for m in _notas(app, "pessoal/projetos/loja-fiscal") if m["titulo"].startswith("Registro:")]) == 1
    hist = client.get("/api/v1/reciclagem").json()
    assert {h["alvo_id"] for h in hist["historico"]} >= {t1["id"], t2["id"], trivial["id"]}


def test_registro_ao_concluir_e_enriquecido_e_caderno_pode_ser_compactado(client):
    app = client.app
    t = _tarefa(app, "Projeto Compacto", "Migrar relatorios para o novo banco", caderno=CADERNO, respostas=("migre so os mensais",))
    ns = "pessoal/projetos/projeto-compacto"
    # nota que o registro ao concluir ja criou para a mesma tarefa (ref tarefa:<id>)
    from forja.memoria.contratos import MemoriaIn

    m = app.state.memoria.criar(Principal("t", frozenset({"pessoal"})), MemoriaIn(
        tipo="decisoria", titulo="Registro: Migrar relatorios para o novo banco", resumo="r", conteudo="## Entendimento\nmigrar",
        namespace=ns, refs=[f"tarefa:{t['id']}"]), "teste")
    app.state.reciclagem.compactar = "caderno"
    r = client.post("/api/v1/reciclagem", json={"alvo_id": t["id"]}).json()["itens"][0]
    assert r["resultado"] == "enriquecida" and r["memoria_id"] == m["id"] and r["compactado"] == "caderno"
    nota = client.get(f"/api/v1/memorias/{m['id']}").json()
    assert "## Entendimento" in nota["conteudo"] and "## Decisões" in nota["conteudo"] and "## Também" not in nota["conteudo"]
    assert app.state.caderno.listar(t["id"]) == []  # copiado para a nota, depois apagado (preferencia)
    # pedido e respostas nunca sao apagados
    with app.state.servico.repo.leitura() as tx:
        assert tx.listar(T.Mensagem, tarefa_id=t["id"], limite=5)


def test_tarefa_nao_terminada_nao_e_reciclada(client):
    app = client.app
    s = app.state.servico
    proj, _ = s.criar_projeto(ProjetoIn(nome="Aberto"))
    obj, _ = s.criar_objetivo(ObjetivoIn(projeto_id=proj["id"], titulo="o", prioridade=3, criterios_sucesso=["ok"]))
    t, _ = s.criar_tarefa(TarefaIn(objetivo_id=obj["id"], titulo="em andamento", descricao="d", criterios_aceite=["ok"],
                                   especialidade="geral", modo="analise"))
    r = client.post("/api/v1/reciclagem", json={"alvo_id": t["id"]})
    assert r.status_code == 422 and "terminadas" in r.text


# ------------------------------------------------------------------ caderno <-> segundo cerebro <-> grafo
def test_caderno_amplo_traz_o_que_sessoes_anteriores_do_projeto_deixaram(client):
    app = client.app
    antiga = _tarefa(app, "Loja Ponte", "Envio de notas fiscais com retentativa", caderno=CADERNO, respostas=("use backoff",))
    client.post("/api/v1/reciclagem", json={"alvo_id": antiga["id"]})
    atual = _tarefa(app, "Loja Ponte", "Nova integracao fiscal", dias=0)
    so_caderno = client.get(f"/api/v1/tarefas/{atual['id']}/caderno", params={"q": "notas fiscais"}).json()
    assert so_caderno == []  # comportamento antigo intacto sem 'amplo'
    amplo = client.get(f"/api/v1/tarefas/{atual['id']}/caderno", params={"q": "notas fiscais retentativa", "amplo": True}).json()
    origens = {i["origem"] for i in amplo}
    assert "memoria" in origens and any("Envio de notas fiscais" in i["texto"] for i in amplo)
    assert any(i["origem"] == "grafo" and "Projeto: Loja Ponte" in i["texto"] for i in amplo)  # vizinho pelo grafo
    # outro projeto nao enxerga
    outra = _tarefa(app, "Outro Projeto", "Nova integracao fiscal", dias=0)
    assert not [i for i in client.get(f"/api/v1/tarefas/{outra['id']}/caderno", params={"q": "notas fiscais retentativa", "amplo": True}).json()
                if i["origem"] != "caderno"]


def test_contexto_inicial_inclui_o_namespace_do_proprio_projeto(client):
    app = client.app
    antiga = _tarefa(app, "Loja Contexto", "Envio de notas fiscais com retentativa", caderno=CADERNO, respostas=("use backoff",))
    client.post("/api/v1/reciclagem", json={"alvo_id": antiga["id"]})
    ctx = app.state.servico.construtor_contexto
    nova = _tarefa(app, "Loja Contexto", "Envio de notas fiscais em lote", dias=0)
    pacote = ctx.construir({**nova, "politicas": {}})
    assert any("Envio de notas fiscais com retentativa" in i.texto for i in pacote.itens)
    ctx.namespaces_da_tarefa = None  # preferencia desligada: so os namespaces de contexto configurados
    assert not any("retentativa" in i.texto for i in ctx.construir({**nova, "politicas": {}}).itens)


def test_agente_nao_cria_nota_duplicada(client):
    corpo = {"tipo": "semantica", "titulo": "Backoff exponencial no envio de notas", "resumo": "r",
             "conteudo": "Use backoff exponencial com no maximo 5 tentativas no envio de notas fiscais.", "namespace": "pessoal/aprendizados"}
    a = client.post("/api/v1/memorias", params={"evitar_duplicata": True}, json=corpo).json()
    b = client.post("/api/v1/memorias", params={"evitar_duplicata": True}, json={**corpo, "titulo": "Backoff exponencial no envio das notas"}).json()
    assert not a.get("duplicata") and b["duplicata"] is True and b["id"] == a["id"]
    c = client.post("/api/v1/memorias", params={"evitar_duplicata": True}, json={**corpo, "titulo": "Cache de consultas SQL",
                                                                                "conteudo": "Cache com TTL curto nas consultas pesadas."}).json()
    assert not c.get("duplicata") and c["id"] != a["id"]


# ------------------------------------------------------------------ catalogo de autocompletar de codigo
def test_catalogo_de_codigo_cobre_as_cinco_linguagens_e_e_valido():
    cat = CatalogoCodigo()
    ramos = cat.ramos()
    assert {r.linguagem for r in ramos.values()} == set(LINGUAGENS)
    for r in ramos.values():
        assert r.itens, r.id
        for rx in r.detectar:
            re.compile(rx, re.MULTILINE)
        for it in r.itens:
            if it.tipo == "trecho":
                assert it.inserir, (r.id, it.rotulo)
    n = {lng: sum(len(r.itens) for r in ramos.values() if r.linguagem == lng) for lng in LINGUAGENS}
    assert min(n.values()) >= 60, n
    assert linguagem_catalogo("typescript") == "javascript" and linguagem_catalogo("cobol") is None
    py = cat.catalogo("python", desligados=["python.pandas"])
    assert py["linguagem"] == "python" and "python.pandas" not in {r["id"] for r in py["ramos"]}
    pandas = ramos["python.pandas"]
    assert pandas.modulo == "pandas" and any(i.rotulo == "read_csv" and i.apos == ["pandas"] for i in pandas.itens)


def test_usuario_e_ia_estendem_o_catalogo_sem_trocar_o_padrao(tmp_path):
    cat = CatalogoCodigo(tmp_path)

    class _Servico:
        def obter(self, cls, id_):  # noqa: ANN001, ANN201
            return {"id": id_, "entrada": {"codigo_assistente": {"linguagem": "python", "ramo": ""}}}

        def listar(self, cls, **kw):  # noqa: ANN001, ANN201, ARG002
            return [{"id": "ART-1", "nome": "resposta.md", "criado_em": "2026-11-19"}]

        def obter_artefato(self, id_, com_conteudo=False):  # noqa: ANN001, ANN201, ARG002
            return {"conteudo": "Segue.\n```json\n" + __import__("json").dumps({"ramos": [{
                "id": "python.polars", "linguagem": "python", "rotulo": "Polars", "descricao": "DataFrames rapidos", "modulo": "polars",
                "detectar": ["^\\s*import\\s+polars"], "itens": [
                    {"rotulo": "read_csv", "tipo": "funcao", "assinatura": "pl.read_csv(caminho)", "doc": "Le CSV.", "apos": ["polars"]},
                    {"rotulo": "", "tipo": "funcao"}]}]}) + "\n```"}

    svc = CodigoServico(cat, _Servico())
    r = svc.importar("T-1")
    assert r["importados"] == [{"ramo": "python.polars", "itens": 1, "recusados": 1}]
    polars = cat.ramos()["python.polars"]
    assert polars.origem == "ia" and polars.itens[0].revisado is False
    assert cat.revisar("python.polars") == 1 and cat.ramos()["python.polars"].itens[0].revisado is True
    svc.salvar_item("python.builtins", {"rotulo": "breakpoint", "tipo": "funcao", "assinatura": "breakpoint()", "doc": "Para no depurador."})
    b = cat.ramos()["python.builtins"]
    assert any(i.rotulo == "breakpoint" and i.origem == "usuario" for i in b.itens) and any(i.rotulo == "print" for i in b.itens)
    cat.remover_item("python.builtins", "breakpoint")
    assert not any(i.rotulo == "breakpoint" for i in cat.ramos()["python.builtins"].itens)
    with pytest.raises(Exception, match="seus ou da IA"):
        cat.remover_item("python.builtins", "print")  # padrao nao se remove


def test_api_do_editor_entrega_preferencias_e_catalogo(client):
    e = client.get(f"{A}/editor").json()
    assert e["preferencias"]["autocompletar_codigo"] is True and e["preferencias"]["autocompletar_fontes"] == ["lsp", "catalogo", "trechos", "palavras"]
    assert {s["id"] for s in e["lsp"]["servidores"]} == {"python", "typescript", "html", "css", "csharp"}
    js = client.get(f"{A}/codigo/catalogo", params={"linguagem": "typescript"}).json()
    assert js["linguagem"] == "javascript" and any(r["id"] == "javascript.dom" for r in js["ramos"])
    falta = client.post(f"{A}/codigo/ia", json={"linguagem": "python", "ramo": "", "pedido": ""})
    assert falta.status_code == 422


def test_preferencia_escolhas_valida_contra_as_opcoes():
    p = POR_ID["autocompletar_fontes"]
    assert validar_valor(p, ["palavras", "lsp"]) == ["lsp", "palavras"]  # ordem das opcoes
    with pytest.raises(Exception, match="escolha entre"):
        validar_valor(p, ["inventada"])
    assert "python.pandas" in {v for v, _ in POR_ID["autocompletar_ramos_desligados"].opcoes}


# ------------------------------------------------------------------ LSP
def test_snippet_do_lsp_vira_formato_do_editor():
    assert snippet_lsp("soma(${1:a}, ${2:b})$0") == "soma(${a}, ${b})${0}"
    assert snippet_lsp("for $1 in ${2|itens,lista|}:\n\t$0") == "for ${} in ${itens}:\n\t${0}"
    assert snippet_lsp("x = \\$HOME") == "x = $HOME" and snippet_lsp("${TM_SELECTED_TEXT}fim") == "fim"


SERVIDOR_FALSO = textwrap.dedent('''
    import json, sys
    def ler():
        h = {}
        while True:
            linha = sys.stdin.buffer.readline()
            if not linha:
                sys.exit(0)
            linha = linha.strip()
            if not linha:
                break
            k, v = linha.split(b":", 1)
            h[k.strip().lower()] = int(v)
        return json.loads(sys.stdin.buffer.read(h[b"content-length"]))
    def enviar(m):
        b = json.dumps(m).encode()
        sys.stdout.buffer.write(b"Content-Length: %d\\r\\n\\r\\n" % len(b) + b)
        sys.stdout.buffer.flush()
    def resp(m, r):
        enviar({"jsonrpc": "2.0", "id": m["id"], "result": r})
    while True:
        m = ler()
        met, p = m.get("method"), m.get("params") or {}
        if met == "initialize":
            resp(m, {"capabilities": {"completionProvider": {}, "hoverProvider": True, "definitionProvider": True, "signatureHelpProvider": {}}})
            enviar({"jsonrpc": "2.0", "id": "cfg-1", "method": "workspace/configuration", "params": {"items": [{"section": "python"}]}})
        elif met in ("textDocument/didOpen", "textDocument/didChange"):
            uri = p["textDocument"]["uri"]
            texto = p["textDocument"]["text"] if met.endswith("didOpen") else p["contentChanges"][-1]["text"]
            d = [{"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 4}}, "severity": 1,
                  "message": "erro sintetico", "source": "falso", "code": "F1"}] if "ERRO" in texto else []
            enviar({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics", "params": {"uri": uri, "diagnostics": d}})
        elif met == "textDocument/completion":
            resp(m, {"isIncomplete": False, "items": [
                {"label": "soma", "kind": 3, "detail": "(a, b) -> int", "insertText": "soma(${1:a}, ${2:b})$0", "insertTextFormat": 2,
                 "documentation": {"kind": "markdown", "value": "Soma dois numeros."}}, {"label": "saida", "kind": 6}]})
        elif met == "textDocument/hover":
            resp(m, {"contents": {"kind": "markdown", "value": "**soma**: soma dois numeros"}})
        elif met == "textDocument/signatureHelp":
            resp(m, {"signatures": [{"label": "soma(a, b)", "parameters": [{"label": [5, 6]}, {"label": [8, 9]}]}], "activeSignature": 0,
                     "activeParameter": 1})
        elif met == "textDocument/definition":
            uri = p["textDocument"]["uri"]
            resp(m, [{"uri": uri, "range": {"start": {"line": 2, "character": 4}, "end": {"line": 2, "character": 8}}},
                     {"uri": "file:///C:/fora/biblioteca.py", "range": {"start": {"line": 9, "character": 0}, "end": {"line": 9, "character": 1}}}])
        elif met == "shutdown":
            resp(m, None)
        elif met == "exit":
            sys.exit(0)
        elif "id" in m and met:
            resp(m, None)
''')


@pytest.fixture
def proj_lsp(client, tmp_path: Path, monkeypatch):
    trab = tmp_path / "trab"
    trab.mkdir()
    (trab / "app.py").write_text("x = 1\n\ndef soma(a, b):\n    return a + b\n", encoding="utf-8")
    p = client.post("/api/v1/projetos", json={"nome": f"lsp-{tmp_path.name}"}).json()
    client.put(f"/api/v1/projetos/{p['id']}/pastas", json={"expected_version": 1, "pastas": [{"caminho": str(trab), "papel": "trabalho"}]})
    script = tmp_path / "lsp_falso.py"
    script.write_text(SERVIDOR_FALSO, encoding="utf-8")
    g = client.app.state.area.gerente_lsp
    monkeypatch.setattr(g, "resolver", lambda d: [sys.executable, str(script)] if d.id == "python" else None)
    return p["id"], trab


def test_lsp_completa_explica_vai_para_definicao_e_diagnostica(client, proj_lsp):
    pid, _ = proj_lsp
    base = {"projeto": pid, "raiz": 0, "rel": "app.py", "texto": "x = 1\n\ndef soma(a, b):\n    return a + b\nso", "linha": 4, "coluna": 2}
    c = client.post(f"{A}/lsp/completar", json=base).json()
    soma = next(i for i in c["itens"] if i["rotulo"] == "soma")
    assert soma["tipo"] == "funcao" and soma["inserir"] == "soma(${a}, ${b})${0}" and soma["doc"] == "Soma dois numeros."
    h = client.post(f"{A}/lsp/explicar", json=base).json()
    assert "soma dois numeros" in h["texto"] and h["assinatura"]["parametro"] == "b"
    d = client.post(f"{A}/lsp/definicao", json=base).json()["definicoes"]
    assert d[0] == {"rel": "app.py", "externo": False, "nome": "app.py", "linha": 3, "coluna": 5} and d[1]["externo"] is True
    sem = client.post(f"{A}/lsp/diagnosticos", json=base).json()
    assert sem["problemas"] == []
    com = client.post(f"{A}/lsp/diagnosticos", json={**base, "texto": "ERRO aqui\n"}).json()
    assert com["problemas"] == [{"linha": 1, "coluna": 1, "gravidade": "erro", "codigo": "F1", "mensagem": "erro sintetico", "fonte": "falso"}]
    estado = client.get(f"{A}/lsp").json()
    assert next(s for s in estado["servidores"] if s["id"] == "python")["rodando"]
    css = client.post(f"{A}/lsp/completar", json={**base, "rel": "app.py"})
    assert css.status_code == 200
    # linguagem sem servidor instalado: resposta clara, sem erro 500
    (proj_lsp[1] / "estilo.css").write_text("a { }", encoding="utf-8")
    sem_srv = client.post(f"{A}/lsp/completar", json={**base, "rel": "estilo.css"}).json()
    assert sem_srv["indisponivel"] is True and "nao instalado" in sem_srv["motivo"]


def test_lsp_desligado_e_instalacao_pede_confirmacao(client, proj_lsp):
    pid, _ = proj_lsp
    r = client.post(f"{A}/lsp/instalar", json={"servidor": "python"})
    assert r.status_code == 428 and any("internet" in m for m in r.json()["dados"]["motivos"])
    client.app.state.area.gerente_lsp.ativo = False
    x = client.post(f"{A}/lsp/completar", json={"projeto": pid, "raiz": 0, "rel": "app.py", "texto": "x", "linha": 0, "coluna": 1}).json()
    assert x["indisponivel"] is True and "desligados" in x["motivo"]


# ------------------------------------------------------------------ fora das pastas do projeto
def test_caminhos_citados_pelo_usuario(tmp_path):
    fora = tmp_path / "relatorios"
    fora.mkdir()
    (fora / ".env").write_text("X=1", encoding="utf-8")
    texto = f"Compare com os dados em {fora}, e ignore {tmp_path / 'nao_existe'} e {fora / '.env'}."
    citados = caminhos_citados(texto)
    assert citados == [fora.resolve()]
    assert dentro_de_citado(str(fora / "jan.csv"), citados) and not dentro_de_citado(str(tmp_path / "outra" / "x"), citados)
    assert caminhos_citados(f"olhe {Path.home()}") == []  # pasta pessoal inteira nao conta


def _pedido(caminho: Path, kind: str = "read") -> dict:
    return {"options": [{"kind": "allow_once", "optionId": "sim"}, {"kind": "reject_once", "optionId": "nao"}],
            "toolCall": {"toolCallId": "t1", "kind": kind, "title": f"{'Read' if kind == 'read' else 'Edit'} {caminho}",
                         "locations": [{"path": str(caminho)}], "rawInput": {"path": str(caminho)}}}


def test_mediador_fora_da_pasta_segue_a_preferencia(tmp_path):
    proj, fora = tmp_path / "proj", tmp_path / "fora"
    proj.mkdir()
    fora.mkdir()
    (fora / "dados.csv").write_text("a,b\n", encoding="utf-8")
    eventos, perguntas = [], []

    def aprovar(itens):  # noqa: ANN001, ANN202
        perguntas.extend(itens)
        return {"aprovados": [], "adendo": "", "lembrar": False}

    ctl = ControleExecucao(lambda c: None, lambda t, d: eventos.append((t, d)), aprovar)
    m = MediadorPermissoes(ctl, proj, janela=0.01, perfil=PerfilTrabalho(nivel="total"), trabalho=[], consulta=[])
    assert m.decidir(_pedido(fora / "dados.csv")) == "nao" and len(perguntas) == 1  # padrao: pergunta (e o usuario negou)
    m.citados = [fora.resolve()]
    assert m.decidir(_pedido(fora / "dados.csv")) == "sim" and len(perguntas) == 1  # citado no pedido: le sem perguntar
    assert any(d.get("motivo") == "pasta citada no pedido" for t, d in eventos if t == "kiro.permissao_automatica")
    m.citados, m.fora_da_pasta = [], "livre_leitura"
    assert m.decidir(_pedido(fora / "dados.csv")) == "sim"
    assert m.decidir(_pedido(fora / "dados.csv", "edit")) == "nao" and len(perguntas) == 2  # escrever fora continua perguntando
    m.fora_da_pasta, m.citados = "bloquear", [fora.resolve()]
    assert m.decidir(_pedido(fora / "dados.csv")) == "nao" and len(perguntas) == 2  # bloquear: nega sem perguntar
