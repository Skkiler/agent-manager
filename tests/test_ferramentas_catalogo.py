"""Catalogo de ferramentas N0: logs, segredos, mapa, esquema, conversor, orcamento, amostra, fallback e API."""

from __future__ import annotations

import csv
import io
import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from forja.adapters.agentes_mock.mock import AgenteMock
from forja.config import Configuracoes
from forja.dominio.erros import NaoEncontrado, ValidacaoDominio
from forja.ferramentas.amostra import amostra_arquivo
from forja.ferramentas.catalogo import Catalogo
from forja.ferramentas.conversor import converter
from forja.ferramentas.esquema import inspecionar_sqlite
from forja.ferramentas.logs import agrupar_falhas, assinatura
from forja.ferramentas.mapa import mapa_repositorio
from forja.ferramentas.orcamento import orcar_tokens
from forja.ferramentas.segredos import varrer
from forja.servidor.app import criar_app

TOKEN = "token-de-teste-com-tamanho-suficiente"
FALSO_TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"  # sintetico, nunca real

# ---------------------------------------------------------------- logs


def test_assinatura_normaliza_numeros_ids_timestamps_e_caminhos():
    a = assinatura("2026-11-08 10:00:01,123 ERROR falha na tarefa 123 em C:\\dados\\x.csv id 3f2a9c4b-1111-2222-3333-444455556666")
    b = assinatura("2026-11-09 11:22:33,999 ERROR falha na tarefa 987 em C:\\outro\\y.csv id aaaaaaaa-1111-2222-3333-444455556666")
    assert a == b


def test_agrupar_falhas_conta_ordena_e_ignora_linhas_sem_erro():
    log = "\n".join(
        [f"2026-01-01 10:00:0{i} INFO ok {i}" for i in range(5)]
        + [f"ERROR timeout ao chamar servico {i}" for i in range(7)]
        + ["Traceback (most recent call last):", "ValueError: valor 42 invalido", "ValueError: valor 77 invalido"]
    )
    r = agrupar_falhas(log)
    g = r.dados["grupos"]
    assert g[0]["contagem"] == 7 and "timeout" in g[0]["exemplo"]
    assert any(x["contagem"] == 2 and "ValueError" in x["exemplo"] for x in g)
    assert r.dados["niveis"]["ERROR"] == 7 and r.dados["niveis"]["INFO"] == 5
    assert r.tokens_resumo < r.tokens_origem


def test_agrupar_falhas_limita_grupos_e_redige_segredos():
    linhas = [f"ERROR modulo{chr(97 + i)} quebrou" for i in range(15)] + [f"ERROR token {FALSO_TOKEN}"]
    r = agrupar_falhas("\n".join(linhas), limite=5)
    assert r.truncado and len(r.dados["grupos"]) == 5
    assert FALSO_TOKEN not in agrupar_falhas("\n".join(linhas), limite=30).resumo


# ---------------------------------------------------------------- segredos


@pytest.fixture
def repo_falso(tmp_path: Path) -> Path:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("x = 1\nTOKEN = '" + FALSO_TOKEN + "'\n", encoding="utf-8")
    (tmp_path / "pkg" / "b.py").write_text("def ok():\n    return 1\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("print('oi')\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_b.py").write_text("def test_b(): pass\n", encoding="utf-8")
    (tmp_path / ".env").write_text("SEGREDO=valor-nao-lido-1234567890\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    return tmp_path


def test_varrer_acha_segredo_sem_devolver_o_valor_e_nao_abre_arquivo_sensivel(repo_falso: Path):
    r = varrer(repo_falso)
    assert {"arquivo": "pkg/a.py", "linha": 2} in r.dados["achados"]
    assert FALSO_TOKEN not in r.resumo and FALSO_TOKEN not in json.dumps(r.dados)
    assert ".env" in r.dados["sensiveis"]
    assert "valor-nao-lido" not in r.resumo + json.dumps(r.dados)
    assert not any(a["arquivo"] == "pkg/b.py" for a in r.dados["achados"])
    assert any("nao prova" in a for a in r.avisos)


@pytest.mark.parametrize(
    ("linha", "suspeito"),
    [
        ('senha = "abc12345xyz"', True),
        ("api_key: 'abcdefgh1234'", True),
        ('{"password": "umasenhalonga1"}', True),
        ("Authorization: Bearer abcdefghijklmnop", True),
        ("AKIA" + "ABCDEFGHIJKLMNOP", True),
        ("-----BEGIN RSA PRIVATE KEY-----", True),
        ("token = obter_token(cfg)", False),  # expressao, nao literal
        ("let token = sessionStorage.getItem('x');", False),
        ('senha = "curta"', False),  # literal curto demais para ser credencial
        ("token: str | None = Query(default=None)", False),
        ("tokens_input = 120", False),
    ],
)
def test_detector_distingue_credencial_de_nome_de_variavel(linha: str, suspeito: bool):
    from forja.ferramentas.segredos import suspeita

    assert suspeita(linha) is suspeito


def test_varrer_um_arquivo_e_recusa_fora_da_raiz(repo_falso: Path, tmp_path_factory):
    assert varrer(repo_falso, "pkg/b.py").dados["achados"] == []
    with pytest.raises(ValidacaoDominio):
        varrer(repo_falso, "..")


# ---------------------------------------------------------------- mapa


def test_mapa_do_repositorio(repo_falso: Path):
    r = mapa_repositorio(repo_falso)
    assert r.dados["linguagens"]["python"] == 4 and r.dados["arquivos"] >= 4
    assert "main.py" in r.dados["entradas"] and "pyproject.toml" in r.dados["config"]
    assert r.dados["arquivos_de_teste"] == 1
    assert ".env" not in r.resumo
    sub = mapa_repositorio(repo_falso, "pkg")
    assert sub.dados["arquivos"] == 2
    with pytest.raises(ValidacaoDominio):
        mapa_repositorio(repo_falso, "main.py")  # nao e diretorio


# ---------------------------------------------------------------- esquema


def test_inspecionar_banco_real_migrado_omite_sombras_do_fts(tmp_path: Path, _db_migrado: Path):
    shutil.copyfile(_db_migrado, tmp_path / "x.sqlite3")
    r = inspecionar_sqlite(tmp_path, "x.sqlite3")
    por = {t["tabela"]: t for t in r.dados["tabelas"]}
    assert {"tarefa", "execucao", "memoria"} <= set(por)
    assert por["memoria_fts"]["virtual"] and r.dados["tabelas_sombra_omitidas"] >= 1
    assert not any(n.startswith("memoria_fts_") for n in por)
    assert any(c["nome"] == "estado" for c in por["tarefa"]["colunas"])
    assert r.tokens_resumo < r.tokens_origem


def test_inspecionar_recusa_arquivo_que_nao_e_sqlite_e_nao_escreve(tmp_path: Path, _db_migrado: Path):
    (tmp_path / "f.sqlite3").write_text("nao sou um banco", encoding="utf-8")
    with pytest.raises(ValidacaoDominio, match="SQLite"):
        inspecionar_sqlite(tmp_path, "f.sqlite3")
    shutil.copyfile(_db_migrado, tmp_path / "x.sqlite3")
    antes = (tmp_path / "x.sqlite3").read_bytes()
    inspecionar_sqlite(tmp_path, "x.sqlite3")
    assert (tmp_path / "x.sqlite3").read_bytes() == antes


# ---------------------------------------------------------------- conversor


DADOS = [{"nome": "Ana", "nota": 9, "obs": "a|b"}, {"nome": "Bia", "nota": 7, "obs": None}]


def test_conversao_ida_e_volta_preserva_os_registros():
    j = json.dumps(DADOS)
    for via in ("csv", "md", "jsonl"):
        meio = converter(j, "json", via).resumo
        volta = json.loads(converter(meio, via, "json").resumo)
        assert [v["nome"] for v in volta] == ["Ana", "Bia"], via
        assert volta[0]["obs"] == "a|b", via


def test_csv_neutraliza_formulas_por_padrao_e_permite_desligar():
    j = json.dumps([{"a": "=HYPERLINK(\"http://x\")", "b": "+1", "c": "normal"}])
    r = converter(j, "json", "csv")
    linha = next(csv.reader(io.StringIO(r.resumo)), None) and list(csv.reader(io.StringIO(r.resumo)))[1]
    assert linha[0].startswith("'=") and linha[1].startswith("'+") and linha[2] == "normal"
    assert any("CSV injection" in a for a in r.avisos)
    cru = converter(j, "json", "csv", neutralizar_formulas=False).resumo
    assert "\n=HYPERLINK" in cru or ',"=HYPERLINK' in cru or cru.splitlines()[1].startswith(('"=', "="))


@pytest.mark.parametrize(("texto", "de"), [("{nao json", "json"), ("[1, 2]", "json"), ("so uma linha", "md")])
def test_conversao_recusa_entrada_invalida(texto: str, de: str):
    with pytest.raises(ValidacaoDominio):
        converter(texto, de, "csv")


def test_conversao_recusa_formato_desconhecido_e_excesso_de_registros():
    with pytest.raises(ValidacaoDominio):
        converter("[]", "json", "xml")
    with pytest.raises(ValidacaoDominio, match="registros"):
        converter(json.dumps([{"a": i} for i in range(5001)]), "json", "csv")


# ---------------------------------------------------------------- orcamento


def test_orcar_respeita_ordem_de_prioridade_pula_o_que_nao_cabe_e_aplica_teto():
    itens = [{"id": "A", "texto": "x" * 400}, {"id": "B", "texto": "x" * 2000}, {"id": "C", "texto": "x" * 200}]
    r = orcar_tokens(itens, orcamento=200)  # A=100, B=500, C=50
    assert [i["id"] for i in r.dados["cabem"]] == ["A", "C"] and r.dados["usados"] == 150
    assert r.dados["fora"][0]["id"] == "B"
    t = orcar_tokens(itens, orcamento=1000, teto_item=120)
    assert [i["id"] for i in t.dados["cabem"]] == ["A", "C"]
    assert t.dados["fora"][0]["motivo"] == "acima do teto do item"
    with pytest.raises(ValidacaoDominio):
        orcar_tokens(itens, orcamento=0)


# ---------------------------------------------------------------- amostra


def test_amostra_numera_limita_e_recusa_binario(tmp_path: Path):
    (tmp_path / "t.txt").write_text("\n".join(f"linha {i}" for i in range(1, 101)), encoding="utf-8")
    r = amostra_arquivo(tmp_path, "t.txt", inicio=10, linhas=3)
    assert r.resumo.splitlines()[1:] == ["10: linha 10", "11: linha 11", "12: linha 12"]
    assert r.truncado
    assert amostra_arquivo(tmp_path, "t.txt", inicio=500).avisos
    (tmp_path / "b.bin").write_bytes(b"\x00\x01")
    with pytest.raises(ValidacaoDominio):
        amostra_arquivo(tmp_path, "b.bin")
    with pytest.raises(ValidacaoDominio):
        amostra_arquivo(tmp_path, "t.txt", linhas=999)


def test_amostra_redige_segredos_no_trecho(tmp_path: Path):
    (tmp_path / "c.txt").write_text(f"token={FALSO_TOKEN}\n", encoding="utf-8")
    assert FALSO_TOKEN not in amostra_arquivo(tmp_path, "c.txt").resumo


# ---------------------------------------------------------------- catalogo


@pytest.fixture
def cat(repo_falso: Path) -> Catalogo:
    return Catalogo((repo_falso,))


def test_catalogo_lista_com_contrato_e_disponibilidade(repo_falso: Path):
    sem = {f["id"]: f for f in Catalogo(()).listar()}
    com = {f["id"]: f for f in Catalogo((repo_falso,)).listar()}
    assert sem["codigo.outline"]["disponivel"] is False and com["codigo.outline"]["disponivel"] is True
    assert sem["logs.agrupar_falhas"]["disponivel"] is True
    assert com["codigo.outline"]["fallback"] == "texto.amostra"
    assert all(f["risco"] in ("leitura", "escrita_aprovada") and f["entrada"]["type"] == "object" for f in com.values())
    # escrita so existe como PROPOSTA (o operador aprova); e nenhuma proposta aparece disponivel sem integracao/acoes configuradas
    assert {i for i, f in com.items() if f["risco"] == "escrita_aprovada"} == {i for i in com if ".propor_" in i}
    assert not any(f["disponivel"] for f in com.values() if f["risco"] == "escrita_aprovada")


def test_catalogo_executa_valida_entrada_e_registra_custo(cat: Catalogo):
    r = cat.executar("codigo.outline", {"caminho": "pkg/b.py"})
    assert "ok" in r["resumo"] and 0 <= r["reducao"] <= 1
    with pytest.raises(ValidacaoDominio, match="entrada invalida"):
        cat.executar("codigo.outline", {"caminho": "pkg/b.py", "extra": 1})  # campos extras proibidos
    with pytest.raises(NaoEncontrado):
        cat.executar("nao.existe", {})
    e = cat.estatisticas()["codigo.outline"]
    # arquivo minusculo: o resumo e MAIOR que o bruto (a reducao e truncada em 0). A ferramenta so compensa em arquivos grandes.
    assert e["chamadas"] == 1 and e["erros"] == 0 and e["tokens_resumo"] > 0 and r["reducao"] == 0.0


def test_fallback_do_outline_para_amostra_quando_nao_ha_simbolos(cat: Catalogo, repo_falso: Path):
    (repo_falso / "notas.txt").write_text("sem simbolos\nso texto\n", encoding="utf-8")
    r = cat.executar("codigo.outline", {"caminho": "notas.txt"})
    assert r["ferramenta"] == "texto.amostra" and r["fallback_de"] == "codigo.outline"
    assert "1: sem simbolos" in r["resumo"] and any("usado texto.amostra" in a for a in r["avisos"])
    est = cat.estatisticas()
    assert est["texto.amostra"]["fallbacks"] == 1 and est["codigo.outline"]["erros"] == 1


def test_catalogo_sem_raizes_recusa_ferramentas_de_arquivo_mas_aceita_texto():
    c = Catalogo(())
    with pytest.raises(ValidacaoDominio, match="APP_TOOLS_ROOTS"):
        c.executar("codigo.outline", {"caminho": "x.py"})
    assert c.executar("git.diff_analisar", {"texto": "diff --git a/x b/x\n+a\n"})["ferramenta"] == "git.diff_analisar"


def test_fora_da_raiz_nao_revela_se_o_alvo_existe(tmp_path: Path):
    raiz = tmp_path / "raiz"
    raiz.mkdir()
    (tmp_path / "existe.py").write_text("x = 1\n", encoding="utf-8")
    c = Catalogo((raiz,))
    erros = []
    for alvo in ("../existe.py", "../nao_existe.py"):
        with pytest.raises(ValidacaoDominio) as e:
            c.executar("texto.amostra", {"caminho": alvo})
        erros.append((type(e.value), e.value.mensagem))
    assert erros[0] == erros[1]


@pytest.mark.parametrize("caminho", ["../x.py", "/etc/passwd", "C:\\Windows\\win.ini", ".env", "pkg/../../x"])
def test_catalogo_nao_sai_das_raizes_autorizadas(cat: Catalogo, caminho: str):
    for ferramenta in ("codigo.outline", "texto.amostra", "segredos.varrer"):
        with pytest.raises((ValidacaoDominio, NaoEncontrado)):
            cat.executar(ferramenta, {"caminho": caminho})


def test_caminho_absoluto_dentro_da_raiz_e_aceito(cat: Catalogo, repo_falso: Path):
    r = cat.executar("codigo.outline", {"caminho": str(repo_falso / "pkg" / "b.py")})
    assert "ok" in r["resumo"]


# ---------------------------------------------------------------- API


@pytest.fixture
def cli(tmp_path: Path, _db_migrado: Path, repo_falso: Path) -> Iterator[TestClient]:
    (tmp_path / "data").mkdir()
    shutil.copyfile(_db_migrado, tmp_path / "data" / "forja.sqlite3")
    cfg = Configuracoes(_env_file=None, app_data_dir=tmp_path / "data", app_log_dir=tmp_path / "logs",  # type: ignore[call-arg]
                        app_api_token=TOKEN, app_allowed_hosts="testserver", app_tools_roots=str(repo_falso))
    with TestClient(criar_app(cfg, AgenteMock()), headers={"Authorization": f"Bearer {TOKEN}"}) as c:
        yield c


def test_api_lista_executa_e_expoe_estatisticas(cli: TestClient):
    ids = {f["id"] for f in cli.get("/api/v1/ferramentas").json()}
    assert {"codigo.outline", "repo.mapa", "segredos.varrer", "dados.converter", "tokens.orcar"} <= ids
    r = cli.post("/api/v1/ferramentas/repo.mapa/executar", json={"entrada": {}})
    assert r.status_code == 200 and r.json()["conteudo_nao_confiavel"] is True
    assert cli.get("/api/v1/ferramentas/estatisticas").json()["repo.mapa"]["chamadas"] == 1


def test_api_erros_sao_http_corretos(cli: TestClient):
    assert cli.post("/api/v1/ferramentas/nao.existe/executar", json={"entrada": {}}).status_code == 404
    assert cli.post("/api/v1/ferramentas/codigo.outline/executar", json={"entrada": {"caminho": "../x"}}).status_code == 422
    assert cli.post("/api/v1/ferramentas/codigo.outline/executar", json={"entrada": {"caminho": "nada.py"}}).status_code == 404
    assert cli.post("/api/v1/ferramentas/codigo.outline/executar", json={"entrada": {}}).status_code == 422
    assert cli.post("/api/v1/ferramentas/repo.mapa/executar", json={"entrada": {}, "x": 1}).status_code == 422


def test_api_exige_autenticacao(cli: TestClient):
    sem = TestClient(cli.app, headers={"Host": "testserver"})
    assert sem.get("/api/v1/ferramentas").status_code in (401, 403)
    assert sem.post("/api/v1/ferramentas/repo.mapa/executar", json={"entrada": {}}).status_code in (401, 403)
