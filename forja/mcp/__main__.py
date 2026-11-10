"""Ponto de entrada: `python -m forja.mcp` (iniciado pelo Kiro via ACP; nao escuta porta nenhuma)."""

from forja.mcp.servidor import principal

raise SystemExit(principal())
