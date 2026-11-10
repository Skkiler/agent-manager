"""Separacao codigo x dados do usuario: perfil fora do Git, recusa de pasta versionada e auditoria dos arquivos rastreados."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from forja.config import Configuracoes
from forja.integracoes import ambiente
from forja.usuario.layout import (
    MARCADOR_MIGRADO,
    SUBPASTAS,
    DadosDentroDoRepositorio,
    PerfilUsuario,
    nome_do_perfil,
    raiz_do_repositorio,
    resolver_perfil,
    validar_fora_do_git,
)

GIT = shutil.which("git")


def test_nome_do_perfil_e_sanitizado_para_ser_um_nome_de_pasta_seguro():
    assert nome_do_perfil("Ana Silva") == "ana-silva" and nome_do_perfil("../../etc") == "etc"
    assert nome_do_perfil("   ") != "" and nome_do_perfil("A" * 100) == "a" * 40
    assert "/" not in nome_do_perfil("a/b\\c") and ".." not in nome_do_perfil("..")


def test_perfil_com_home_explicito_fica_em_perfis_por_usuario(tmp_path: Path):
    p = resolver_perfil({"APP_USER_HOME": str(tmp_path), "APP_PROFILE": "Maria"}, cwd=tmp_path)
    assert p.raiz == tmp_path / "perfis" / "maria" and not p.legado
    assert p.dados == p.raiz / "dados" and p.credenciais == p.raiz / "credenciais" and p.arquivo_env == p.raiz / "credenciais" / ".env"
    assert resolver_perfil({"APP_USER_HOME": str(tmp_path), "APP_PROFILE": "joana"}, cwd=tmp_path).raiz != p.raiz  # um perfil por usuario


def test_padrao_e_a_pasta_de_dados_do_sistema_e_fora_do_repositorio(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    p = resolver_perfil({}, cwd=tmp_path)
    assert not p.legado and "perfis" in p.raiz.parts
    repo = raiz_do_repositorio()
    assert repo is None or repo.resolve() not in [p.raiz.resolve(), *p.raiz.resolve().parents]


def test_instalacao_antiga_em_data_continua_funcionando_ate_a_migracao(tmp_path: Path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "forja.sqlite3").write_bytes(b"x")
    antigo = resolver_perfil({}, cwd=tmp_path)
    assert antigo.legado and antigo.dados == Path("./data")
    assert antigo.pasta("workspace") == Path("./data") / "kiro-workspace" and antigo.logs == Path("./logs")
    (tmp_path / "data" / MARCADOR_MIGRADO).write_text("migrado", encoding="utf-8")
    assert not resolver_perfil({}, cwd=tmp_path).legado  # com o marcador, o legado deixa de ser usado


def test_criar_monta_as_pastas_e_deixa_um_leia_me(tmp_path: Path):
    p = PerfilUsuario(tmp_path / "perfis" / "x", "x")
    p.criar()
    assert all((p.raiz / n).is_dir() for n in SUBPASTAS) and "Nao copie" in (p.raiz / "LEIA-ME.txt").read_text(encoding="utf-8")
    with pytest.raises(KeyError):
        p.pasta("../fora")


def _repo(tmp_path: Path, ignorar: str = "") -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)  # noqa: S603, S607
    (repo / ".gitignore").write_text(ignorar, encoding="utf-8")
    return repo


@pytest.mark.skipif(GIT is None, reason="git ausente")
def test_dados_dentro_de_pasta_versionada_sao_recusados_mas_pasta_ignorada_e_fora_sao_aceitas(tmp_path: Path):
    repo = _repo(tmp_path, "/data/\n")
    with pytest.raises(DadosDentroDoRepositorio):
        validar_fora_do_git(PerfilUsuario(repo / "meus-dados", "x"), repo)
    validar_fora_do_git(PerfilUsuario(repo / "data", "x"), repo)  # ignorada pelo Git (legado ./data)
    validar_fora_do_git(PerfilUsuario(tmp_path / "fora", "x"), repo)  # fora do repositorio: o caso desejado
    validar_fora_do_git(PerfilUsuario(repo / "meus-dados", "x"), None)  # sem repositorio: nada a proteger


def test_configuracoes_derivam_todos_os_caminhos_do_perfil(tmp_path: Path):
    c = Configuracoes(_env_file=None, app_user_home=tmp_path, app_profile="Eu")  # type: ignore[call-arg]
    raiz = tmp_path / "perfis" / "eu"
    assert c.dados_dir == raiz / "dados" and c.db_path == raiz / "dados" / "forja.sqlite3" and c.credenciais_dir == raiz / "credenciais"
    assert c.artefatos_dir == raiz / "artefatos" and c.kiro_workspace_dir == raiz / "workspace" and c.logs_dir == raiz / "logs"


def test_app_data_dir_explicito_sobrescreve_e_mantem_o_comportamento_antigo(tmp_path: Path):
    c = Configuracoes(_env_file=None, app_data_dir=tmp_path / "d", app_log_dir=tmp_path / "l")  # type: ignore[call-arg]
    assert c.db_path == tmp_path / "d" / "forja.sqlite3" and c.credenciais_dir == tmp_path / "d" and c.logs_dir == tmp_path / "l"
    assert c.kiro_workspace_dir == tmp_path / "d" / "kiro-workspace" and c.artefatos_dir == tmp_path / "d" / "artefatos"


def test_segredos_de_integracao_sao_procurados_primeiro_no_env_do_usuario(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("FORJA_INT_Z", raising=False)
    usuario, legado = tmp_path / "usuario.env", tmp_path / "legado.env"
    usuario.write_text("FORJA_INT_Z=do_usuario\n", encoding="utf-8")
    legado.write_text("FORJA_INT_Z=do_legado\nFORJA_INT_Y=so_legado\n", encoding="utf-8")
    antes = list(ambiente._arquivos)
    try:
        ambiente.definir_arquivos([usuario, legado])
        assert ambiente.ler("FORJA_INT_Z") == "do_usuario" and ambiente.ler("FORJA_INT_Y") == "so_legado"
    finally:
        ambiente.definir_arquivos(antes)


# ---- auditoria permanente: o Git nao pode rastrear dados do usuario


@pytest.mark.skipif(GIT is None, reason="git ausente")
def test_nenhum_arquivo_de_usuario_e_rastreado_pelo_git():
    raiz = raiz_do_repositorio()
    if raiz is None:
        pytest.skip("fora de um repositorio")
    out = subprocess.run(["git", "-C", str(raiz), "ls-files"], capture_output=True, text=True, check=True).stdout.splitlines()  # noqa: S603, S607
    proibido = re.compile(r"(^|/)(data|logs|credenciais|perfis|memoria-local|segundo-cerebro)/|\.sqlite3?(-|$)|\.db$|(^|/)\.env(\.(?!example$).*)?$|"
                          r"api_token|\.pem$|\.key$|\.mbox$|\.log$|(^|/)id_(rsa|ed25519)|credentials\.json|secrets?\.(json|ya?ml)$")
    achados = [a for a in out if proibido.search(a)]
    assert not achados, f"arquivos de usuario rastreados pelo Git: {achados}"


@pytest.mark.skipif(GIT is None, reason="git ausente")
def test_gitignore_cobre_as_pastas_e_arquivos_do_usuario():
    raiz = raiz_do_repositorio()
    if raiz is None:
        pytest.skip("fora de um repositorio")
    for caminho in ("data/forja.sqlite3", "data/api_token.txt", ".env", ".env.local", "perfis/x/dados/forja.sqlite3",
                    "credenciais/.env", "logs/forja.log", "x.sqlite3", "notas/minha.brain", "memoria-local/a"):
        r = subprocess.run(["git", "-C", str(raiz), "check-ignore", "-q", "--", caminho], check=False)  # noqa: S603, S607
        assert r.returncode == 0, f"{caminho} NAO e ignorado pelo Git"
