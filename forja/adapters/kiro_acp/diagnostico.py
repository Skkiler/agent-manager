"""Diagnostico nao intrusivo do Kiro CLI: versao, autenticacao (booleano) e handshake ACP (sem sessao/prompt).

Nunca retorna a saida de 'whoami' (pode conter identidade); apenas se ha login. Sem consumo de creditos.
"""

from __future__ import annotations

import subprocess
from typing import Any

from forja.adapters.kiro_acp.cliente import AcpErro, ClienteAcp
from forja.adapters.kiro_acp.provedor import montar_comando, resolver_cli


def _executar(cli: str, *args: str, timeout: float = 15.0) -> tuple[int, str]:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        p = subprocess.run(  # noqa: S603 - args fixos, sem shell
            [cli, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, creationflags=flags, check=False,
        )
        return p.returncode, (p.stdout + p.stderr)
    except (subprocess.TimeoutExpired, OSError) as e:
        return -1, str(e)


def diagnosticar(cli_configurado: str = "", agente: str = "", modelo: str = "") -> dict[str, Any]:
    cli = resolver_cli(cli_configurado)
    if cli is None:
        return {"cli_encontrada": False, "versao": None, "autenticado": None, "acp_handshake": False,
                "pendencias": ["kiro_cli_ausente"]}
    rc, saida = _executar(cli, "--version")
    versao = saida.strip().splitlines()[0] if rc == 0 and saida.strip() else None
    rc_w, saida_w = _executar(cli, "whoami")
    autenticado = rc_w == 0 and "not logged in" not in saida_w.lower()
    handshake: dict[str, Any] = {"acp_handshake": False}
    cliente = ClienteAcp(montar_comando(cli, agente, modelo))
    try:
        cliente.iniciar()
        cliente.inicializar(timeout=20)
        handshake = {
            "acp_handshake": True,
            "agente": cliente.agent_info.get("name"),
            "agente_versao": cliente.agent_info.get("version"),
            "metodos_autenticacao": [m.get("id") for m in cliente.auth_methods],
            "capacidades_prompt": (cliente.capacidades.get("promptCapabilities") or {}),
        }
    except AcpErro as e:
        handshake = {"acp_handshake": False, "erro_handshake": e.mensagem[:200]}
    finally:
        cliente.encerrar()
    pend = [] if autenticado else ["reautenticacao_necessaria: execute 'kiro-cli login' (acao do usuario)"]
    return {"cli_encontrada": True, "versao": versao, "autenticado": autenticado, **handshake, "pendencias": pend}
