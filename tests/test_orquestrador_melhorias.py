"""Melhorias do orquestrador (9.1-9.5): desfazer por tarefa, pastas isoladas, retomada apos queda e isolamento dos testes."""

from __future__ import annotations

import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from forja.adapters.agentes_mock.mock import AgenteMock
from forja.adapters.sqlite import tabelas as T
from forja.dominio.contratos import EvidenciaSaida, ObjetivoIn, ProjetoIn, ResultadoAgente, TarefaIn, TransicaoIn
from forja.dominio.erros import Conflito
from forja.dominio.estados import EstadoExecucao, EstadoTarefa
from forja.ferramentas import sandbox, verificacao
from forja.orquestracao.isolamento import Isolamento
from forja.orquestracao.restauracao import Limites, PontosRestauracao
from forja.orquestracao.servico import Servico

ET = EstadoTarefa
TEM_GIT = shutil.which("git") is not None


# ------------------------------------------------------------------ 9.1 pontos de restauracao (unidade)
def _pasta(tmp_path: Path) -> Path:
    p = tmp_path / "proj"
    (p / "src").mkdir(parents=True)
    (p / "src" / "a.py").write_text("a = 1\n", encoding="utf-8")
    (p / "src" / "b.py").write_text("b = 1\n", encoding="utf-8")
    (p / ".env").write_text("SEGREDO=nao-copiar\n", encoding="utf-8")
    (p / "node_modules").mkdir()
    (p / "node_modules" / "x.js").write_text("x", encoding="utf-8")
    return p


def test_desfazer_restaura_alterados_apagados_e_remove_criados(tmp_path, repo):
    pasta = _pasta(tmp_path)
    pr = PontosRestauracao(repo, tmp_path / "pontos")
    pid = pr.capturar("EX-1", "T-1", pasta)
    with repo.leitura() as t:
        ponto = t.obter(T.PontoRestauracao, pid)
    assert set(ponto["antes"]) == {"src/a.py", "src/b.py"}  # .env (segredo) e node_modules ficam de fora
    blobs = [p.read_bytes() for p in (tmp_path / "pontos").rglob("*") if p.is_file()]
    assert all(b"SEGREDO" not in b for b in blobs)
    (pasta / "src" / "a.py").write_text("a = 2\n", encoding="utf-8")  # a execucao altera, apaga e cria
    (pasta / "src" / "b.py").unlink()
    (pasta / "src" / "novo.py").write_text("n = 1\n", encoding="utf-8")
    resumo = pr.finalizar(pid)
    assert resumo == {"alterados": ["src/a.py"], "adicionados": ["src/novo.py"], "removidos": ["src/b.py"], "ignorados": 1}
    assert pr.tem_desfazer(["T-1"]) == {"T-1"}
    r = pr.desfazer(pid)
    assert r["estado"] == "desfeito" and sorted(r["restaurados"]) == ["src/a.py", "src/b.py"] and r["removidos"] == ["src/novo.py"]
    assert (pasta / "src" / "a.py").read_text(encoding="utf-8") == "a = 1\n" and (pasta / "src" / "b.py").exists()
    assert not (pasta / "src" / "novo.py").exists() and (pasta / ".env").exists()
    with pytest.raises(Conflito):
        pr.desfazer(pid)  # nada mais a desfazer


def test_desfazer_nao_sobrescreve_o_que_voce_mexeu_depois(tmp_path, repo):
    pasta = _pasta(tmp_path)
    pr = PontosRestauracao(repo, tmp_path / "pontos")
    pid = pr.capturar("EX-1", "T-1", pasta)
    (pasta / "src" / "a.py").write_text("da execucao\n", encoding="utf-8")
    pr.finalizar(pid)
    (pasta / "src" / "a.py").write_text("editado por voce depois\n", encoding="utf-8")
    r = pr.desfazer(pid)
    assert r["conflitos"] == ["src/a.py"] and r["estado"] == "finalizado"
    assert (pasta / "src" / "a.py").read_text(encoding="utf-8") == "editado por voce depois\n"
    r = pr.desfazer(pid, forcar=True)  # forcar: a tela pede confirmacao explicita
    assert r["estado"] == "desfeito" and (pasta / "src" / "a.py").read_text(encoding="utf-8") == "a = 1\n"


def test_desfazer_em_ordem_e_limites(tmp_path, repo):
    pasta = _pasta(tmp_path)
    pr = PontosRestauracao(repo, tmp_path / "pontos")
    p1 = pr.capturar("EX-1", "T-1", pasta)
    (pasta / "src" / "a.py").write_text("v2\n", encoding="utf-8")
    pr.finalizar(p1)
    p2 = pr.capturar("EX-2", "T-2", pasta)
    (pasta / "src" / "a.py").write_text("v3\n", encoding="utf-8")
    pr.finalizar(p2)
    with pytest.raises(Conflito, match="mais recente"):
        pr.desfazer(p1)
    assert pr.desfazer(p2)["estado"] == "desfeito" and pr.desfazer(p1)["estado"] == "desfeito"
    assert (pasta / "src" / "a.py").read_text(encoding="utf-8") == "a = 1\n"
    pequeno = PontosRestauracao(repo, tmp_path / "p2", limites=Limites(max_arquivo=3))
    pid = pequeno.capturar("EX-3", "T-3", pasta)
    with repo.leitura() as t:
        assert t.obter(T.PontoRestauracao, pid)["antes"] == {}  # tudo acima do limite fica de fora (informado)
    assert pequeno.capturar("EX-4", "T-4", tmp_path / "nao-existe") is None


# ------------------------------------------------------------------ 9.2 pastas isoladas
def _git_repo(p: Path) -> Path:
    p.mkdir(parents=True)
    for args in (["init", "-q"], ["config", "user.email", "teste@exemplo.invalid"], ["config", "user.name", "teste"]):
        subprocess.run(["git", *args], cwd=p, check=True, capture_output=True)  # noqa: S603, S607
    (p / "app.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=p, check=True, capture_output=True)  # noqa: S603, S607
    subprocess.run(["git", "commit", "-q", "-m", "inicio"], cwd=p, check=True, capture_output=True)  # noqa: S603, S607
    return p


def test_pasta_ocupada_sem_git_bloqueia(tmp_path, repo):
    iso = Isolamento(repo)
    pasta = tmp_path / "semgit"
    pasta.mkdir()
    pastas = [{"caminho": str(pasta), "papel": "trabalho"}, {"caminho": str(tmp_path), "papel": "consulta"}]
    ef, areas, motivo = iso.reservar("EX-1", "T-1", pastas)
    assert motivo is None and ef == pastas and areas == []
    _ef, _a, motivo = iso.reservar("EX-2", "T-2", pastas)
    assert motivo and motivo.startswith("pasta_ocupada") and "EX-1" in motivo
    iso.liberar("EX-1")
    assert iso.reservar("EX-2", "T-2", pastas)[2] is None


@pytest.mark.skipif(not TEM_GIT, reason="git ausente")
def test_pasta_ocupada_com_git_ganha_worktree_em_branch_proprio(tmp_path, repo):
    proj = _git_repo(tmp_path / "repo")
    iso = Isolamento(repo)
    pastas = [{"caminho": str(proj), "papel": "trabalho"}]
    assert iso.reservar("EX-aaaaaa", "T-1", pastas)[2] is None
    ef, areas, motivo = iso.reservar("EX-bbbbbb", "T-2", pastas)
    assert motivo is None and len(areas) == 1 and areas[0]["branch"] == "forja/T-2-bbbbbb"
    copia = Path(ef[0]["caminho"])
    assert copia.parent == (proj / ".worktrees").resolve() and (copia / "app.py").exists() and ef[0]["isolada"]
    assert "/.worktrees/" in (proj / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    status = subprocess.run(["git", "status", "--porcelain"], cwd=proj, capture_output=True, text=True, check=True)  # noqa: S603, S607
    assert ".worktrees" not in status.stdout  # a copia nao aparece como alteracao no repositorio original
    assert [a["branch"] for a in iso.listar()] == ["forja/T-2-bbbbbb"]
    with pytest.raises(Conflito, match="usando"):
        iso.remover("EX-bbbbbb")
    iso.liberar("EX-bbbbbb")
    assert iso.remover("EX-bbbbbb")["estado"] == "removida" and not copia.exists()
    branches = subprocess.run(["git", "branch", "--list", "forja/*"], cwd=proj, capture_output=True, text=True, check=True)  # noqa: S603, S607
    assert "forja/T-2-bbbbbb" in branches.stdout  # o trabalho (branch) nunca e apagado


@pytest.mark.skipif(not TEM_GIT, reason="git ausente")
def test_politica_sandbox_worktree_isola_mesmo_com_pasta_livre(tmp_path, repo):
    proj = _git_repo(tmp_path / "repo")
    ef, areas, motivo = Isolamento(repo).reservar("EX-cccccc", "T-9", [{"caminho": str(proj), "papel": "trabalho"}], forcar=True)
    assert motivo is None and areas and Path(ef[0]["caminho"]) != proj.resolve()
    semgit = tmp_path / "x"
    semgit.mkdir()
    motivo = Isolamento(repo).reservar("EX-d", "T-d", [{"caminho": str(semgit), "papel": "trabalho"}], forcar=True)[2]
    assert motivo and motivo.startswith("isolamento_indisponivel")


# ------------------------------------------------------------------ integracao com o Servico
class _Escritor:
    """Provedor de teste: escreve um arquivo na pasta de trabalho; `portao` segura a execucao para simular paralelismo."""

    id, mock = "teste.escritor", False

    def __init__(self) -> None:
        self.portao = threading.Event()
        self.portao.set()
        self.cwds: list[str] = []

    def executar(self, tarefa, checkpoint, ctl):  # noqa: ANN001, ANN201
        pasta = Path(tarefa["projeto_ctx"]["pastas"][0]["caminho"])
        self.cwds.append(str(pasta))
        self.portao.wait(10)
        (pasta / f"{tarefa['id']}.txt").write_text("feito\n", encoding="utf-8")
        return ResultadoAgente(estado="concluida", resumo="ok", agente_id=self.id,
                               evidencias=[EvidenciaSaida(tipo="teste", resumo="arquivo escrito")])


class _Projetos:
    def __init__(self, pasta: Path) -> None:
        self.pasta = pasta

    def para_execucao(self, tarefa):  # noqa: ANN001, ANN201
        return {"projeto": "p", "pastas": [{"caminho": str(self.pasta), "papel": "trabalho"}], "anexos": []}


def _pronta(s: Servico, nome: str, modo: str = "alteracao_codigo") -> dict:
    p, _ = s.criar_projeto(ProjetoIn(nome=nome))
    o, _ = s.criar_objetivo(ObjetivoIn(projeto_id=p["id"], titulo="o"))
    t, _ = s.criar_tarefa(TarefaIn(objetivo_id=o["id"], titulo=nome, criterios_aceite=["ok"], modo=modo))
    a = s.transicionar(t["id"], TransicaoIn(para=ET.CLASSIFICADA, expected_version=1))[0]
    return s.transicionar(t["id"], TransicaoIn(para=ET.PREPARADA, expected_version=a["versao_estado"]))[0]


@pytest.fixture
def servico_pastas(repo, tmp_path, relogio):
    pasta = tmp_path / "trabalho"
    pasta.mkdir()
    prov = _Escritor()
    s = Servico(repo, prov, tmp_path / "data" / "artefatos", max_workers=4, relogio=relogio)
    s.projetos = _Projetos(pasta)
    s.restauracao = PontosRestauracao(repo, tmp_path / "pontos", relogio=relogio)
    s.isolamento = Isolamento(repo, relogio=relogio)
    yield s, prov, pasta
    prov.portao.set()
    s.encerrar(timeout=5)


def test_execucao_que_escreve_ganha_ponto_e_pode_ser_desfeita(servico_pastas):
    s, _prov, pasta = servico_pastas
    t = _pronta(s, "escreve")
    ex = s.criar_execucao(t["id"])
    s.iniciar_execucao(ex["id"])
    s.aguardar(ex["id"])
    assert s.obter(T.Tarefa, t["id"])["estado"] == ET.CONCLUIDA.value and (pasta / f"{t['id']}.txt").exists()
    [ponto] = s.restauracao.listar(t["id"])
    assert ponto["adicionados"] == [f"{t['id']}.txt"] and ponto["pode_desfazer"]
    s.restauracao.desfazer(ponto["id"])
    assert not (pasta / f"{t['id']}.txt").exists()
    analise = _pronta(s, "so-le", modo="analise")  # modo que nao escreve: sem foto (custo zero)
    ex2 = s.criar_execucao(analise["id"])
    s.iniciar_execucao(ex2["id"])
    s.aguardar(ex2["id"])
    assert s.restauracao.listar(analise["id"]) == []


def test_segunda_execucao_na_mesma_pasta_espera_e_retoma_sozinha(servico_pastas):
    s, prov, pasta = servico_pastas
    prov.portao.clear()
    t1, t2 = _pronta(s, "primeira"), _pronta(s, "segunda")
    e1 = s.criar_execucao(t1["id"])
    s.iniciar_execucao(e1["id"])
    for _ in range(200):  # espera a primeira reservar a pasta
        if s.isolamento.ocupante(pasta):
            break
        threading.Event().wait(0.02)
    e2 = s.criar_execucao(t2["id"])
    s.iniciar_execucao(e2["id"])
    s.aguardar(e2["id"])
    ex2 = s.obter(T.Execucao, e2["id"])
    assert ex2["estado"] == EstadoExecucao.PAUSADA.value and ex2["resultado"]["pendencias"][0].startswith("pasta_ocupada")
    prov.portao.set()
    s.aguardar(e1["id"])
    for _ in range(300):  # a liberacao da pasta acorda a segunda
        if s.obter(T.Tarefa, t2["id"])["estado"] == ET.CONCLUIDA.value:
            break
        threading.Event().wait(0.02)
    assert s.obter(T.Tarefa, t2["id"])["estado"] == ET.CONCLUIDA.value and (pasta / f"{t2['id']}.txt").exists()


# ------------------------------------------------------------------ 9.3 retomada apos queda
def _orfa(s: Servico, repo, nome: str) -> tuple[dict, dict]:
    p, _ = s.criar_projeto(ProjetoIn(nome=nome))
    o, _ = s.criar_objetivo(ObjetivoIn(projeto_id=p["id"], titulo="o"))
    t, _ = s.criar_tarefa(TarefaIn(objetivo_id=o["id"], titulo=nome, criterios_aceite=["ok"], entrada={"mock_cenario": "sucesso", "mock_passos": 1}))
    a = s.transicionar(t["id"], TransicaoIn(para=ET.CLASSIFICADA, expected_version=1))[0]
    t = s.transicionar(t["id"], TransicaoIn(para=ET.PREPARADA, expected_version=a["versao_estado"]))[0]
    ex = s.criar_execucao(t["id"])
    with repo.escrita() as tx:  # estado pos-crash: 'executando' sem worker vivo
        tx.atualizar(T.Execucao, ex["id"], estado=EstadoExecucao.EXECUTANDO.value)
        assert tx.atualizar_tarefa_condicional(t["id"], ET.PRONTA.value, t["versao_estado"], estado=ET.EXECUTANDO.value)
    return t, ex


def test_retomada_automatica_uma_vez_por_execucao(servico: Servico, repo):
    t, ex = _orfa(servico, repo, "queda")
    novo = Servico(repo, AgenteMock(), servico.artefatos_dir)
    novo.retomar_apos_queda = "automatico"
    r = novo.recuperar()
    assert r["retomadas"] == [ex["id"]]
    novo.aguardar(ex["id"])
    assert servico.obter(T.Tarefa, t["id"])["estado"] == ET.CONCLUIDA.value
    with repo.leitura() as tx:
        assert tx.contar_eventos("execucao.retomada_automatica", ex["id"]) == 1
    t2, ex2 = _orfa(servico, repo, "queda-2")
    with repo.escrita() as tx:  # ja retomada uma vez: a proxima queda exige voce
        tx.emitir_evento("execucao.retomada_automatica", "2026-01-01T00:00:00+00:00", {}, execucao_id=ex2["id"])
    assert novo.recuperar()["retomadas"] == []
    assert servico.obter(T.Tarefa, t2["id"])["estado"] == ET.BLOQUEADA.value
    manual = Servico(repo, AgenteMock(), servico.artefatos_dir)  # padrao: manual
    assert manual.recuperar()["retomadas"] == []


# ------------------------------------------------------------------ 9.5 isolamento dos testes
def test_caixa_de_areia_estrita_troca_home_e_corta_rede(tmp_path):
    env = sandbox.preparar_ambiente({"PATH": "x", "HOME": "/home/real", "NO_PROXY": "*"}, "estrito", tmp_path)
    assert env["HOME"].startswith(str(tmp_path)) and env["USERPROFILE"] == env["HOME"] and env["HTTPS_PROXY"] == sandbox.PROXY_MORTO
    assert "NO_PROXY" not in env and env["TMP"].startswith(str(tmp_path)) and env["PIP_NO_INDEX"] == "1"
    basico = sandbox.preparar_ambiente({"HOME": "/home/real"}, "basico", tmp_path)
    assert basico["HOME"] == "/home/real" and basico["TEMP"].startswith(str(tmp_path))


def test_tempo_esgotado_mata_a_arvore_de_processos(tmp_path):
    marca = tmp_path / "neto_vivo.txt"
    (tmp_path / "neto.py").write_text("import pathlib, sys, time\ntime.sleep(3)\npathlib.Path(sys.argv[1]).write_text('x')\n", encoding="utf-8")
    (tmp_path / "pai.py").write_text("import subprocess, sys, time\nsubprocess.Popen([sys.executable, sys.argv[1], sys.argv[2]])\n"
                                     "time.sleep(30)\n", encoding="utf-8")
    s = sandbox.executar([sys.executable, str(tmp_path / "pai.py"), str(tmp_path / "neto.py"), str(marca)], tmp_path,
                         verificacao.ambiente_limpo(), timeout=1.5)
    assert s.esgotado and s.codigo is None and s.isolamento["grupo"]
    threading.Event().wait(4)
    assert not marca.exists()  # o neto morreu junto (Job Object / grupo de processos)


def test_rodar_testes_informa_o_isolamento_aplicado(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_ok.py").write_text("import os, tempfile\n\ndef test_ok():\n    assert 'forja-caixa' in tempfile.gettempdir()\n",
                                                   encoding="utf-8")
    cmd = verificacao.detectar(tmp_path)
    r = verificacao.rodar(cmd, tmp_path, 120, "estrito")
    assert r.ok, r.saida[-500:]
    assert r.isolamento["modo"] == "estrito" and r.isolamento["grupo"]
