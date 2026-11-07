"""Diagnostico do Kiro CLI (versao, login sim/nao, handshake ACP). Nao inicia sessao nem consome creditos.

Uso: python scripts/diagnostico_kiro.py   (le APP_KIRO_CLI_PATH/APP_KIRO_AGENT/APP_KIRO_MODEL do ambiente/.env)
Nunca imprime identidade, tokens ou saida de 'whoami'.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from forja.adapters.kiro_acp.diagnostico import diagnosticar  # noqa: E402
from forja.config import Configuracoes  # noqa: E402

if __name__ == "__main__":
    cfg = Configuracoes()
    print(json.dumps(diagnosticar(cfg.app_kiro_cli_path, cfg.app_kiro_agent, cfg.app_kiro_model),
                     indent=2, ensure_ascii=False))
