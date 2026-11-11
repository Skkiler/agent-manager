"""Orcamentos rigidos do turno (laco de ferramentas, limite de chamadas), lembrete do objetivo e mensagem dos testes."""

from __future__ import annotations

from pathlib import Path

from forja.adapters.kiro_acp.provedor import ProvedorKiroAcp, lembrete_objetivo, montar_acompanhamento
from forja.ferramentas import estrutura as E
from tests.test_acp import _ctl, _tarefa, cmd


def _prov(cenario: str, tmp_path: Path) -> ProvedorKiroAcp:
    return ProvedorKiroAcp(cmd(cenario), tmp_path / "ws", timeout_prompt=30, timeout_handshake=10)


def test_mesma_chamada_repetida_e_laco_e_interrompe(tmp_path):
    ctl, eventos = _ctl()
    r = _prov("laco", tmp_path).executar(_tarefa(), {}, ctl)
    assert r.estado == "bloqueada" and r.pendencias[0].startswith("laco_detectado")
    assert any(t == "kiro.orcamento" for t, _ in eventos)
    assert any(a.nome == "resposta_parcial.md" for a in r.artefatos)  # nada se perde
    assert r.mensagens and r.mensagens[0].tipo == "verificacao"


def test_limite_de_chamadas_interrompe(tmp_path):
    ctl, _ = _ctl()
    p = _prov("muitas", tmp_path)
    p.max_ferramentas = 20
    r = p.executar(_tarefa(), {}, ctl)
    assert r.estado == "bloqueada" and r.pendencias[0].startswith("orcamento_ferramentas_excedido")


def test_chamadas_variadas_abaixo_do_limite_nao_sao_laco(tmp_path):
    ctl, _ = _ctl()
    assert _prov("ok", tmp_path).executar(_tarefa(), {}, ctl).estado == "concluida"


def test_turnos_de_acompanhamento_lembram_o_objetivo():
    t = {"titulo": "Corrigir media", "criterios_aceite": ["testes passam", "arquivo: calc.py"]}
    assert lembrete_objetivo(t).startswith("Lembrete do objetivo: Corrigir media (criterios: testes passam; arquivo: calc.py)")
    assert montar_acompanhamento(["use pytest"], t).startswith("Lembrete do objetivo")
    assert lembrete_objetivo({}) == ""


def test_impacto_e_testes_afetados(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "fila.py").write_text("def criar_fila():\n    return []\n", encoding="utf-8")
    (tmp_path / "app" / "uso.py").write_text("from app.fila import criar_fila\n\n\ndef usar():\n    return criar_fila()\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_uso.py").write_text("from app.uso import usar\n\n\ndef test_u():\n    assert usar() == []\n", encoding="utf-8")
    E.limpar_cache()
    r = E.estrutura_codigo(tmp_path, ".", "impacto", "criar_fila")
    assert r.dados["definido_em"] == ["app/fila.py"] and r.dados["usado_em"] == ["app/uso.py"] and r.dados["testes"] == ["tests/test_uso.py"]
    t = E.estrutura_codigo(tmp_path, ".", "testes_afetados", "app/fila.py, app/uso.py")
    assert t.dados["testes"] == ["tests/test_uso.py"]
