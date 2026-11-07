"""Deteccao de hardware e perfil de recursos (heuristica; valores sujeitos a benchmark, secao 4.4)."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import psutil

GB = 1024**3


def coletar(diretorio: Path | None = None) -> dict[str, Any]:
    vm = psutil.virtual_memory()
    disco = shutil.disk_usage(str(diretorio if diretorio and diretorio.exists() else Path.cwd()))
    bateria = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    return {
        "ram_total_gb": round(vm.total / GB, 2),
        "ram_disponivel_gb": round(vm.available / GB, 2),
        "cpu_logicos": psutil.cpu_count(logical=True),
        "cpu_fisicos": psutil.cpu_count(logical=False),
        "cpu_percent": psutil.cpu_percent(interval=0.2),
        "disco_livre_gb": round(disco.free / GB, 2),
        "bateria_percent": None if bateria is None else round(bateria.percent, 1),
    }


def decidir_perfil(m: dict[str, Any], reserva_gb: float, forcado: str = "auto") -> dict[str, Any]:
    """Perfil por regra simples. Nao ativa LLM local em nenhum caso na Fase 1."""
    if forcado != "auto":
        perfil, motivo = forcado, "forcado por configuracao"
    elif m["ram_disponivel_gb"] < reserva_gb or m["cpu_percent"] > 85:
        perfil, motivo = "essencial", "RAM livre abaixo da reserva ou CPU saturada"
    elif m["ram_total_gb"] >= 8 and (m["cpu_logicos"] or 0) >= 4:
        perfil, motivo = "equilibrado", "folga de RAM/CPU observada (sem benchmark)"
    else:
        perfil, motivo = "essencial", "hardware limitado"
    return {
        "perfil": perfil,
        "motivo": motivo,
        "local_llm_enabled": False,
        "max_workers_sugerido": 1 if perfil == "essencial" else 2,
        "fonte": "heuristica_nao_benchmarkada",
    }
