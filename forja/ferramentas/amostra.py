"""texto.amostra: trecho numerado de um arquivo (fallback do outline quando nao ha simbolos)."""

from __future__ import annotations

from pathlib import Path

from forja.dominio.erros import ValidacaoDominio
from forja.ferramentas.caminhos import resolver_dentro
from forja.ferramentas.contrato import ResultadoFerramenta, montar
from forja.memoria.indexador import MAX_BYTES, eh_minificado

MAX_LINHAS = 200
MAX_COLUNAS = 240


def amostra_arquivo(raiz: Path, caminho: str, inicio: int = 1, linhas: int = 60, buscar: str = "") -> ResultadoFerramenta:
    """`buscar` (texto, sem diferenciar maiusculas): a janela comeca 5 linhas antes da 1a ocorrencia a partir de `inicio`.
    Evita o agente ler trechos grandes so para achar uma linha."""
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
    achou = None
    if buscar:
        alvo = buscar.casefold()
        achou = next((i + 1 for i in range(inicio - 1, len(todas)) if alvo in todas[i].casefold()), None)
        if achou is None:
            cab = f"{real.relative_to(raiz.resolve()).as_posix()}: '{buscar[:60]}' nao encontrado a partir da linha {inicio}"
            return montar("texto.amostra", texto, cab, {"caminho": real.relative_to(raiz.resolve()).as_posix(), "encontrado": False,
                                                        "total_linhas": len(todas)}, False, [])
        inicio = max(1, achou - 5)
    fatia = todas[inicio - 1 : inicio - 1 + linhas]
    corpo = [f"{inicio + i}: {ln[:MAX_COLUNAS]}" for i, ln in enumerate(fatia)]
    fim = inicio + len(fatia) - 1
    cab = f"{real.relative_to(raiz.resolve()).as_posix()} linhas {inicio}-{max(fim, inicio)} de {len(todas)}"
    avisos = ["inicio alem do fim do arquivo"] if not fatia else []
    dados_ = {"caminho": cab.split(" linhas ")[0], "inicio": inicio, "fim": fim, "total_linhas": len(todas),
              **({"encontrado": True, "linha_encontrada": achou} if achou else {})}
    return montar("texto.amostra", texto, "\n".join([cab, *corpo]), dados_, fim < len(todas), avisos)
