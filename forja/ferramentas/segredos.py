"""segredos.varrer: acha possiveis segredos em arquivos SEM devolver o valor (so arquivo e linha)."""

from __future__ import annotations

import os
import re
from pathlib import Path

from forja.ferramentas.caminhos import resolver_dentro
from forja.ferramentas.contrato import ResultadoFerramenta, montar, tokens_de_bytes
from forja.memoria.indexador import IGNORAR_DIRS, MAX_BYTES
from forja.observabilidade.sanitizar import PADROES_ALTA_CONFIANCA
from forja.seguranca.acoes import caminho_sensivel
from forja.seguranca.pastas import proibido

MAX_ARQUIVOS = 3000
MAX_ACHADOS = 100
MAX_LINHA = 2000
# Atribuicao de LITERAL a um nome sensivel: `senha = "abc12345"`. `token = obter_token()` (expressao) nao conta.
_ATRIBUICAO = re.compile(r"""(?i)\b(token|secret|password|senha|passwd|api[_-]?key)\w*["']?\s*[=:]\s*["'][^"'\s]{8,}["']""")


def suspeita(linha: str) -> bool:
    return any(p.search(linha) for p in PADROES_ALTA_CONFIANCA) or bool(_ATRIBUICAO.search(linha))


def _arquivos(base: Path, alvo: Path):
    if alvo.is_file():
        yield alvo
        return
    for atual, dirs, nomes in os.walk(alvo, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in IGNORAR_DIRS and not d.endswith(".egg-info") and not proibido(Path(atual) / d))
        for nome in sorted(nomes):
            p = Path(atual) / nome
            if not p.is_symlink():
                yield p


def varrer(raiz: Path, caminho: str = ".") -> ResultadoFerramenta:
    base = raiz.resolve()
    alvo = resolver_dentro(raiz, caminho, diretorio=True) if (base / caminho).is_dir() else resolver_dentro(raiz, caminho)
    achados: list[dict] = []
    sensiveis: list[str] = []
    lidos = 0
    bytes_lidos = 0
    truncado = False
    for p in _arquivos(base, alvo):
        rel = p.resolve().relative_to(base).as_posix()
        if caminho_sensivel(rel):
            sensiveis.append(rel)  # nunca abre: so informa que existe
            continue
        try:
            if p.stat().st_size > MAX_BYTES:
                continue
            dados = p.read_bytes()
        except OSError:
            continue
        if b"\x00" in dados[:8192]:
            continue
        lidos += 1
        bytes_lidos += len(dados)
        if lidos > MAX_ARQUIVOS:
            truncado = True
            break
        for n, linha in enumerate(dados.decode("utf-8", errors="replace").splitlines(), 1):
            linha = linha[:MAX_LINHA]
            if suspeita(linha):
                achados.append({"arquivo": rel, "linha": n})
                if len(achados) >= MAX_ACHADOS:
                    truncado = True
                    break
        if len(achados) >= MAX_ACHADOS:
            break
    linhas = [f"{lidos} arquivo(s) varridos; {len(achados)} possivel(is) segredo(s); {len(sensiveis)} arquivo(s) sensivel(is)"]
    linhas += [f"- {a['arquivo']}:{a['linha']}" for a in achados[:MAX_ACHADOS]]
    linhas += [f"- SENSIVEL (nao aberto): {s}" for s in sensiveis[:20]]
    if truncado:
        linhas.append("(varredura interrompida no limite; refine o caminho)")
    dados = {"arquivos_lidos": lidos, "achados": achados, "sensiveis": sensiveis[:50]}
    avisos = ["heuristica por padroes: ausencia de achados nao prova ausencia de segredos"]
    return montar("segredos.varrer", "", "\n".join(linhas), dados, truncado, avisos,
                  tokens_origem=tokens_de_bytes(bytes_lidos))
