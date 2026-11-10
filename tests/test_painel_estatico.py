"""Regras de seguranca e integridade do painel estatico (sem navegador): CSP, sem innerHTML/eval, imports e ids coerentes.

O comportamento real no navegador e verificado por scripts/inspecionar_painel.py (Playwright, opcional).
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from forja.adapters.agentes_mock.mock import AgenteMock
from forja.config import Configuracoes
from forja.servidor.app import criar_app

RAIZ = Path(__file__).resolve().parents[1] / "forja" / "painel" / "estatico"
JS = sorted((RAIZ / "js").rglob("*.js"))
HTML = (RAIZ / "index.html").read_text(encoding="utf-8")
PROIBIDOS = ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "setTimeout(\"")


def test_ha_modulos_e_nenhum_script_legado():
    assert len(JS) >= 12 and not (RAIZ / "app.js").exists()


@pytest.mark.parametrize("arq", JS, ids=lambda p: p.name)
def test_js_nao_usa_apis_de_injecao_de_html_nem_eval(arq: Path):
    texto = re.sub(r"(?m)(^|\s)//.*$", "", arq.read_text(encoding="utf-8"))  # comentarios podem citar as APIs proibidas
    achados = [p for p in PROIBIDOS if p in texto]
    assert not achados, f"{arq.name} usa {achados}: conteudo do backend e dado, so textContent/DOM"


def test_token_so_e_tocado_em_api_js_e_no_formulario_de_acesso():
    donos = {a.name for a in JS if "forja_token" in a.read_text(encoding="utf-8")}
    assert donos == {"api.js"}
    for a in JS:  # token nunca vai para console, DOM ou armazenamento persistente
        t = a.read_text(encoding="utf-8")
        assert "console.log" not in t and "localStorage.setItem(\"forja_token\"" not in t


def test_html_tem_csp_restritiva_sem_script_ou_handler_inline():
    csp = re.search(r'http-equiv="Content-Security-Policy"\s+content="([^"]+)"', HTML).group(1)
    assert "default-src 'self'" in csp and "object-src 'none'" in csp and "base-uri 'none'" in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert not re.search(r"<script(?![^>]*\bsrc=)", HTML) and not re.search(r"\son\w+\s*=", HTML)
    assert not re.search(r'(src|href)="https?://', HTML)  # nenhum recurso externo


def test_html_e_semantico_e_acessivel():
    for marca in ('lang="pt-BR"', 'role="banner"', "<main", 'role="contentinfo"', 'aria-label="Áreas do orquestrador"',
                  'class="pular"', 'aria-live="polite"', 'role="tablist"'):
        assert marca in HTML, marca
    assert "prefers-reduced-motion" in (RAIZ / "app.css").read_text(encoding="utf-8")


def test_todo_import_relativo_existe():
    for arq in JS:
        for alvo in re.findall(r'from "(\.{1,2}/[^"]+)"', arq.read_text(encoding="utf-8")):
            assert (arq.parent / alvo).resolve().exists(), f"{arq.name} importa {alvo} inexistente"


def test_todo_id_usado_pelo_js_existe_no_html_ou_e_criado_em_js():
    ids_html = set(re.findall(r'\bid="([\w-]+)"', HTML))
    criados = set()
    for a in JS:
        criados |= set(re.findall(r'\bid: "([\w-]+)"', a.read_text(encoding="utf-8")))
    for a in JS:
        t = a.read_text(encoding="utf-8")
        usados = set(re.findall(r'\$\("#([\w-]+)"\)', t)) | set(re.findall(r'getElementById\("([\w-]+)"\)', t))
        faltando = {i for i in usados if i not in ids_html and i not in criados and not i.startswith("aba-")}
        assert not faltando, f"{a.name} referencia ids inexistentes: {faltando}"


@pytest.fixture
def cli(tmp_path: Path, _db_migrado: Path) -> Iterator[TestClient]:
    (tmp_path / "data").mkdir()
    shutil.copyfile(_db_migrado, tmp_path / "data" / "forja.sqlite3")
    cfg = Configuracoes(_env_file=None, app_data_dir=tmp_path / "data", app_log_dir=tmp_path / "logs",  # type: ignore[call-arg]
                        app_api_token="token-de-teste-com-tamanho-suficiente", app_allowed_hosts="testserver")
    with TestClient(criar_app(cfg, AgenteMock())) as c:
        yield c


def test_servidor_entrega_shell_css_e_todos_os_modulos(cli: TestClient):
    r = cli.get("/")
    assert r.status_code == 200 and "Content-Security-Policy" in r.text and r.headers["x-content-type-options"] == "nosniff"
    assert cli.get("/estatico/app.css").status_code == 200
    for arq in JS:
        rel = arq.relative_to(RAIZ).as_posix()
        resp = cli.get(f"/estatico/{rel}")
        assert resp.status_code == 200, rel
        assert "javascript" in resp.headers["content-type"], (rel, resp.headers["content-type"])


def test_shell_e_estatico_nao_exigem_token_mas_a_api_exige(cli: TestClient):
    assert cli.get("/").status_code == 200
    assert cli.get("/api/v1/kanban").status_code in (401, 403)


def test_todos_os_modulos_js_tem_sintaxe_valida_como_esm():
    """`node --check arquivo.js` aceita modulo ESM invalido (falso positivo observado no Node 24); so a checagem por stdin com
    --input-type=module detecta. Regressao: uma template string corrompida passou pelo node --check e quebrou o painel."""
    import shutil
    import subprocess

    import pytest

    node = shutil.which("node")
    if node is None:
        pytest.skip("node nao instalado")
    ruins = []
    for js in JS:
        r = subprocess.run([node, "--input-type=module", "--check"], input=js.read_bytes(), capture_output=True, timeout=30)  # noqa: S603
        if r.returncode != 0:
            ruins.append(f"{js.name}: {r.stderr.decode('utf-8', 'replace').splitlines()[:3]}")
    assert not ruins, ruins
