"""Qualidade da busca: linguagem (radicais/sinonimos), benchmark rotulado (baseline x nova), grafo e simbolos de docs."""

from __future__ import annotations

from pathlib import Path

import pytest

from forja.adapters.sqlite.repositorio import RepositorioSqlite
from forja.memoria import indexador
from forja.memoria.avaliacao import Caso, avaliar, carregar_benchmark, comparar, metricas_do_caso
from forja.memoria.contratos import ArestaIn, FonteIn, IngerirIn, MemoriaIn, NoIn
from forja.memoria.linguagem import grupos_de_expansao, montar_match, radical, sinonimos_de, termos_relevantes
from forja.memoria.modelo import Principal
from forja.orquestracao.memoria_servico import ServicoMemoria

RAIZ = Path(__file__).resolve().parents[1]
BENCH = RAIZ / "knowledge" / "modelos_publicos" / "benchmark_busca.json"
P = Principal("t", frozenset({"publico", "pessoal"}))


@pytest.fixture
def mem(repo: RepositorioSqlite, tmp_path: Path) -> ServicoMemoria:
    return ServicoMemoria(repo, raizes_ingestao=[tmp_path / "repos"])


# ------------------------------------------------------------------ linguagem
@pytest.mark.parametrize(("palavra", "esperado"), [
    ("autenticacao", "autentic"), ("autenticando", "autentic"), ("autenticar", "autentic"),
    ("acoes", "acao"), ("ações", "acao"), ("requisicoes", "requisicao"), ("credenciais", "credencial"),
    ("sistema", "sistema"), ("log", "log"), ("api", "api"), ("v1", "v1"),
])
def test_radical(palavra, esperado):
    assert radical(palavra) == esperado


def test_radical_nunca_gera_prefixo_curto_demais():
    for palavra in ("dados", "uso", "gerenciamento", "relatorios", "ambiente"):
        assert len(radical(palavra)) >= 3 or radical(palavra) == palavra


def test_sinonimos_cobrem_pt_en_e_sao_simetricos():
    assert "login" in sinonimos_de("autenticar") and "authenticate" in sinonimos_de("login")
    assert "apagar" in sinonimos_de("excluir") and "excluir" in sinonimos_de("apagar")
    assert sinonimos_de("zzzinexistente") == ()


def test_sinonimos_do_arquivo_publico_estendem_os_embutidos(tmp_path: Path):
    arq = tmp_path / "sin.json"
    arq.write_text('{"grupos": [["rpa", "automacao", "robo"]]}', encoding="utf-8")
    assert "robo" in sinonimos_de("rpa", str(arq))
    assert sinonimos_de("rpa") == ()  # sem o arquivo, nao existe
    (tmp_path / "quebrado.json").write_text("{nao e json", encoding="utf-8")
    assert "login" in sinonimos_de("autenticar", str(tmp_path / "quebrado.json"))  # arquivo invalido nao derruba


def test_stopwords_saem_mas_nunca_deixam_a_consulta_vazia():
    assert termos_relevantes(["como", "logar", "no", "portal"]) == ["logar", "portal"]
    assert termos_relevantes(["como", "para"]) == ["como"]


def test_match_gerado_e_seguro_contra_operadores_fts():
    import re

    grupos = grupos_de_expansao(['titulo:foo', 'AND', 'NEAR(x', '"aberta'])
    m = montar_match(grupos)
    # tudo que o usuario digitou esta ENTRE ASPAS (frase literal): fora delas so restam os operadores que NOS inserimos
    fora_das_aspas = re.sub(r'"[^"]*"\*?', "", m)
    assert re.fullmatch(r"[\s()]*(?:(?:AND|OR)[\s()]*)*", fora_das_aspas), fora_das_aspas
    assert m.count('"') % 2 == 0
    assert montar_match([]) == ""


# ------------------------------------------------------------------ metricas
def test_metricas_do_caso_sao_matematicamente_corretas():
    m = metricas_do_caso(["x", "A", "y", "B"], frozenset({"A", "B"}), k=3)
    assert m["recall"] == 0.5 and m["rr"] == 0.5  # so A no top-3; primeiro relevante na posicao 2
    perfeito = metricas_do_caso(["A", "B", "z"], frozenset({"A", "B"}), k=3)
    assert perfeito == {"recall": 1.0, "rr": 1.0, "ndcg": 1.0}
    assert metricas_do_caso(["z"], frozenset({"A"}), k=3) == {"recall": 0.0, "rr": 0.0, "ndcg": 0.0}


def test_avaliar_agrega_por_categoria():
    casos = [Caso("q1", frozenset({"A"}), "x"), Caso("q2", frozenset({"B"}), "y")]
    r = avaliar(lambda q: ["A"] if q == "q1" else ["z"], casos, k=3)
    assert r["global"]["recall@3"] == 0.5 and r["por_categoria"]["x"]["mrr"] == 1.0
    assert r["por_categoria"]["y"]["recall@3"] == 0.0


# ------------------------------------------------------------------ benchmark: a busca NOVA e melhor, sem regredir
@pytest.fixture(scope="module")
def resultado_benchmark(tmp_path_factory, _db_migrado):
    import shutil

    from forja.adapters.sqlite.banco import criar_engines

    db = tmp_path_factory.mktemp("bench") / "b.sqlite3"
    shutil.copyfile(_db_migrado, db)
    w, r = criar_engines(db)
    repo = RepositorioSqlite(w, r)
    try:
        memorias, casos = carregar_benchmark(BENCH)
        return comparar(ServicoMemoria(repo), Principal("b", frozenset({"publico"})), memorias, casos, k=3)
    finally:
        repo.fechar()


def test_benchmark_tem_tamanho_e_ruido_suficientes():
    memorias, casos = carregar_benchmark(BENCH)
    assert len(memorias) >= 40 and len(casos) >= 30  # com 16 docs o top-k trivializa tudo (descoberto na pratica)
    assert {c.categoria for c in casos} >= {"exata", "radical", "sinonimo", "natural", "bilingue", "dificil"}


def test_busca_nova_supera_o_baseline_no_global(resultado_benchmark):
    b, n = resultado_benchmark["baseline"]["global"], resultado_benchmark["nova"]["global"]
    assert n["recall@3"] >= b["recall@3"] + 0.10
    assert n["mrr"] >= b["mrr"] + 0.10
    assert n["ndcg@3"] >= b["ndcg@3"] + 0.10


def test_nenhuma_categoria_piora_em_relacao_ao_baseline(resultado_benchmark):
    """Regressao real encontrada: a primeira versao (descartar termos comuns) piorou 'dificil', 'natural' e 'sinonimo'."""
    base, nova = resultado_benchmark["baseline"]["por_categoria"], resultado_benchmark["nova"]["por_categoria"]
    for categoria, b in base.items():
        assert nova[categoria]["recall@3"] >= b["recall@3"] - 1e-9, categoria
        assert nova[categoria]["mrr"] >= b["mrr"] - 1e-9, categoria


def test_ganhos_onde_a_tecnica_deveria_ajudar(resultado_benchmark):
    nova = resultado_benchmark["nova"]["por_categoria"]
    base = resultado_benchmark["baseline"]["por_categoria"]
    assert nova["exata"]["recall@3"] == 1.0
    assert nova["sinonimo"]["recall@3"] >= 0.95 and nova["sinonimo"]["mrr"] > base["sinonimo"]["mrr"]
    assert nova["bilingue"]["recall@3"] > base["bilingue"]["recall@3"]
    assert nova["dificil"]["recall@3"] >= base["dificil"]["recall@3"] + 0.25


def test_termo_raro_certo_vence_documentos_que_repetem_palavras_genericas(mem):
    """Caso que quebrou a 1a versao: 'autenticando' (raro) + 'usuarios'/'sistema' (comuns no ruido)."""
    mem.criar(P, MemoriaIn(tipo="procedimental", titulo="Procedimento de autenticação no portal",
                           conteudo="Preencher o formulário de login e confirmar a sessão.", namespace="publico"))
    for i in range(6):
        mem.criar(P, MemoriaIn(tipo="semantica", titulo=f"Manual {i} do sistema",
                               conteudo="O sistema atende usuários e o sistema registra usuários ativos.", namespace="publico"))
    topo = mem.buscar(P, "autenticando usuários no sistema", ["publico"], fontes=("memoria",))["resultados"][0]
    assert "autenticação" in topo["titulo"]


def test_resposta_informa_a_expansao_para_transparencia(mem):
    mem.criar(P, MemoriaIn(tipo="semantica", titulo="Login do portal", conteudo="x", namespace="publico"))
    r = mem.buscar(P, "autenticar", ["publico"], fontes=("memoria",))
    assert r["resultados"] and "login" in r["expansao"][0]["alternativas"]
    assert mem.buscar(P, "autenticar", ["publico"], fontes=("memoria",), expandir=False)["expansao"] == []


def test_expansao_continua_respeitando_acl(mem):
    from forja.dominio.erros import ErroDominio

    mem.criar(Principal("d", frozenset({"empresa/acme"})), MemoriaIn(
        tipo="semantica", titulo="Login interno", conteudo="credencial secreta", namespace="empresa/acme"))
    assert not mem.buscar(P, "autenticar", ["publico"], fontes=("memoria",))["resultados"]  # sinonimo nao fura a ACL
    with pytest.raises(ErroDominio):
        mem.buscar(P, "autenticar", ["empresa/acme"])


# ------------------------------------------------------------------ grafo como ranker
def test_grafo_traz_memoria_relacionada_que_o_texto_nao_menciona(mem):
    erro = mem.criar_no(P, NoIn(tipo="Erro", nome="TimeoutDeConexao", namespace="publico"))
    solucao = mem.criar_no(P, NoIn(tipo="Solucao", nome="BackoffExponencial", namespace="publico"))
    mem.criar_aresta(P, ArestaIn(origem=solucao["id"], destino=erro["id"], tipo="CORRIGE", namespace="publico"))
    m = mem.criar(P, MemoriaIn(tipo="procedimental", titulo="Receita de repetição", namespace="publico",
                               conteudo="Aguardar e tentar de novo aumentando o intervalo.", refs=[solucao["id"]]))
    # a consulta cita o ERRO; a memoria so referencia a SOLUCAO (vizinha): o texto nao tem nenhum termo em comum
    r = mem.buscar(P, "TimeoutDeConexao", ["publico"], fontes=("memoria",))
    achada = [x for x in r["resultados"] if x["id"] == m["id"]]
    assert achada and "CORRIGE" in achada[0]["via_grafo"]
    sem = mem.buscar(P, "TimeoutDeConexao", ["publico"], fontes=("memoria",), usar_grafo=False)
    assert not [x for x in sem["resultados"] if x["id"] == m["id"]]


def test_grafo_nao_vaza_memoria_de_outro_namespace(mem):
    privado = Principal("d", frozenset({"empresa/acme"}))
    no = mem.criar_no(privado, NoIn(tipo="Erro", nome="ErroPrivado", namespace="empresa/acme"))
    mem.criar(privado, MemoriaIn(tipo="episodica", titulo="Solucao interna", conteudo="segredo", namespace="empresa/acme",
                                 refs=[no["id"]]))
    assert not mem.buscar(P, "ErroPrivado", ["publico"])["resultados"]


# ------------------------------------------------------------------ simbolos de documentos e escopo de extensoes
def test_secoes_de_markdown_viram_pontos_de_entrada():
    simbolos = indexador.extrair_simbolos_generico(
        "markdown", "# Titulo\ntexto\n## Regras de nomenclatura\n```\n# comentario em bloco de codigo\n```\n### Commits #\n")
    assert [(s.nome, s.linha) for s in simbolos] == [("Titulo", 1), ("Regras de nomenclatura", 3), ("Commits", 7)]


def test_simbolos_js_ts_powershell_sql():
    js = indexador.extrair_simbolos_generico("typescript", (
        "export async function carregar() {}\nclass Painel {}\nexport interface Config {}\ntype Id = string;\n"
        "const somar = (a, b) => a + b;\nconst x = 1;\n"))
    assert {s.nome for s in js} == {"carregar", "Painel", "Config", "Id", "somar"}
    ps = indexador.extrair_simbolos_generico("powershell", "function Get-Dados {\n}\n# function Falso\n")
    assert [s.nome for s in ps] == ["Get-Dados"]
    sql = indexador.extrair_simbolos_generico("sql", "CREATE TABLE IF NOT EXISTS clientes (id int);\ncreate view v_ativos as select 1;")
    assert [(s.nome, s.tipo) for s in sql] == [("clientes", "tabela"), ("v_ativos", "view")]


def test_busca_acha_secao_de_documento_de_boas_praticas(mem, tmp_path):
    raiz = tmp_path / "repos" / "docs"
    raiz.mkdir(parents=True)
    (raiz / "arquitetura.md").write_text("# Arquitetura\n## Camadas e responsabilidades\ntexto\n## Nomenclatura\nsnake_case\n",
                                         encoding="utf-8")
    mem.ingerir_diretorio(P, IngerirIn(namespace="publico", raiz=str(raiz), repositorio="docs"))
    r = mem.buscar(P, "nomenclatura", ["publico"], fontes=("codigo",))["resultados"][0]
    assert r["caminho"] == "arquitetura.md" and r["definicao"]["tipo"] == "secao" and r["definicao"]["nome"] == "Nomenclatura"


def test_extensoes_restringem_o_escopo_da_ingestao(mem, tmp_path):
    raiz = tmp_path / "repos" / "misto"
    raiz.mkdir(parents=True)
    (raiz / "a.py").write_text("class A:\n    pass\n", encoding="utf-8")
    (raiz / "dump.json").write_text('{"dado": "volumoso"}', encoding="utf-8")
    (raiz / "pagina.html").write_text("<html>capturada</html>", encoding="utf-8")
    r = mem.ingerir_diretorio(P, IngerirIn(namespace="publico", raiz=str(raiz), repositorio="m", extensoes=[".py", "md"]))
    assert r["novos"] == 1
    assert not mem.buscar(P, "volumoso", ["publico"])["resultados"]
    with pytest.raises(ValueError):
        IngerirIn(namespace="publico", raiz="x", repositorio="r", extensoes=[".exe"])


def test_fonte_aceita_para_ingestao_de_memoria_com_proveniencia():
    assert FonteIn(tipo="documento", caminho="docs/a.md").caminho == "docs/a.md"


# ------------------------------------------------------------------ desempenho estrutural (sem depender de relogio)
def _contagens(repo) -> tuple[int, int, int]:
    from sqlalchemy import text

    with repo.leitura() as t:
        trechos = t.s.execute(text("SELECT count(*) FROM codigo_trecho")).scalar()
        fts = t.s.execute(text("SELECT count(*) FROM codigo_fts")).scalar()
        orfaos = t.s.execute(text("SELECT count(*) FROM codigo_fts WHERE rowid NOT IN (SELECT id FROM codigo_trecho)")).scalar()
    return trechos, fts, orfaos


def test_mapa_de_trechos_permanece_1_para_1_com_o_fts(mem, repo, tmp_path):
    raiz = tmp_path / "repos" / "perf"
    raiz.mkdir(parents=True)
    arq = raiz / "a.py"
    arq.write_text("\n".join(f"def f{i}():\n    return {i}" for i in range(80)), encoding="utf-8")  # varios trechos
    (raiz / "b.py").write_text("class B:\n    pass\n", encoding="utf-8")
    d = IngerirIn(namespace="publico", raiz=str(raiz), repositorio="perf")
    mem.ingerir_diretorio(P, d)
    trechos, fts, orfaos = _contagens(repo)
    assert trechos == fts > 2 and orfaos == 0
    arq.write_text("def novo():\n    return 1\n", encoding="utf-8")  # alteracao: remove os trechos antigos
    mem.ingerir_diretorio(P, d)
    trechos, fts, orfaos = _contagens(repo)
    assert trechos == fts == 2 and orfaos == 0
    arq.unlink()
    mem.ingerir_diretorio(P, d)
    trechos, fts, orfaos = _contagens(repo)
    assert trechos == fts == 1 and orfaos == 0
    assert not mem.buscar(P, "novo", ["publico"], fontes=("codigo",))["resultados"]


def test_busca_de_simbolo_usa_indices_e_nao_varre_a_tabela(repo):
    from sqlalchemy import text

    from forja.adapters.sqlite.memoria_fts import simbolos_buscar

    with repo.leitura() as t:
        plano = " ".join(str(r[-1]) for r in t.s.execute(text(
            "EXPLAIN QUERY PLAN SELECT s.nome FROM simbolo s JOIN arquivo_indexado a ON a.id = s.arquivo_id "
            "WHERE a.estado = 'ativo' AND (s.nome_norm = 'abc' OR s.nome_final = 'abc' OR "
            "(s.nome_norm >= 'abc' AND s.nome_norm < 'abd'))")))
        assert "ix_simbolo_nome_norm" in plano or "ix_simbolo_nome_final" in plano, plano
        assert simbolos_buscar(t, ["abc"], ["publico"], 5) == []  # roda sem erro num banco vazio


def test_consulta_de_trecho_por_arquivo_e_linha_usa_o_indice(repo):
    from sqlalchemy import text

    with repo.leitura() as t:
        plano = " ".join(str(r[-1]) for r in t.s.execute(text(
            "EXPLAIN QUERY PLAN SELECT id FROM codigo_trecho WHERE arquivo_id = 'x' AND linha_ini <= 5 AND linha_fim >= 5")))
    assert "ix_codigo_trecho_arquivo_linha" in plano, plano


def test_nome_normalizado_e_componente_final_sao_gravados(mem, repo, tmp_path):
    from sqlalchemy import text

    raiz = tmp_path / "repos" / "norm"
    raiz.mkdir(parents=True)
    (raiz / "m.py").write_text("class ClienteAcp:\n    def Conectar(self):\n        pass\n", encoding="utf-8")
    mem.ingerir_diretorio(P, IngerirIn(namespace="publico", raiz=str(raiz), repositorio="norm"))
    with repo.leitura() as t:
        linhas = {n: (a, b) for n, a, b in t.s.execute(text("SELECT nome, nome_norm, nome_final FROM simbolo"))}
    assert linhas["ClienteAcp"] == ("clienteacp", "clienteacp")
    assert linhas["ClienteAcp.Conectar"] == ("clienteacp.conectar", "conectar")
