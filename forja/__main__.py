"""Entrypoint: python -m forja. Bind loopback por padrao; LAN exige aprovacao via .env."""

from __future__ import annotations

import logging

import uvicorn

from forja.config import obter_configuracoes
from forja.observabilidade.logs import configurar_logging

log = logging.getLogger("forja")


def main() -> None:
    cfg = obter_configuracoes()
    configurar_logging(cfg.app_log_level)
    if cfg.app_bind_host not in {"127.0.0.1", "localhost", "::1"}:
        log.warning("bind fora de loopback", extra={"evento": "seguranca.bind_lan", "caminho": cfg.app_bind_host})
    uvicorn.run("forja.servidor.app:criar_app", host=cfg.app_bind_host, port=cfg.app_port,
                factory=True, log_level=cfg.app_log_level.lower(), access_log=False)


if __name__ == "__main__":
    main()
