"""texto.amostra: trecho numerado de um arquivo (fallback do outline quando nao ha simbolos)."""

from __future__ import annotations

from pathlib import Path

from forja.dominio.erros import ValidacaoDominio
from forja.ferramentas.caminhos import resolver_dentro
from forja.ferramentas.contrato import ResultadoFerramenta, montar
from forja.memoria.indexador import MAX_BYTES, eh_minificado

MAX_LINHAS = 200
MAX_COLUNAS = 240


def amostra_arquivo(raiz: Path, caminho: str, inicio: int = 1, linhas: int = 60) -> ResultadoFerramenta:
    if inicio < 1 or not 1 <= linhas <= MAX_LINHAS:
        raise ValidacaoDominio(f"inicio >= 1 e 1 <= linhas <= {MAX_LINHAS}")
    real = resolver_dentro(raiz, caminho)
    if real.stat().st_size > MAX_BYTES:
        raise ValidacaoDominio("arquivo acima do limite de tamanho")
    dados = real.read_bytes()
    if b"\x00" in dados[:8192]:
        raise ValidacaoDominio("arquivo binario")
    texto = dados.decode("utf-8", errors="replace")
    if eh_minificado(real.name, texto):
        raise ValidacaoDominio("arquivo minificado")
    todas = texto.splitlines()
    fatia = todas[inicio - 1 : inicio - 1 + linhas]
    corpo = [f"{inicio + i}: {ln[:MAX_COLUNAS]}" for i, ln in enumerate(fatia)]
    fim = inicio + len(fatia) - 1
    cab = f"{real.relative_to(raiz.resolve()).as_posix()} linhas {inicio}-{max(fim, inicio)} de {len(todas)}"
    avisos = ["inicio alem do fim do arquivo"] if not fatia else []
    dados_ = {"caminho": cab.split(" linhas ")[0], "inicio": inicio, "fim": fim, "total_linhas": len(todas)}
    return montar("texto.amostra", texto, "\n".join([cab, *corpo]), dados_, fim < len(todas), avisos)
