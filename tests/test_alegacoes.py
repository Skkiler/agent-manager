"""Salvaguarda anti-alucinacao: alegacoes da resposta conferidas contra ferramentas observadas e arquivos reais."""

from __future__ import annotations

from pathlib import Path

from forja.conversa.alegacoes import resumo, verificar

TESTE_OK = {"tipo": "execute", "status": "completed", "titulo": "Run Command", "comando": "python -m pytest -q"}
OUTRO_CMD = {"tipo": "execute", "status": "completed", "titulo": "Run Command", "comando": "git status"}
ESCRITA = {"tipo": "edit", "status": "completed", "titulo": "Write File"}


def _falhas(texto, ferramentas, cwd=None):
    return [(a.tipo, a.motivo) for a in verificar(texto, ferramentas, cwd) if not a.verificada]


def test_testes_passaram_sem_execucao_e_sinalizado():
    f = _falhas("Implementei a mudanca e todos os testes passaram.", [])
    assert f == [("testes", "nenhum comando foi executado nesta execucao")]


def test_testes_passaram_com_pytest_observado_e_confirmado():
    al = verificar("Os testes passaram (pytest).", [TESTE_OK])
    assert len(al) == 1 and al[0].verificada


def test_execucao_que_nao_e_teste_nao_confirma():
    assert _falhas("A suite ficou verde.", [OUTRO_CMD])[0][1].startswith("houve execucao")


def test_comando_falhou_nao_conta():
    assert _falhas("Os testes passaram.", [{**TESTE_OK, "status": "failed"}])


def test_negacao_nao_e_alegacao():
    assert verificar("Nao rodei os testes.", []) == []
    assert verificar("Ainda nao executei nada.", []) == []
    assert verificar("Nao criei `x.py`.", [], Path(".")) == []


def test_rodei_sem_execucao():
    assert ("comando", "nenhuma execucao de comando foi observada") in _falhas("Rodei o build e deu certo.", [])


def test_arquivo_criado_inexistente(tmp_path: Path):
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    assert _falhas("Criei `a.py` com a funcao.", [ESCRITA], tmp_path) == []
    f = _falhas("Criei `b.py` com a funcao.", [ESCRITA], tmp_path)
    assert f == [("arquivo_escrito", "b.py nao existe na pasta de trabalho")]
    assert _falhas("Alterei `a.py`.", [], tmp_path)[0][1] == "nenhuma escrita de arquivo foi observada"


def test_arquivo_removido_que_ainda_existe(tmp_path: Path):
    (tmp_path / "velho.txt").write_text("x", encoding="utf-8")
    assert _falhas("Removi `velho.txt`.", [ESCRITA], tmp_path)[0][0] == "arquivo_removido"


def test_citacao_inventada(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "real.py").write_text("x", encoding="utf-8")
    f = _falhas("Veja `src/real.py` e `src/inventado.py`.", [], tmp_path)
    assert f == [("arquivo_citado", "caminho citado nao existe na pasta de trabalho")]


def test_caminho_absoluto_ou_fora_nao_e_conferido(tmp_path: Path):
    assert _falhas("Veja `../fora/x.py` e `C:/abs/y.py`.", [], tmp_path) == []


def test_resumo_vazio_quando_tudo_confere():
    assert resumo(verificar("Os testes passaram.", [TESTE_OK])) == ""
    assert "não conseguiu confirmar" in resumo(verificar("Os testes passaram.", []))


# ------------------------------------------------------------------ integrado ao provedor (Kiro fake)
def test_provedor_sinaliza_alegacao_nao_verificada(tmp_path):
    from forja.adapters.kiro_acp.provedor import ProvedorKiroAcp
    from tests.test_acp import _ctl, _tarefa, cmd

    ctl, eventos = _ctl()
    r = ProvedorKiroAcp(cmd("alegacao"), tmp_path / "ws", timeout_prompt=20, timeout_handshake=10).executar(_tarefa(), {}, ctl)
    assert r.estado == "concluida"
    ver = [m for m in r.mensagens if m.tipo == "verificacao"]
    assert ver and "testes" in ver[0].conteudo
    assert any(p.startswith("alegacoes_nao_verificadas") for p in r.pendencias)
    assert any(t == "kiro.alegacoes" for t, _ in eventos)
    assert "todos os testes passaram" in r.artefatos[0].conteudo  # resposta do agente intacta
