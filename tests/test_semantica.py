"""Busca semantica opcional por nivel (inativo | fallback | ativo), com embedder FALSO deterministico (sem download)."""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

import pytest
from sqlalchemy import text

from forja.adapters.sqlite.repositorio import RepositorioSqlite
from forja.memoria import semantica as S
from forja.memoria.contratos import FonteIn, IngerirIn, MemoriaIn
from forja.memoria.modelo import Principal
from forja.orquestracao.memoria_servico import ServicoMemoria
from forja.preferencias.registro import POR_ID

TUDO = Principal("dono", frozenset({"publico", "pessoal"}))
PUB = Principal("teste", frozenset({"publico"}))
SINONIMOS = {"carro": "veiculo", "automovel": "veiculo", "veiculo": "veiculo"}  # "significado" que o lexical nao conhece


class Falso:
    """Bag-of-words com sinonimos: 'automovel' e 'carro' caem no mesmo eixo (o que o embedding real faz por significado)."""
    modelo = "falso-64"
    chamadas = 0

    def vetores(self, textos):
        Falso.chamadas += len(textos)
        saida = []
        for t in textos:
            v = [0.0] * 64
            for w in re.findall(r"[a-z]+", t.lower()):
                w = SINONIMOS.get(w, w)
                v[int(hashlib.sha256(w.encode()).hexdigest(), 16) % 64] += 1.0
            saida.append(v)
        return saida


@pytest.fixture
def mem(repo: RepositorioSqlite, tmp_path: Path, relogio) -> ServicoMemoria:
    m = ServicoMemoria(repo, relogio, raizes_ingestao=[tmp_path / "repos"])
    m.semantica = S.IndiceSemantico(repo, fabrica=Falso, checar=lambda: (True, ""))
    return m


def _nota(mem: ServicoMemoria, titulo: str, conteudo: str, ns: str = "publico") -> str:
    return mem.criar(TUDO, MemoriaIn(tipo="semantica", titulo=titulo, resumo=titulo, conteudo=conteudo, namespace=ns,
                                     fonte=FonteIn(tipo="manual")))["id"]


def _esperar(mem: ServicoMemoria) -> None:
    for _ in range(200):
        th = mem.semantica._thread
        if th is None or not th.is_alive():
            return
        time.sleep(0.02)


def test_preferencia_tem_os_tres_niveis_e_nasce_inativa():
    p = POR_ID["busca_semantica"]
    assert [v for v, _ in p.opcoes] == ["inativo", "fallback", "ativo"] and p.padrao == "inativo"


def test_inativa_nao_toca_no_modelo_nem_muda_o_ranking(mem):
    _nota(mem, "Manutencao do automovel", "troca de oleo do automovel a cada 10 mil km")
    Falso.chamadas = 0
    r = mem.buscar(TUDO, "revisao do carro", ["publico"])
    assert r["semantica"] == {"modo": "inativo", "usada": False} and Falso.chamadas == 0


def test_ativa_acha_por_significado_o_que_a_lexical_nao_acha(mem):
    alvo = _nota(mem, "Manutencao do automovel", "troca de oleo do automovel a cada 10 mil km")
    _nota(mem, "Receita de bolo", "farinha ovos e acucar")
    mem.semantica.definir_modo("ativo")
    _esperar(mem)
    r = mem.buscar(TUDO, "carro", ["publico"])
    assert r["semantica"]["usada"] is True and r["resultados"] and r["resultados"][0]["id"] == alvo
    assert r["resultados"][0].get("semantico") is True


def test_fallback_so_entra_quando_a_lexical_esta_insegura(mem):
    _nota(mem, "Alembic migracoes", "como rodar alembic upgrade head")
    _nota(mem, "Manutencao do automovel", "troca de oleo do automovel")
    mem.semantica.definir_modo("fallback")
    _esperar(mem)
    confiante = mem.buscar(TUDO, "alembic upgrade head", ["publico"])
    assert confiante["semantica"]["usada"] is False and confiante["semantica"]["motivo"] == "busca lexical confiante"
    vaga = mem.buscar(TUDO, "carro", ["publico"])
    assert vaga["semantica"]["usada"] is True


def test_acl_e_aplicada_antes_da_pontuacao(mem):
    _nota(mem, "Automovel pessoal", "meu automovel particular", ns="pessoal")
    mem.semantica.definir_modo("ativo")
    _esperar(mem)
    r = mem.buscar(PUB, "carro", ["publico"])
    assert all(i["namespace"] == "publico" for i in r["resultados"])


def test_indexacao_e_incremental_e_remove_orfaos(mem, repo):
    _nota(mem, "Um", "automovel")
    mem.semantica.definir_modo("ativo")
    _esperar(mem)
    with repo.leitura() as t:
        n1 = t.s.execute(text("SELECT count(*) FROM vetor_semantico")).scalar()
    Falso.chamadas = 0
    assert mem.semantica.sincronizar() == 0 and Falso.chamadas == 0  # nada mudou: nada recalculado
    _nota(mem, "Dois", "bolo")
    _esperar(mem)
    with repo.leitura() as t:
        assert t.s.execute(text("SELECT count(*) FROM vetor_semantico")).scalar() == n1 + 1


def test_codigo_ingerido_tambem_vira_vetor(mem, tmp_path):
    raiz = tmp_path / "repos" / "demo"
    raiz.mkdir(parents=True)
    (raiz / "frota.py").write_text("def revisar_automovel(placa):\n    return placa\n", encoding="utf-8")
    mem.semantica.definir_modo("ativo")
    mem.ingerir_diretorio(TUDO, IngerirIn(raiz=str(raiz), namespace="publico", repositorio="demo"))
    _esperar(mem)
    r = mem.buscar(TUDO, "carro", ["publico"], fontes=("codigo",))
    assert any(i["origem"] == "codigo" and i["caminho"] == "frota.py" for i in r["resultados"])


def test_indisponivel_explica_o_motivo_e_nao_quebra_a_busca(mem):
    mem.semantica = S.IndiceSemantico(mem.repo, fabrica=Falso, checar=lambda: (False, "dependencia opcional ausente: pip install fastembed"))
    mem.semantica.definir_modo("ativo")
    _nota(mem, "Alembic", "alembic upgrade")
    r = mem.buscar(TUDO, "alembic", ["publico"])
    assert r["resultados"] and r["semantica"]["usada"] is False and "fastembed" in r["semantica"]["motivo"]
    e = mem.semantica.estado()
    assert e["disponivel"] is False and "fastembed" in e["motivo"]


def test_margem_insegura():
    assert S.margem_insegura([]) and S.margem_insegura([1.0, 0.8])
    assert not S.margem_insegura([1.0]) and not S.margem_insegura([1.0, 0.5])


def test_ram_detectada():
    ram = S.ram_total_gb()
    assert ram is None or ram > 0.5
