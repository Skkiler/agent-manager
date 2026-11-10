"""Move (copiando) os dados antigos de ./data para o perfil do usuario FORA do repositorio.

Uso:  python scripts/migrar_dados_usuario.py                (simulacao: mostra o plano)
      python scripts/migrar_dados_usuario.py --executar     (copia, valida os bancos e marca data/ como migrada)
Opcoes: --incluir-env (copia o .env do projeto para credenciais/.env), --sobrescrever (aceita destino ja existente).
Nunca apaga a origem. Destino: APP_USER_HOME/perfis/<perfil> (ou a pasta de dados do sistema).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from forja.usuario.layout import resolver_perfil  # noqa: E402
from forja.usuario.migracao import conflitos, executar, planejar  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--executar", action="store_true")
    ap.add_argument("--incluir-env", action="store_true")
    ap.add_argument("--sobrescrever", action="store_true")
    a = ap.parse_args()
    destino = resolver_perfil(permitir_legado=False, cwd=RAIZ)
    passos = planejar(RAIZ, destino, a.incluir_env)
    print(f"origem : {RAIZ / 'data'}\ndestino: {destino.raiz}")
    if not passos:
        print("nada a migrar (nao ha ./data).")
        return 0
    for p in passos:
        print(f"  {p.tipo:<8} {p.origem.relative_to(RAIZ)}  ->  {p.destino.relative_to(destino.raiz)}  ({p.bytes / 1024:.0f} KB)")
    ja = conflitos(passos)
    if ja and not a.sobrescrever:
        print(f"\nrecusado: o destino ja tem dados ({len(ja)} item(ns)). Use --sobrescrever se tiver certeza.")
        return 2
    if not a.executar:
        print("\nsimulacao: nada foi copiado. Rode com --executar.")
        return 0
    executar(RAIZ, destino, passos)
    print("\nmigrado. ./data foi marcada com MIGRADO.txt (a Forja a ignora). Confira e apague a pasta antiga manualmente.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
