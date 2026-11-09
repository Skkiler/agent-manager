"""A base publica de conhecimento (`knowledge/procedimentos`) e ingerivel e encontravel pela busca, com sinonimos."""

from __future__ import annotations

from pathlib import Path

import pytest

from forja.adapters.sqlite.repositorio import RepositorioSqlite
from forja.memoria.contratos import IngerirIn
from forja.memoria.modelo import Principal
from forja.orquestracao.memoria_servico import ServicoMemoria

RAIZ = Path(__file__).resolve().parents[1] / "knowledge"
PRINCIPAL = Principal("teste", frozenset({"publico"}))


@pytest.fixture
def mem(repo: RepositorioSqlite, relogio) -> ServicoMemoria:
    s = ServicoMemoria(repo, relogio, raizes_ingestao=[RAIZ], sinonimos=str(RAIZ / "ontologias" / "sinonimos.json"))
    r = s.ingerir_diretorio(
        PRINCIPAL, IngerirIn(namespace="publico", raiz=str(RAIZ / "procedimentos"), repositorio="conhecimento-publico")
    )
    assert r["novos"] >= 5
    return s


@pytest.mark.parametrize(
    ("consulta", "arquivo"),
    [
        ("como organizar camadas do projeto", "arquitetura-em-camadas.md"),
        ("padrao de mensagem de commit", "git-commits-e-ci.md"),
        ("nomenclatura snake_case", "solid-poo-nomenclatura.md"),
        ("proteger segredos e prompt injection", "seguranca-appsec.md"),
        ("robo idempotente com tentativas", "rpa-dba-ux-busca.md"),
    ],
)
def test_pergunta_em_linguagem_natural_acha_o_procedimento_certo(mem, consulta, arquivo):
    r = mem.buscar(PRINCIPAL, consulta, ["publico"])["resultados"]
    topo = [str(x.get("caminho") or x.get("fonte") or x) for x in r[:3]]
    assert any(arquivo in t for t in topo), (consulta, topo)
