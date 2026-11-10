"""Entrypoint: python -m forja [--abrir]. Bind loopback por padrao; LAN exige aprovacao via .env.

Modelo de hospedagem: app web LOCAL (servidor so no seu computador + interface no navegador). `--abrir` abre a interface quando o
servidor responder; no Edge/Chrome, "Instalar Forja" transforma a aba em janela de aplicativo (PWA), sem empacotar outro runtime.
"""

from __future__ import annotations

import argparse
import logging
import threading
import time
import urllib.request
import webbrowser

import uvicorn

from forja.config import obter_configuracoes
from forja.observabilidade.logs import configurar_logging

log = logging.getLogger("forja")
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def endereco_local(host: str, porta: int) -> str:
    """URL que o navegador do PROPRIO computador usa (bind em 0.0.0.0/LAN continua sendo aberto por loopback)."""
    alvo = host if host in LOOPBACK else "127.0.0.1"
    return f"http://{'[::1]' if alvo == '::1' else alvo}:{porta}/"


def abrir_quando_pronto(url: str, tentativas: int = 60, intervalo: float = 0.25, abrir=webbrowser.open) -> bool:
    for _ in range(tentativas):
        try:
            with urllib.request.urlopen(url + "api/v1/saude", timeout=1):  # noqa: S310 - URL fixa em loopback
                abrir(url)
                return True
        except OSError:
            time.sleep(intervalo)
    log.warning("servidor nao respondeu a tempo; abra manualmente", extra={"evento": "abrir.timeout"})
    return False


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m forja", description="Orquestrador local Forja")
    ap.add_argument("--abrir", action="store_true", help="abre a interface no navegador quando o servidor estiver pronto")
    args = ap.parse_args(argv)
    cfg = obter_configuracoes()
    configurar_logging(cfg.app_log_level)
    if cfg.app_bind_host not in LOOPBACK:
        log.warning("bind fora de loopback", extra={"evento": "seguranca.bind_lan", "caminho": cfg.app_bind_host})
    if args.abrir:
        threading.Thread(target=abrir_quando_pronto, args=(endereco_local(cfg.app_bind_host, cfg.app_port),), daemon=True).start()
    uvicorn.run("forja.servidor.app:criar_app", host=cfg.app_bind_host, port=cfg.app_port,
                factory=True, log_level=cfg.app_log_level.lower(), access_log=False)


if __name__ == "__main__":
    main()
