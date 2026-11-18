"""codigo.buscar: busca de texto (literal ou regex) em varios arquivos, SEM passar por segredos.

Por que existe: buscar texto e a operacao mais comum do agente. Sem esta ferramenta ele usa o shell (grep -r, Select-String,
Get-ChildItem -Recurse), o que pede permissao (custa tempo) ou, com autonomia alta, le o .env junto (achado no Kiro real).
Aqui a varredura pula arquivos com cara de segredo, pastas de dependencias, links simbolicos, binarios e arquivos grandes, e a
saida e compacta (arquivo:linha: trecho), com segredos redigidos. Somente leitura; nada e executado.
"""

from __future__ import annotations

import fnmatch
import os
import re
import time
from pathlib import Path

from forja.dominio.erros import ValidacaoDominio
from forja.ferramentas.caminhos import resolver_dentro
from forja.ferramentas.contrato import ResultadoFerramenta, montar
from forja.memoria.indexador import IGNORAR_DIRS
from forja.seguranca.pastas import proibido
from forja.seguranca.sensiveis import DEPENDENCIAS, caminho_sensivel

MAX_ARQUIVO = 2 * 1024 * 1024
MAX_ARQUIVOS = 20_000
MAX_COLUNA = 240
TEMPO_MAX_S = 8.0
_PULAR = frozenset(IGNORAR_DIRS | DEPENDENCIAS)
# Quantificador aninhado ((a+)+, (a*)*...) = risco de travar o regex (ReDoS): recusado. As linhas tambem sao cortadas.
_ANINHADO = re.compile(r"\([^)]*[+*][^)]*\)\s*[+*{]")


def _compilar(padrao: str, regex: bool, ignorar_maiusculas: bool) -> re.Pattern[str]:
    if not padrao:
        raise ValidacaoDominio("informe o texto a buscar")
    flags = re.IGNORECASE if ignorar_maiusculas else 0
    if not regex:
        return re.compile(re.escape(padrao), flags)
    if _ANINHADO.search(padrao):
        raise ValidacaoDominio("regex com quantificador aninhado (ex.: (a+)+) nao e aceito: risco de travar a busca")
    try:
        return re.compile(padrao, flags)
    except re.error as e:
        raise ValidacaoDominio(f"regex invalido: {e}") from e


def _binario(amostra: bytes) -> bool:
    return b"\x00" in amostra


def _arquivos(base: Path, incluir: str):
    if base.is_file():
        yield base
        return
    for atual, dirs, nomes in os.walk(base, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in _PULAR and not d.endswith(".egg-info") and not Path(atual, d).is_symlink()
                         and not proibido(Path(atual) / d))
        for nome in sorted(nomes):
            if incluir and not fnmatch.fnmatch(nome, incluir):
                continue
            yield Path(atual) / nome


def buscar_texto(raiz: Path, caminho: str = ".", padrao: str = "", regex: bool = False, ignorar_maiusculas: bool = True,
                 incluir: str = "", contexto: int = 0, limite: int = 50) -> ResultadoFerramenta:
    expr = _compilar(padrao, regex, ignorar_maiusculas)
    if caminho in ("", "."):
        alvo = raiz.resolve()
    else:
        try:
            alvo = resolver_dentro(raiz, caminho, diretorio=True)
        except ValidacaoDominio as e:
            if "diretorio" not in str(getattr(e, "mensagem", e)):
                raise
            alvo = resolver_dentro(raiz, caminho)  # e um arquivo
    base_rel = raiz.resolve()
    t0 = time.monotonic()
    ocorrencias: list[dict] = []
    arquivos_com, vistos, bytes_lidos, segredos_pulados, grandes = set(), 0, 0, 0, 0
    truncado, tempo_esgotado = False, False
    for p in _arquivos(alvo, incluir):
        try:
            rel = p.resolve().relative_to(base_rel).as_posix()
        except (ValueError, OSError):
            continue
        if p.is_symlink() or caminho_sensivel(rel) or proibido(p):
            segredos_pulados += int(caminho_sensivel(rel))
            continue
        vistos += 1
        if vistos > MAX_ARQUIVOS or time.monotonic() - t0 > TEMPO_MAX_S:
            tempo_esgotado = time.monotonic() - t0 > TEMPO_MAX_S
            truncado = True
            break
        try:
            tamanho = p.stat().st_size
            if tamanho > MAX_ARQUIVO:
                grandes += 1
                continue
            dados = p.read_bytes()
        except OSError:
            continue
        if _binario(dados[:4096]):
            continue
        bytes_lidos += len(dados)
        linhas = dados.decode("utf-8", errors="replace").splitlines()
        for i, linha in enumerate(linhas):
            if not expr.search(linha[:4000]):
                continue
            item = {"arquivo": rel, "linha": i + 1, "texto": linha.strip()[:MAX_COLUNA]}
            if contexto:
                item["antes"] = [x.rstrip()[:MAX_COLUNA] for x in linhas[max(0, i - contexto):i]]
                item["depois"] = [x.rstrip()[:MAX_COLUNA] for x in linhas[i + 1:i + 1 + contexto]]
            ocorrencias.append(item)
            arquivos_com.add(rel)
            if len(ocorrencias) >= limite:
                truncado = True
                break
        if len(ocorrencias) >= limite:
            break
    cab = f"{len(ocorrencias)} ocorrencia(s) de '{padrao[:60]}' em {len(arquivos_com)} arquivo(s) ({vistos} varridos)"
    linhas_saida = [cab]
    for o in ocorrencias:
        for a in o.get("antes", []):
            linhas_saida.append(f"  {o['arquivo']}-  {a}")
        linhas_saida.append(f"{o['arquivo']}:{o['linha']}: {o['texto']}")
        for d in o.get("depois", []):
            linhas_saida.append(f"  {o['arquivo']}-  {d}")
    avisos = []
    if segredos_pulados:
        avisos.append(f"{segredos_pulados} arquivo(s) de segredo pulados (nunca sao lidos)")
    if grandes:
        avisos.append(f"{grandes} arquivo(s) acima de 2 MB pulados")
    if tempo_esgotado:
        avisos.append("busca interrompida pelo tempo maximo; restrinja a pasta ou use 'incluir'")
    elif truncado:
        avisos.append(f"limite de {limite} ocorrencias atingido; refine o padrao")
    dados_saida = {"ocorrencias": ocorrencias, "arquivos": sorted(arquivos_com), "varridos": vistos,
                   "segredos_pulados": segredos_pulados, "truncado": truncado}
    return montar("codigo.buscar", "", "\n".join(linhas_saida), dados_saida, truncado, avisos, bytes_lidos // 4)
