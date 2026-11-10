"""Migracao dos dados antigos (./data) para o perfil do usuario: nao destrutiva, consistente e reversivel."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from forja.usuario.layout import MARCADOR_MIGRADO, PerfilUsuario, resolver_perfil
from forja.usuario.migracao import conflitos, executar, planejar


@pytest.fixture
def projeto(tmp_path: Path) -> Path:
    raiz = tmp_path / "proj"
    (raiz / "data" / "artefatos" / "ab").mkdir(parents=True)
    (raiz / "data" / "kiro-workspace").mkdir()
    (raiz / "logs").mkdir()
    con = sqlite3.connect(raiz / "data" / "forja.sqlite3")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE t (v TEXT)")
    con.execute("INSERT INTO t VALUES ('importante')")
    try:
        con.commit()  # com o banco ainda aberto: parte dos dados esta no -wal
        # Banco pequeno e valido como arquivo real. (Antes: serialize() de um ':memory:' vazio, que algumas builds do SQLite recusam,
        # e a falha deixava conexoes abertas que viravam ResourceWarning em OUTRO teste. Achado pelo CI.)
        vazio = sqlite3.connect(raiz / "data" / "segundo-cerebro.sqlite3")
        try:
            vazio.execute("CREATE TABLE nota (id INTEGER PRIMARY KEY)")
            vazio.commit()
        finally:
            vazio.close()
        (raiz / "data" / "artefatos" / "ab" / "abc").write_text("artefato", encoding="utf-8")
        (raiz / "data" / "api_token.txt").write_text("token-de-teste\n", encoding="utf-8")
        (raiz / "logs" / "a.log").write_text("log", encoding="utf-8")
        (raiz / ".env").write_text("APP_PORT=8787\n", encoding="utf-8")
        yield raiz
    finally:
        con.close()  # fecha mesmo se a preparacao falhar no meio


def destino(tmp_path: Path) -> PerfilUsuario:
    return PerfilUsuario(tmp_path / "home" / "perfis" / "eu", "eu")


def test_plano_lista_bancos_artefatos_token_e_logs_mas_so_inclui_env_se_pedido(projeto, tmp_path):
    nomes = {p.origem.name for p in planejar(projeto, destino(tmp_path))}
    assert {"forja.sqlite3", "segundo-cerebro.sqlite3", "artefatos", "kiro-workspace", "api_token.txt", "logs"} <= nomes
    assert ".env" not in nomes and ".env" in {p.origem.name for p in planejar(projeto, destino(tmp_path), incluir_env=True)}


def test_executar_copia_com_consistencia_marca_o_legado_e_nao_apaga_a_origem(projeto, tmp_path):
    d = destino(tmp_path)
    executar(projeto, d, planejar(projeto, d, incluir_env=True))
    copia = sqlite3.connect(d.dados / "forja.sqlite3")
    try:
        assert copia.execute("SELECT v FROM t").fetchone() == ("importante",)  # inclui o que estava so no WAL
    finally:
        copia.close()
    assert (d.credenciais / "api_token.txt").read_text(encoding="utf-8").strip() == "token-de-teste"
    assert (d.arquivo_env).read_text(encoding="utf-8") == "APP_PORT=8787\n"
    assert (d.pasta("artefatos") / "ab" / "abc").read_text(encoding="utf-8") == "artefato" and (d.logs / "a.log").exists()
    assert (projeto / "data" / "forja.sqlite3").exists() and (projeto / "data" / "api_token.txt").exists()  # origem intacta
    assert (projeto / "data" / MARCADOR_MIGRADO).exists()


def test_depois_de_migrar_a_forja_deixa_de_usar_o_legado(projeto, tmp_path):
    assert resolver_perfil({}, cwd=projeto).legado
    executar(projeto, destino(tmp_path), planejar(projeto, destino(tmp_path)))
    assert not resolver_perfil({}, cwd=projeto).legado


def test_conflito_quando_o_destino_ja_tem_dados(projeto, tmp_path):
    d = destino(tmp_path)
    passos = planejar(projeto, d)
    assert conflitos(passos) == []
    executar(projeto, d, passos)
    assert any(c.name == "forja.sqlite3" for c in conflitos(planejar(projeto, d)))


def test_sem_data_nao_ha_o_que_migrar(tmp_path):
    assert planejar(tmp_path, destino(tmp_path)) == []
