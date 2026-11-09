"""Ferramentas N0: outline, resumo de pytest e resumo de diff."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from forja.dominio.erros import NaoEncontrado, ValidacaoDominio
from forja.ferramentas.diff import resumir_diff
from forja.ferramentas.outline import outline_arquivo
from forja.ferramentas.testes import resumir_pytest

# ---------------------------------------------------------------- outline


def test_outline_lista_simbolos_com_linha_e_nao_devolve_o_corpo(tmp_path: Path):
    corpo = "\n".join(f"        x{i} = {i}" for i in range(300))
    (tmp_path / "m.py").write_text(f"import os\n\nclass Servico:\n    def rodar(self):\n{corpo}\n\ndef util():\n    pass\n",
                                   encoding="utf-8")
    r = outline_arquivo(tmp_path, "m.py")
    assert "Servico" in r.resumo and "rodar" in r.resumo and "util" in r.resumo
    assert "x299" not in r.resumo
    assert {"Servico", "Servico.rodar", "util"} <= {s["nome"] for s in r.dados["simbolos"]}
    assert "metodo Servico.rodar(self)" in r.resumo
    assert r.dados["extrator"] == "ast" and len(r.dados["sha256"]) == 64
    assert r.tokens_resumo < r.tokens_origem / 5
    assert r.conteudo_nao_confiavel


def test_outline_aponta_a_linha_correta(tmp_path: Path):
    (tmp_path / "m.py").write_text("\n\n\ndef alvo():\n    pass\n", encoding="utf-8")
    r = outline_arquivo(tmp_path, "m.py")
    assert next(s for s in r.dados["simbolos"] if s["nome"] == "alvo")["linha"] == 4


@pytest.mark.parametrize("caminho", ["../fora.py", "sub/../../fora.py", ".env", "id_rsa", "credentials.json"])
def test_outline_recusa_fora_da_raiz_e_arquivos_sensiveis(tmp_path: Path, caminho: str):
    raiz = tmp_path / "raiz"
    raiz.mkdir()
    (tmp_path / "fora.py").write_text("def x(): pass\n", encoding="utf-8")
    (raiz / ".env").write_text("TOKEN=abc\n", encoding="utf-8")
    with pytest.raises((ValidacaoDominio, NaoEncontrado)):
        outline_arquivo(raiz, caminho)


def test_outline_nao_segue_link_simbolico_nem_para_dentro_da_raiz(tmp_path: Path):
    (tmp_path / "real.py").write_text("def x(): pass\n", encoding="utf-8")
    try:
        (tmp_path / "atalho.py").symlink_to(tmp_path / "real.py")
    except OSError:
        pytest.skip("sem permissao para criar link simbolico neste ambiente")
    with pytest.raises(ValidacaoDominio, match="simbolicos"):
        outline_arquivo(tmp_path, "atalho.py")


def test_outline_recusa_binario_e_inexistente(tmp_path: Path):
    (tmp_path / "b.py").write_bytes(b"\x00\x01\x02def x(): pass")
    with pytest.raises(ValidacaoDominio):
        outline_arquivo(tmp_path, "b.py")
    with pytest.raises(NaoEncontrado):
        outline_arquivo(tmp_path, "nao_existe.py")


def test_outline_arquivo_com_erro_de_sintaxe_avisa_e_nao_quebra(tmp_path: Path):
    (tmp_path / "q.py").write_text("def ok():\n    pass\n\ndef quebrado(:\n", encoding="utf-8")
    r = outline_arquivo(tmp_path, "q.py")
    assert any("parse parcial" in a for a in r.avisos)


# ---------------------------------------------------------------- pytest


@pytest.fixture(scope="module")
def saida_real(tmp_path_factory) -> str:
    d = tmp_path_factory.mktemp("proj")
    (d / "test_a.py").write_text(
        "def test_ok():\n    assert 1 == 1\n\n"
        "def test_soma():\n    esperado = 5\n    assert 2 + 2 == esperado\n\n"
        "def test_excecao():\n    raise ValueError('quebrou aqui')\n",
        encoding="utf-8",
    )
    p = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-rfE", "test_a.py"], cwd=d,
                       capture_output=True, text=True, encoding="utf-8", check=False)
    assert p.returncode == 1
    return p.stdout


def test_resumo_de_pytest_real_traz_veredito_contagens_e_causa(saida_real: str):
    r = resumir_pytest(saida_real)
    assert r.dados["veredito"] == "REPROVADO"
    assert r.dados["contagens"]["failed"] == 2 and r.dados["contagens"]["passed"] == 1
    ids = [f["id"] for f in r.dados["falhas"]]
    assert any(i.endswith("test_soma") for i in ids) and any(i.endswith("test_excecao") for i in ids)
    assert "quebrou aqui" in r.resumo
    assert "assert (2 + 2) == 5" in r.resumo or "assert 4 == 5" in r.resumo
    assert r.tokens_resumo < r.tokens_origem


def test_resumo_de_pytest_aprovado_e_sem_resultado():
    ok = resumir_pytest("....\n396 passed in 100.5s\n")
    assert ok.dados["veredito"] == "APROVADO" and ok.dados["segundos"] == 100.5
    vazio = resumir_pytest("Traceback: nada\n")
    assert vazio.dados["veredito"] == "SEM_RESULTADO" and vazio.avisos


def test_resumo_de_pytest_limita_falhas_e_redige_segredos():
    linhas = [f"FAILED t.py::test_{i} - AssertionError: x" for i in range(25)]
    linhas.append("FAILED t.py::test_s - AssertionError: token ghp_abcdefghijklmnopqrstuvwxyz0123456789")
    r = resumir_pytest("\n".join(linhas) + "\n26 failed in 1.0s\n", limite=10)
    assert r.truncado and "+16 falhas omitidas" in r.resumo
    seg = resumir_pytest(linhas[-1] + "\n1 failed in 1.0s\n")
    assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in seg.resumo


def test_resumo_nao_aprova_quando_ha_erros_de_coleta():
    r = resumir_pytest("ERROR t.py - ImportError: x\n1 error in 0.1s\n")
    assert r.dados["veredito"] == "REPROVADO"


# ---------------------------------------------------------------- diff

DIFF = """diff --git a/forja/a.py b/forja/a.py
index 111..222 100644
--- a/forja/a.py
+++ b/forja/a.py
@@ -10,3 +10,4 @@ class Servico:
 linha
-velha
+nova
+token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"
diff --git a/forja/migrations/versions/0006_x.py b/forja/migrations/versions/0006_x.py
new file mode 100644
--- /dev/null
+++ b/forja/migrations/versions/0006_x.py
@@ -0,0 +1,2 @@
+a = 1
+b = 2
diff --git a/velho.txt b/novo.txt
similarity index 90%
rename from velho.txt
rename to novo.txt
diff --git a/img.png b/img.png
Binary files a/img.png and b/img.png differ
"""


def test_resumo_de_diff_estados_contagens_contexto_e_riscos():
    r = resumir_diff(DIFF)
    por = {a["caminho"]: a for a in r.dados["arquivos"]}
    assert por["forja/a.py"]["adicoes"] == 2 and por["forja/a.py"]["remocoes"] == 1
    assert por["forja/migrations/versions/0006_x.py"]["estado"] == "A"
    assert por["novo.txt"]["estado"] == "R" and por["img.png"]["estado"] == "B"
    assert "class Servico" in r.resumo
    assert "migracao/SQL" in r.resumo
    assert "possivel segredo nas linhas [12]" in r.resumo
    assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in r.resumo
    assert "codigo alterado sem alteracao em testes" in r.avisos


def test_resumo_de_diff_sem_aviso_quando_ha_teste_e_marca_remocao_grande():
    diff = (
        "diff --git a/forja/a.py b/forja/a.py\n--- a/forja/a.py\n+++ b/forja/a.py\n@@ -1,300 +1,0 @@\n"
        + "".join(f"-l{i}\n" for i in range(250))
        + "diff --git a/tests/test_a.py b/tests/test_a.py\n--- a/tests/test_a.py\n+++ b/tests/test_a.py\n@@ -1 +1 @@\n-a\n+b\n"
    )
    r = resumir_diff(diff)
    assert not r.avisos
    assert "remocao grande (250 linhas)" in r.resumo


def test_resumo_de_diff_limita_arquivos():
    diff = "".join(f"diff --git a/f{i}.txt b/f{i}.txt\n@@ -1 +1 @@\n-a\n+b\n" for i in range(60))
    r = resumir_diff(diff)
    assert r.truncado and "+20 arquivos omitidos" in r.resumo and len(r.dados["arquivos"]) == 40
