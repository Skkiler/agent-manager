"""Rodada unica de correcao (avaliador-otimizador): a Forja roda os testes REAIS do projeto e devolve a falha ao agente uma vez."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from forja.adapters.kiro_acp.provedor import ProvedorKiroAcp
from forja.agentes.base import ControleExecucao
from forja.agentes.estilo import PerfilTrabalho
from forja.ferramentas import verificacao as V
from tests.test_acp import _tarefa, cmd


@pytest.fixture
def projeto(tmp_path: Path) -> Path:
    p = tmp_path / "proj"
    (p / "tests").mkdir(parents=True)
    (p / "conftest.py").write_text("", encoding="utf-8")
    (p / "soma.py").write_text("def soma(a, b):\n    return a + b\n", encoding="utf-8")
    (p / "tests" / "test_soma.py").write_text("from soma import soma\n\n\ndef test_soma():\n    assert soma(2, 3) == 5\n", encoding="utf-8")
    return p


def _tarefa_proj(p: Path, criterios: list[str] | None = None) -> dict:
    return {**_tarefa("alteracao_codigo"), "criterios_aceite": criterios or ["testes passam"],
            "projeto_ctx": {"projeto": "P", "pastas": [{"caminho": str(p), "papel": "trabalho"}], "anexos": []}}


def _rodar(cenario: str, p: Path, nivel: str = "total", aprovar=None, criterios=None, correcao: str = "uma_rodada"):
    eventos: list = []
    ctl = ControleExecucao(lambda c: None, lambda t, d: eventos.append((t, d)), aprovar)
    prov = ProvedorKiroAcp(cmd(cenario), p.parent / "ws", timeout_prompt=60, timeout_handshake=10,
                           perfil_de=lambda: PerfilTrabalho(nivel=nivel, correcao=correcao, testes_timeout_s=120))
    return prov.executar(_tarefa_proj(p, criterios), {}, ctl), eventos


# ------------------------------------------------------------------ deteccao e execucao (puro)
def test_detecta_pytest_e_roda_com_ambiente_limpo(projeto, monkeypatch):
    c = V.detectar(projeto)
    assert c is not None and c.tipo == "pytest"
    monkeypatch.setenv("FORJA_INT_X_TOKEN", "segredo-que-nao-pode-vazar")
    monkeypatch.setenv("MEU_API_KEY", "outro")
    env = V.ambiente_limpo()
    assert "FORJA_INT_X_TOKEN" not in env and "MEU_API_KEY" not in env and "PATH" in {k.upper() for k in env}
    r = V.rodar(c, projeto, 120)
    assert r.ok and "APROVADO" in r.resumo


def test_sem_comando_declarado_nao_inventa(tmp_path):
    assert V.detectar(tmp_path) is None
    (tmp_path / "package.json").write_text('{"scripts": {"test": "echo \\"Error: no test specified\\" && exit 1"}}', encoding="utf-8")
    assert V.detectar(tmp_path) is None


def test_falha_traz_a_causa(projeto):
    (projeto / "soma.py").write_text("def soma(a, b):\n    return a - b\n", encoding="utf-8")
    r = V.rodar(V.detectar(projeto), projeto, 120)
    assert not r.ok and r.falhas and "test_soma" in r.falhas[0]


# ------------------------------------------------------------------ integrado ao provedor
def test_falha_vira_uma_rodada_de_correcao_e_passa(projeto):
    r, ev = _rodar("corrige", projeto)
    assert r.estado == "concluida"
    corr = next(d for t, d in ev if t == "kiro.correcao")
    assert corr["executada"] and corr["corrigiu"] and corr["aprovado_final"] and corr["rodadas"] >= 2
    assert r.consumo.chamadas_modelo == 2  # exatamente UM turno extra
    ev_testes = next(e for e in r.evidencias if e.tipo == "testes_forja")
    assert ev_testes.simulada is False and "PASSOU" in ev_testes.resumo and "corrigido" in ev_testes.resumo
    assert any(a.nome == "testes_forja.txt" for a in r.artefatos)
    assert "Correção após os testes da Forja" in r.artefatos[0].conteudo
    assert not any(p.startswith("testes_falhando") for p in r.pendencias)
    crit = next(e for e in r.evidencias if e.tipo == "criterios_forja")
    assert "testes passam -> ok" in crit.resumo


def test_sem_correcao_fica_pendente_e_nao_repete(projeto):
    r, ev = _rodar("corrige_nunca", projeto)
    corr = next(d for t, d in ev if t == "kiro.correcao")
    assert corr["executada"] and not corr["aprovado_final"] and r.consumo.chamadas_modelo == 2
    assert r.estado == "bloqueada"  # testes reais falhando: nunca conta como concluida
    assert any(p.startswith("testes_falhando") for p in r.pendencias)
    assert any(p.startswith("criterios_nao_atendidos") for p in r.pendencias)
    # "os testes passaram" do 1o turno nao se confirma: a execucao observada (da Forja) falhou
    assert any(m.tipo == "verificacao" for m in r.mensagens)


def test_nivel_liberado_pede_aprovacao_e_negar_nao_executa(projeto):
    pedidos: list = []

    def negar(itens):
        pedidos.append(itens)
        return {"aprovados": [], "adendo": "", "lembrar": False}

    r, ev = _rodar("corrige", projeto, nivel="liberado", aprovar=negar)
    assert pedidos and pedidos[0][0]["categoria"] == "executar_comando" and "testes" in pedidos[0][0]["descricao"]
    assert not any(t == "kiro.testes_forja" for t, _ in ev)
    assert any(p.startswith("testes_nao_conferidos") for p in r.pendencias)


def test_desligada_nao_roda_nada(projeto):
    r, ev = _rodar("corrige", projeto, correcao="desligada")
    assert not any(t in ("kiro.correcao", "kiro.testes_forja") for t, _ in ev) and r.consumo.chamadas_modelo == 1


def test_criterio_de_arquivo_e_conferido(projeto):
    r, _ = _rodar("corrige", projeto, criterios=["arquivo: soma.py", "arquivo: nao_existe.py", "explicar a mudanca"])
    crit = next(e for e in r.evidencias if e.tipo == "criterios_forja")
    assert "arquivo: soma.py -> ok" in crit.resumo and "nao_existe.py -> FALHOU" in crit.resumo and "-> manual" in crit.resumo


@pytest.mark.skipif(os.name != "nt" and sys.platform != "linux", reason="so validado em Windows/Linux")
def test_python_do_venv_do_projeto_tem_prioridade(projeto):
    pasta = projeto / (".venv/Scripts" if os.name == "nt" else ".venv/bin")
    pasta.mkdir(parents=True)
    exe = pasta / ("python.exe" if os.name == "nt" else "python")
    exe.write_text("", encoding="utf-8")
    assert V.detectar(projeto).args[0] == str(exe)


def test_resultado_dos_testes_aparece_na_conversa(projeto):
    r, _ = _rodar("corrige", projeto)
    assert any(m.tipo == "verificacao" and "PASSOU" in m.conteudo for m in r.mensagens)


def test_correcao_com_mesmo_tamanho_no_mesmo_segundo_nao_usa_bytecode_velho(projeto):
    """Regressao (achada no CI Linux): o .pyc e validado por mtime em segundos + tamanho. Sem cache novo por rodada, a correcao
    'a - b' -> 'a + b' (mesmo tamanho, mesmo segundo) carregava o bytecode antigo e o teste continuava falhando."""
    alvo = projeto / "soma.py"
    alvo.write_text("def soma(a, b):\n    return a - b\n", encoding="utf-8")
    c = V.detectar(projeto)
    assert not V.rodar(c, projeto, 120).ok
    st = alvo.stat()
    alvo.write_text("def soma(a, b):\n    return a + b\n", encoding="utf-8")
    os.utime(alvo, ns=(st.st_atime_ns, st.st_mtime_ns))  # forca o pior caso: mesmo tamanho E mesmo mtime
    assert V.rodar(c, projeto, 120).ok
    assert not (projeto / "__pycache__").exists()  # nada gravado na pasta do projeto
