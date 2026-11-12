"""Segundo cerebro: base inicial curada (somente leitura), topicos -> subtopicos ligados, navegacao, estudo e registro."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from forja.adapters.kiro_acp.provedor import ProvedorKiroAcp
from forja.adapters.sqlite import tabelas as T
from forja.adapters.sqlite.repositorio import RepositorioSqlite
from forja.agentes.estilo import PerfilTrabalho
from forja.contexto.construtor import ConstrutorContexto
from forja.dominio.contratos import ObjetivoIn, ProjetoIn, TarefaIn, TransicaoIn
from forja.dominio.erros import ValidacaoDominio
from forja.dominio.estados import EstadoTarefa
from forja.memoria import base as B
from forja.memoria.contratos import MemoriaAtualizaIn, MemoriaIn
from forja.memoria.modelo import BASE_NS, AcessoNegado, Principal
from forja.orquestracao.estudos import EstudoIn, EstudoServico, extrair_notas
from forja.orquestracao.grafo_servico import GrafoServico
from forja.orquestracao.memoria_servico import ServicoMemoria
from forja.orquestracao.servico import Servico
from forja.seguranca.pastas import PoliticaPastas

P = Principal("t", frozenset({"publico", "pessoal"}))
FAKE = str(Path(__file__).parent / "fakes" / "fake_acp_agent.py")


@pytest.fixture
def mem(repo: RepositorioSqlite, tmp_path: Path) -> ServicoMemoria:
    B.semear(repo)
    return ServicoMemoria(repo, raizes_ingestao=[tmp_path])


# ------------------------------------------------------------------ base inicial
def test_base_e_vasta_coerente_e_cobre_as_areas():
    notas = B.carregar()
    titulos = {n.titulo.casefold() for n in notas}
    assert len(notas) >= 60
    for area in ("Engenharia de software", "Segurança de aplicações", "DevOps", "Banco de dados", "Front-end", "UI e UX design",
                 "Qualidade e testes", "RPA (automação robótica de processos)", "Python", "Agentes de IA e orquestração"):
        assert area.casefold() in titulos
    for termo in ("SOLID", "OWASP Top 10", "Heurísticas de Nielsen", "Acessibilidade (WCAG)", "Migrações de esquema", "CI/CD"):
        assert termo.casefold() in titulos
    soltas = [(n.titulo, r) for n in notas for r in ([n.pai] if n.pai else []) + list(n.relacionados) if r.casefold() not in titulos]
    assert soltas == []  # todo pai/relacionado existe
    assert all(len(n.corpo) <= B.MAX_CORPO and n.resumo for n in notas)
    assert sum(1 for n in notas if not n.pai) == 1  # uma unica raiz


def test_semeadura_e_idempotente_e_atualiza_so_o_que_mudou(repo, tmp_path):
    r1 = B.semear(repo)
    assert r1["novas"] >= 60 and r1["ligacoes"] >= 60
    assert B.semear(repo) == {**r1, "novas": 0, "inalteradas": r1["novas"]}
    raiz = tmp_path / "base"
    raiz.mkdir()
    (raiz / "a.md").write_text("---\ntitulo: Raiz\n---\nraiz\n+++\n---\ntitulo: Filho\npai: Raiz\n---\nfilho v1\n", encoding="utf-8")
    assert B.semear(repo, raiz)["removidas"] >= 60  # a base de teste substitui a outra (o que sai da base sai do banco)
    (raiz / "a.md").write_text("---\ntitulo: Raiz\n---\nraiz\n+++\n---\ntitulo: Filho\npai: Raiz\n---\nfilho v2\n", encoding="utf-8")
    r = B.semear(repo, raiz)
    assert r["atualizadas"] == 1 and r["inalteradas"] == 1 and r["ligacoes"] == 1


def test_base_e_validada_por_curadoria_e_somente_leitura(mem):
    with mem.repo.leitura() as t:
        m = next(x for x in t.listar(T.Memoria, namespace=BASE_NS, limite=200) if x["titulo"] == "SOLID")
    assert m["estado"] == "validado" and m["validado_por"] == B.CURADORIA and m["fonte"]["caminho"].startswith("forja/conhecimento_base/")
    with pytest.raises(AcessoNegado):
        mem.criar(P, MemoriaIn(tipo="semantica", titulo="x", namespace=BASE_NS))
    with pytest.raises(AcessoNegado):
        mem.atualizar(P, m["id"], MemoriaAtualizaIn(expected_version=m["versao"], conteudo="alterado"))


def test_navegar_traz_so_a_vizinhanca_com_resumos(mem):
    n = B.navegar(mem.repo, P, "Segurança de aplicações")
    assert n["pai"][0]["titulo"] == "Base de conhecimento da Forja"
    subs = {s["titulo"] for s in n["subtopicos"]}
    assert {"OWASP Top 10", "Gestão de segredos", "Segurança de agentes de IA"} <= subs
    assert "conteudo" not in n and all("conteudo" not in s for s in n["subtopicos"])
    folha = B.navegar(mem.repo, P, "SOLID", incluir_conteudo=True)
    assert "Liskov" in folha["conteudo"] and any(r["titulo"] == "Programação orientada a objetos" for r in folha["relacionados"])


def test_busca_acha_a_base_e_o_contexto_aponta_os_subtopicos(mem):
    r = mem.buscar(P, "principios solid inversao de dependencia", ["publico"], limite=3)
    assert r["resultados"][0]["titulo"] == "SOLID"
    c = ConstrutorContexto(mem, Principal("ctx", frozenset({"publico"})), ["publico"])
    pac = c.construir({"titulo": "Revisar seguranca de aplicacoes", "descricao": "owasp e segredos", "criterios_aceite": ["ok"],
                       "politicas": {}, "contexto_refs": []})
    assert pac.itens and "subtopicos:" in pac.texto  # o agente sabe onde aprofundar sem receber tudo


# ------------------------------------------------------------------ estudo (alimentacao) e registro
def test_extrair_notas_tolera_variacoes():
    notas = extrair_notas("## Notas\n### Nota: A\nTópico pai: \nTags: x, y\nFontes: http://ex.org a.py\ncorpo A\n"
                          "#### nota: B\npai: A\ncorpo B\n## Premissas\n- fim")
    assert [(n.titulo, n.pai, n.tags) for n in notas] == [("A", "", ["x", "y"]), ("B", "A", [])]
    assert notas[0].fontes == ["http://ex.org", "a.py"] and notas[1].corpo == "corpo B"


@pytest.fixture
def estudo_ctx(repo, tmp_path, mem):
    pasta = tmp_path / "proj"
    (pasta / "src").mkdir(parents=True)
    (pasta / "src" / "fila.py").write_text("def enfileirar(x, prioridade=3):\n    return (prioridade, x)\n", encoding="utf-8")
    (pasta / ".env").write_text("SEGREDO=nao-pode\n", encoding="utf-8")
    prov = ProvedorKiroAcp([sys.executable, FAKE, "estudo"], tmp_path / "ws", timeout_prompt=30, timeout_handshake=10,
                           perfil_de=lambda: PerfilTrabalho(nivel="liberado"))
    s = Servico(repo, prov, tmp_path / "art", max_workers=1)
    est = EstudoServico(s, mem, GrafoServico(repo), lambda: PoliticaPastas(ativa=True, permitidas=(tmp_path,)), P)
    s.ao_finalizar.append(est.ao_finalizar)
    yield s, est, pasta
    s.encerrar()


def _esperar(s, tarefa_id):
    import time

    for _ in range(300):
        with s.repo.leitura() as t:
            if t.obter(T.Tarefa, tarefa_id)["estado"] in ("concluida", "falhou", "bloqueada"):
                break
        time.sleep(0.05)
    time.sleep(0.3)  # ganchos rodam logo apos a finalizacao


def test_estudo_de_pasta_vira_notas_candidatas_ligadas(estudo_ctx):
    s, est, pasta = estudo_ctx
    r = est.solicitar(EstudoIn(tipo="pasta", alvo=str(pasta), namespace="pessoal/estudos", executar=True))
    assert "enfileirar" in r["tarefa"]["descricao"] and "nao-pode" not in r["tarefa"]["descricao"]
    _esperar(s, r["tarefa"]["id"])
    with s.repo.leitura() as t:
        notas = {m["titulo"]: m for m in t.listar(T.Memoria, namespace="pessoal/estudos", limite=100)}
        ligs = t.listar(T.LigacaoGrafo, tipo="SUBTOPICO_DE", limite=100)
    assert {"Estudo: proj", "Visao geral da fila", "Prioridade da fila", "Riscos de concorrencia na fila"} <= set(notas)
    assert all(m["estado"] == "candidato" for m in notas.values())  # nada nasce validado
    pares = {(lg["origem"], lg["destino"]) for lg in ligs}
    assert (notas["Prioridade da fila"]["id"], notas["Visao geral da fila"]["id"]) in pares  # pai dentro do estudo
    assert (notas["Visao geral da fila"]["id"], notas["Estudo: proj"]["id"]) in pares  # sem pai -> raiz do estudo
    with s.repo.leitura() as t:
        conc = next(x for x in t.listar(T.Memoria, namespace=BASE_NS, limite=200) if x["titulo"] == "Concorrência e paralelismo")
    assert (notas["Riscos de concorrencia na fila"]["id"], conc["id"]) in pares  # pai na base da Forja
    assert "protocolo=True" in notas["Visao geral da fila"]["conteudo"]


def test_estudo_recusa_pasta_nao_permitida(estudo_ctx, tmp_path_factory):
    _s, est, _p = estudo_ctx
    with pytest.raises(ValidacaoDominio):
        est.solicitar(EstudoIn(tipo="pasta", alvo=str(tmp_path_factory.mktemp("fora"))))


def test_registro_de_decisoes_de_tarefa_real(repo, tmp_path, mem):
    from tests.test_acp import cmd

    prov = ProvedorKiroAcp(cmd("briefing_sem_decisao"), tmp_path / "ws", timeout_prompt=30, timeout_handshake=10)
    s = Servico(repo, prov, tmp_path / "art", max_workers=1)
    est = EstudoServico(s, mem, GrafoServico(repo), None, P)
    s.ao_finalizar.append(est.ao_finalizar)
    try:
        pj, _ = s.criar_projeto(ProjetoIn(nome="Loja Demo"))
        ob, _ = s.criar_objetivo(ObjetivoIn(projeto_id=pj["id"], titulo="o"))
        tf, _ = s.criar_tarefa(TarefaIn(objetivo_id=ob["id"], titulo="Revisar integridade", criterios_aceite=["ok"]))
        for d in (EstadoTarefa.CLASSIFICADA, EstadoTarefa.PREPARADA):
            tf, _ = s.transicionar(tf["id"], TransicaoIn(para=d, expected_version=tf["versao_estado"]))
        s.iniciar_execucao(s.criar_execucao(tf["id"])["id"], "operador")
        _esperar(s, tf["id"])
        with repo.leitura() as t:
            regs = {m["titulo"]: m for m in t.listar(T.Memoria, namespace="pessoal/projetos/loja-demo", limite=20)}
        assert {"Projeto: Loja Demo", "Registro: Revisar integridade"} <= set(regs)
        r = regs["Registro: Revisar integridade"]
        assert r["tipo"] == "decisoria" and r["estado"] == "candidato" and "## Premissas" in r["conteudo"]
        assert B.navegar(repo, P, "Projeto: Loja Demo")["subtopicos"][0]["titulo"] == "Registro: Revisar integridade"
    finally:
        s.encerrar()
