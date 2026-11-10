"""Smoke test ponta a ponta contra um servidor Forja ja em execucao.

Uso (com o servidor rodando):
    python scripts/smoke.py --base http://127.0.0.1:8787 --token <TOKEN>

Cria projeto/objetivo/tarefa sinteticos, executa via agente mock e verifica a conclusao real.
Encerra com codigo 0 em sucesso, 1 em falha. Nao usa credenciais empresariais nem dados reais.
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def _req(base: str, token: str | None, metodo: str, caminho: str, corpo: dict | None = None) -> dict:
    import json

    url = base.rstrip("/") + caminho
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(url, data=dados, method=metodo)  # noqa: S310 - URL local controlada
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
        txt = resp.read().decode()
    return json.loads(txt) if txt else {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8787")
    ap.add_argument("--token", default=None)
    args = ap.parse_args()

    token = args.token
    if token is None:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from forja.usuario.layout import resolver_perfil

        arq = resolver_perfil().credenciais / "api_token.txt"
        if arq.exists():
            token = arq.read_text(encoding="utf-8").strip()

    try:
        saude = _req(args.base, None, "GET", "/api/v1/saude")
        print(f"[ok] saude: {saude}")
        p = _req(args.base, token, "POST", "/api/v1/projetos", {"nome": f"smoke-{int(time.time())}"})
        o = _req(args.base, token, "POST", "/api/v1/objetivos", {"projeto_id": p["id"], "titulo": "smoke"})
        t = _req(args.base, token, "POST", "/api/v1/tarefas", {
            "objetivo_id": o["id"], "titulo": "tarefa smoke", "criterios_aceite": ["mock conclui"],
            "entrada": {"mock_cenario": "sucesso", "mock_passos": 3}})
        c = _req(args.base, token, "POST", f"/api/v1/tarefas/{t['id']}/transicao",
                 {"para": "classificada", "expected_version": t["versao_estado"]})
        _req(args.base, token, "POST", f"/api/v1/tarefas/{t['id']}/transicao",
             {"para": "preparada", "expected_version": c["versao_estado"]})
        ex = _req(args.base, token, "POST", f"/api/v1/tarefas/{t['id']}/execucoes")
        _req(args.base, token, "POST", f"/api/v1/execucoes/{ex['id']}/iniciar")
        estado = ""
        for _ in range(100):
            estado = _req(args.base, token, "GET", f"/api/v1/execucoes/{ex['id']}")["estado"]
            if estado in ("concluida", "falhou", "cancelada", "expirada"):
                break
            time.sleep(0.1)
        final = _req(args.base, token, "GET", f"/api/v1/tarefas/{t['id']}")
        print(f"[info] execucao={estado} tarefa={final['estado']} "
              f"evidencias={len(final['evidencias'])} artefatos={len(final['artefatos'])}")
        ok = final["estado"] == "concluida" and final["evidencias"] and final["artefatos"]
        if ok:
            print("[sucesso] fluxo ponta a ponta concluido com evidencia (SIMULADA pelo mock).")
            return 0
        print("[falha] estado final inesperado.")
        return 1
    except urllib.error.HTTPError as e:  # noqa: PERF203
        print(f"[falha] HTTP {e.code}: {e.read().decode()[:400]}")
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"[falha] erro inesperado: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
