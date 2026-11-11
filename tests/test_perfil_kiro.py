"""Perfil de seguranca "forja" no Kiro: arquivo gerado, modo aplicado na sessao, presets por nivel e falha fechada."""

from __future__ import annotations

import json
from pathlib import Path

from forja.adapters.kiro_acp import perfil_kiro
from forja.adapters.kiro_acp.provedor import ProvedorKiroAcp, montar_comando
from forja.agentes.estilo import PerfilTrabalho
from tests.test_acp import _ctl, _tarefa, cmd


def _prov(cenario: str, tmp_path: Path, nivel: str = "restrito") -> ProvedorKiroAcp:
    return ProvedorKiroAcp(cmd(cenario), tmp_path / "ws", timeout_prompt=20, timeout_handshake=10,
                           perfil_de=lambda: PerfilTrabalho(nivel=nivel))


def _com_projeto(tmp_path: Path) -> dict:
    trab = tmp_path / "proj"
    trab.mkdir()
    return {**_tarefa(), "projeto_ctx": {"projeto": "P", "pastas": [{"caminho": str(trab), "papel": "trabalho"}], "anexos": []}}


# ------------------------------------------------------------------ arquivo do perfil
def test_perfil_nega_segredos_e_libera_modelos(tmp_path):
    p = perfil_kiro.montar(protegidas=[tmp_path / "dados"])
    regras = {(r["capability"], r["effect"]): r for r in p["permissions"]["rules"]}
    leitura = regras[("fs_read", "deny")]
    assert "**/.env" in leitura["match"] and "**/.env.*" in leitura["match"]
    assert "**/.env.example" in leitura["exclude"]
    assert any(m.endswith("/dados/**") for m in leitura["match"])  # pasta de dados da Forja tambem e negada
    assert "printenv*" in regras[("shell", "deny")]["match"]
    assert "@forja" in p["tools"] and p["name"] == "forja"
    assert all(r["effect"] == "deny" for r in p["permissions"]["rules"])  # o perfil so restringe, nunca libera


def test_garantir_e_idempotente(tmp_path):
    arq = perfil_kiro.garantir(tmp_path / "agents")
    assert json.loads(arq.read_text(encoding="utf-8"))["name"] == "forja"
    antes = arq.stat().st_mtime_ns
    perfil_kiro.garantir(tmp_path / "agents")
    assert arq.stat().st_mtime_ns == antes


def test_comando_nao_usa_agent_no_v3():
    assert "--agent" not in montar_comando("kiro-cli", agente="qualquer")


# ------------------------------------------------------------------ sessao (Kiro fake)
def test_modo_forja_e_preset_restrito(tmp_path):
    ctl, eventos = _ctl()
    r = _prov("perfil", tmp_path).executar(_tarefa(), {}, ctl)
    texto = r.artefatos[0].conteudo
    assert "modo=forja" in texto and '"policyPreset": ["read-workspace"]' in texto
    assert any(t == "kiro.perfil" and d["aplicado"] for t, d in eventos)


def test_preset_liberado_edita_workspace(tmp_path):
    ctl, _ = _ctl()
    tarefa = {**_tarefa(), "modo": "alteracao_codigo"}
    texto = _prov("perfil", tmp_path, "liberado").executar(tarefa, {}, ctl).artefatos[0].conteudo
    assert '"policyPreset": ["edit-workspace"]' in texto and "modo=forja" in texto


def test_sem_perfil_em_projeto_bloqueia(tmp_path):
    ctl, _ = _ctl()
    r = _prov("perfil_sem_perfil", tmp_path).executar(_com_projeto(tmp_path), {}, ctl)
    assert r.estado == "bloqueada" and r.pendencias[0].startswith("perfil_kiro_indisponivel")


def test_sem_perfil_no_workspace_isolado_segue(tmp_path):
    ctl, eventos = _ctl()
    r = _prov("perfil_sem_perfil", tmp_path).executar(_tarefa(), {}, ctl)
    assert r.estado == "concluida" and "modo=vibe" in r.artefatos[0].conteudo  # pasta vazia: nada a vazar
    assert any(t == "kiro.perfil" and not d["aplicado"] for t, d in eventos)


def test_projeto_com_perfil_executa(tmp_path):
    ctl, _ = _ctl()
    r = _prov("perfil", tmp_path).executar(_com_projeto(tmp_path), {}, ctl)
    assert r.estado == "concluida" and "modo=forja" in r.artefatos[0].conteudo
