"""Migracao NAO destrutiva dos dados antigos (./data, ./logs, .env) para o perfil do usuario fora do repositorio.

Copia (nunca apaga a origem), usa a API de backup do SQLite (consistente mesmo com o banco em uso) e, ao terminar, grava
`data/MIGRADO.txt`: a partir dai a Forja ignora o legado. Apague a pasta antiga manualmente quando confirmar que tudo funciona.
"""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from forja.usuario.layout import MARCADOR_MIGRADO, PerfilUsuario


@dataclass(frozen=True)
class Passo:
    tipo: str  # sqlite | arvore | arquivo
    origem: Path
    destino: Path
    bytes: int


def _tamanho(p: Path) -> int:
    return p.stat().st_size if p.is_file() else sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def planejar(raiz: Path, destino: PerfilUsuario, incluir_env: bool = False) -> list[Passo]:
    """O que seria copiado. `raiz` = pasta do projeto onde estao ./data, ./logs e .env."""
    dados, passos = raiz / "data", []
    if not dados.is_dir():
        return passos
    for banco in sorted(dados.glob("*.sqlite3")):
        passos.append(Passo("sqlite", banco, destino.dados / banco.name, _tamanho(banco)))
    for nome, sub in (("artefatos", "artefatos"), ("kiro-workspace", "workspace")):
        if (dados / nome).is_dir():
            passos.append(Passo("arvore", dados / nome, destino.pasta(sub), _tamanho(dados / nome)))
    if (dados / "api_token.txt").is_file():
        passos.append(Passo("arquivo", dados / "api_token.txt", destino.credenciais / "api_token.txt", _tamanho(dados / "api_token.txt")))
    if (raiz / "logs").is_dir():
        passos.append(Passo("arvore", raiz / "logs", destino.logs, _tamanho(raiz / "logs")))
    if incluir_env and (raiz / ".env").is_file():
        passos.append(Passo("arquivo", raiz / ".env", destino.arquivo_env, _tamanho(raiz / ".env")))
    return passos


def conflitos(passos: list[Passo]) -> list[Path]:
    return [p.destino for p in passos if p.destino.exists() and (p.destino.is_file() or any(p.destino.iterdir()))]


def _copiar_sqlite(origem: Path, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{origem.resolve().as_posix()}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(str(destino))
        try:
            src.backup(dst)
            ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            dst.close()
    finally:
        src.close()
    if ok != "ok":
        raise RuntimeError(f"integridade do banco copiado falhou: {destino.name}")


def executar(raiz: Path, destino: PerfilUsuario, passos: list[Passo]) -> None:
    destino.criar()
    for p in passos:
        if p.tipo == "sqlite":
            _copiar_sqlite(p.origem, p.destino)
        elif p.tipo == "arvore":
            shutil.copytree(p.origem, p.destino, dirs_exist_ok=True)
        else:
            p.destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p.origem, p.destino)
    marcador = raiz / "data" / MARCADOR_MIGRADO
    marcador.write_text(f"Migrado em {datetime.now(UTC).isoformat()} para {destino.raiz}\n"
                        "A Forja ignora esta pasta a partir de agora. Apague-a manualmente depois de conferir.\n", encoding="utf-8")
