"""Backup consistente do banco do usuario (API de backup do SQLite + integrity_check). Guarda os N mais recentes.

Uso: python scripts/backup_banco.py [--manter 5]
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    from forja.adapters.sqlite.banco import backup
    from forja.config import obter_configuracoes

    ap = argparse.ArgumentParser()
    ap.add_argument("--manter", type=int, default=5)
    a = ap.parse_args()
    c = obter_configuracoes()
    if not c.db_path.exists():
        print("primeira execucao: sem banco para copiar")
        return 0
    pasta = c.db_path.parent / "backups"
    destino = backup(c.db_path, pasta / f"forja-{datetime.now():%Y%m%d-%H%M%S}.sqlite3")
    for velho in sorted(pasta.glob("forja-*.sqlite3"))[: -max(1, a.manter)]:
        velho.unlink()
    print(f"backup ok: {destino.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
