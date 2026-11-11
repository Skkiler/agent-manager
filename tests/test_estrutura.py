"""Indice estrutural de codigo (codigo.estrutura): definicoes, referencias, dependencias, mapa, cache e seguranca."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from forja.dominio.erros import ValidacaoDominio
from forja.ferramentas import estrutura as E
from forja.ferramentas.catalogo import Catalogo


@pytest.fixture
def projeto(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "fila.py").write_text(
        "class Fila:\n    def enfileirar(self, x):\n        return x\n\n\ndef criar_fila():\n    return Fila()\n", encoding="utf-8")
    (tmp_path / "app" / "servico.py").write_text(
        "from .fila import criar_fila\nimport json\n\n\ndef processar():\n    f = criar_fila()\n    f.enfileirar(1)\n    return json.dumps(1)\n",
        encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_servico.py").write_text("from app.servico import processar\n\n\ndef test_p():\n    assert processar()\n",
                                                       encoding="utf-8")
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "ui.js").write_text('export function el(t) { return t; }\n', encoding="utf-8")
    (tmp_path / "web" / "main.js").write_text('import { el } from "./ui.js";\nconst x = el("div");\n', encoding="utf-8")
    (tmp_path / "quebrado.py").write_text("def (:\n", encoding="utf-8")
    (tmp_path / ".env").write_text("SEGREDO=nao-pode-aparecer\n", encoding="utf-8")
    E.limpar_cache()
    return tmp_path


def test_definicao_de_classe_metodo_e_funcao(projeto):
    r = E.estrutura_codigo(projeto, ".", "definicao", "enfileirar")
    assert r.dados["definicoes"][0] | {"assinatura": ""} == {"caminho": "app/fila.py", "linha": 2, "fim": 3, "tipo": "metodo",
                                                              "nome": "Fila.enfileirar", "assinatura": ""}
    assert E.estrutura_codigo(projeto, ".", "definicao", "Fila").dados["definicoes"][0]["fim"] == 3


def test_referencias_excluem_a_propria_definicao(projeto):
    r = E.estrutura_codigo(projeto, ".", "referencias", "criar_fila")
    linhas = {(x["caminho"], x["linha"]) for x in r.dados["referencias"]}
    assert ("app/servico.py", 1) in linhas and ("app/servico.py", 6) in linhas and ("app/fila.py", 6) not in linhas
    js = E.estrutura_codigo(projeto, ".", "referencias", "el")
    assert any(x["caminho"] == "web/main.js" for x in js.dados["referencias"])


def test_dependencias_resolvem_import_relativo_e_js(projeto):
    r = E.estrutura_codigo(projeto, ".", "dependencias", "app/fila.py")
    assert r.dados["importado_por"] == ["app/servico.py"]
    s = E.estrutura_codigo(projeto, ".", "dependencias", "app/servico.py")
    assert s.dados["importa"] == ["app/fila.py"] and s.dados["externos"] == ["json"]
    assert E.estrutura_codigo(projeto, ".", "dependencias", "web/main.js").dados["importa"] == ["web/ui.js"]


def test_mapa_ordena_pelo_mais_central_e_nao_quebra_com_arquivo_invalido(projeto):
    r = E.estrutura_codigo(projeto, ".", "mapa")
    assert r.dados["mapa"][0]["caminho"] in ("app/fila.py", "app/servico.py")
    assert "quebrado.py" in r.dados["erros_de_analise"]
    assert "nao-pode-aparecer" not in r.resumo + str(r.dados)  # .env nunca entra no indice


def test_testes_afetados_seguem_os_imports(projeto):
    assert E.arquivos_de_teste_afetados(projeto, ["app/fila.py"]) == ["tests/test_servico.py"]


def test_cache_incremental_reanalisa_so_o_que_mudou(projeto):
    E.estrutura_codigo(projeto, ".", "mapa")
    antes = dict(E._cache)
    alvo = projeto / "app" / "fila.py"
    alvo.write_text(alvo.read_text(encoding="utf-8") + "\n\ndef nova():\n    pass\n", encoding="utf-8")
    os.utime(alvo, ns=(alvo.stat().st_atime_ns, alvo.stat().st_mtime_ns + 10_000_000))
    assert E.estrutura_codigo(projeto, ".", "definicao", "nova").dados["definicoes"]
    mudou = [k for k in E._cache if E._cache[k][2] is not antes.get(k, (0, 0, None))[2]]
    assert mudou == [str(alvo.resolve())] or mudou == [str(alvo)]


def test_entrada_invalida_e_erro_de_validacao(projeto):
    with pytest.raises(ValidacaoDominio):
        E.estrutura_codigo(projeto, ".", "definicao", "")
    with pytest.raises(ValidacaoDominio):
        E.estrutura_codigo(projeto, ".", "dependencias", ".env")


def test_no_catalogo_com_raiz_autorizada(projeto):
    c = Catalogo(raizes=(projeto,))
    r = c.executar("codigo.estrutura", {"caminho": str(projeto), "operacao": "definicao", "alvo": "criar_fila"})
    assert r["dados"]["definicoes"][0]["caminho"] == "app/fila.py"
    assert any(f["id"] == "codigo.estrutura" for f in c.listar())
