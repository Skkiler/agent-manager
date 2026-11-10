"""Descritor de acoes: comando bruto -> pergunta em linguagem natural, categoria e risco."""

from __future__ import annotations

from pathlib import Path

import pytest

from forja.seguranca.acoes import descrever_acao


def _cmd(cmd: str, **extra) -> dict:
    return {"toolCallId": "t1", "title": "Run command", "kind": "execute", "rawInput": {"command": cmd}, **extra}


def test_exemplo_do_usuario_rm_rf_vira_exclusao_forcada():
    a = descrever_acao(_cmd("rm -rf build dist"))
    assert a["categoria"] == "excluir_forcado" and a["risco"] == "critico"
    assert a["descricao"].startswith("Posso excluir forçadamente")
    assert "`build`" in a["descricao"] and "`dist`" in a["descricao"]
    assert a["alvos"] == ["build", "dist"]


@pytest.mark.parametrize("cmd", [
    "Remove-Item -Recurse -Force .\\cache",
    "rd /s /q cache",
    "del /f /q cache",
])
def test_formas_windows_de_exclusao_forcada(cmd):
    assert descrever_acao(_cmd(cmd))["categoria"] == "excluir_forcado"


def test_exclusao_simples_e_menos_grave_que_forcada():
    a = descrever_acao(_cmd("rm arquivo.tmp"))
    assert a["categoria"] == "excluir" and a["risco"] == "alto"
    assert a["descricao"].startswith("Posso excluir `arquivo.tmp`")


def test_escrita_de_arquivo_usa_kind_e_rawinput_do_tool_call():
    # formato REAL observado no Kiro CLI: kind=edit, rawInput={path,text}, title='Write File'
    a = descrever_acao({"toolCallId": "t2", "title": "Write File", "kind": "edit",
                        "rawInput": {"path": "teste.txt", "text": "ola"}})
    assert a["categoria"] == "modificar_arquivos" and a["alvos"] == ["teste.txt"]
    assert a["descricao"] == "Posso criar ou modificar `teste.txt`?"


@pytest.mark.parametrize(("cmd", "categoria"), [
    ("git push origin main", "publicar"),
    ("git reset --hard HEAD~3", "descartar_alteracoes"),
    ("pip install requests", "instalar_dependencias"),
    ("curl https://exemplo.invalid/x", "acessar_rede"),
    ("mv a.txt b.txt", "mover"),
    ("python -m pytest", "executar_comando"),
])
def test_categorias_de_comando(cmd, categoria):
    assert descrever_acao(_cmd(cmd))["categoria"] == categoria


def test_leitura_tem_risco_baixo():
    a = descrever_acao({"toolCallId": "r", "title": "Read", "kind": "read", "locations": [{"path": "README.md"}]})
    assert a["categoria"] == "ler" and a["risco"] == "baixo"


@pytest.mark.parametrize("alvo", [".env", "config/.env.local", "chaves/id_rsa", "x/servidor.pem", "credentials.json",
                                  "data/api_token.txt"])
def test_segredos_sao_sensiveis_e_criticos(alvo):
    a = descrever_acao({"toolCallId": "s", "title": "Read", "kind": "read", "locations": [{"path": alvo}]})
    assert a["sensivel"] is True and a["risco"] == "critico"


def test_comando_que_toca_segredo_e_sensivel():
    assert descrever_acao(_cmd("type .env"))["sensivel"] is True


def test_fora_do_workspace_sobe_o_risco(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    dentro = descrever_acao({"toolCallId": "a", "title": "Write File", "kind": "edit",
                             "rawInput": {"path": "ok.txt"}}, ws)
    fora = descrever_acao({"toolCallId": "b", "title": "Write File", "kind": "edit",
                           "rawInput": {"path": "..\\fora.txt"}}, ws)
    assert dentro["fora_do_workspace"] is False and dentro["risco"] == "medio"
    assert fora["fora_do_workspace"] is True and fora["risco"] == "alto"


def test_alvo_duplicado_e_caminho_absoluto_dentro_do_workspace(tmp_path: Path):
    """Regressao do Kiro real: o mesmo caminho vinha em locations E rawInput, absoluto e longo."""
    ws = tmp_path / "ws"
    ws.mkdir()
    absoluto = str(ws / "teste.txt")
    a = descrever_acao({"toolCallId": "x", "title": "Write File", "kind": "edit",
                        "locations": [{"path": absoluto}], "rawInput": {"path": absoluto, "text": "ola"}}, ws)
    assert a["alvos"] == ["teste.txt"]
    assert a["descricao"] == "Posso criar ou modificar `teste.txt`?"
    assert a["fora_do_workspace"] is False and a["risco"] == "medio"
    assert str(tmp_path) not in a["descricao"]  # nao vaza o diretorio do usuario na pergunta


def test_caminho_absoluto_fora_do_workspace_continua_completo_e_de_risco_alto(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    fora = str(tmp_path / "outro" / "x.txt")
    a = descrever_acao({"toolCallId": "y", "title": "Write File", "kind": "edit", "rawInput": {"path": fora}}, ws)
    assert a["fora_do_workspace"] is True and a["risco"] == "alto" and a["alvos"] == [fora]


def test_acao_desconhecida_nao_quebra_e_e_sanitizada():
    a = descrever_acao({"title": "Coisa estranha token=abc123segredo"})
    assert a["categoria"] == "outra" and "abc123segredo" not in a["descricao"]
    assert descrever_acao({})["categoria"] == "outra"  # entrada vazia/mal formada


def test_muitos_alvos_sao_resumidos():
    a = descrever_acao(_cmd("rm -rf " + " ".join(f"d{i}" for i in range(10))))
    assert len(a["alvos"]) == 6 and "(+" in a["descricao"]


@pytest.mark.parametrize("caminho", ["..\\fora.txt", "sub\\..\\..\\fora.txt", "../fora.txt"])
def test_barra_invertida_conta_como_separador_em_qualquer_so(tmp_path: Path, caminho: str):
    """Regressao achada no CI (Linux): '..\\x' nao era 'fora do workspace' porque '\\' nao e separador no POSIX."""
    ws = tmp_path / "ws"
    ws.mkdir()
    assert descrever_acao({"toolCallId": "x", "kind": "edit", "rawInput": {"path": caminho}}, ws)["fora_do_workspace"] is True
    assert descrever_acao({"toolCallId": "y", "kind": "edit", "rawInput": {"path": "sub\\ok.txt"}}, ws)["fora_do_workspace"] is False
