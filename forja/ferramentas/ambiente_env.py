"""Validar um .env SEM revelar valores: o agente pergunta, a Forja responde fatos booleanos e NOMES de variaveis.

Respostas possiveis: a variavel existe? esta vazia? tem o formato esperado (url, inteiro, porta, booleano, email, caminho)? e igual a
um valor que o agente informou? quais chaves do .env.example faltam (ou sobram)? ha linhas mal formadas ou chaves duplicadas?
Nunca: o valor, parte dele, tamanho exato, prefixo ou regex arbitraria (cada uma vazaria o segredo aos poucos).

Comparacao de igualdade e um oraculo: tempo constante (hmac.compare_digest) e no maximo LIMITE_COMPARACOES por chave a cada janela,
para que nao vire um jeito de adivinhar o segredo por tentativa e erro.
"""

from __future__ import annotations

import hmac
import re
import threading
import time
from pathlib import Path
from typing import Any

from forja.dominio.erros import ValidacaoDominio
from forja.ferramentas.contrato import ResultadoFerramenta, montar

NOME_ENV = re.compile(r"^\.env(\.[A-Za-z0-9_-]+)?$")
CHAVE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,99}$")
LINHA = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")
FORMATOS = {
    "nao_vazio": lambda v: bool(v.strip()),
    "url": lambda v: re.fullmatch(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s/]+\S*", v) is not None,
    "inteiro": lambda v: re.fullmatch(r"[+-]?\d+", v) is not None,
    "porta": lambda v: v.isdigit() and 1 <= int(v) <= 65535,
    "booleano": lambda v: v.strip().lower() in {"true", "false", "1", "0", "yes", "no", "sim", "nao", "on", "off"},
    "email": lambda v: re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v) is not None,
    "caminho_existente": lambda v: bool(v) and Path(v).expanduser().exists(),
}
LIMITE_COMPARACOES = 3
JANELA_S = 600
MAX_CHAVES = 50
_comparacoes: dict[tuple[str, str], list[float]] = {}
_mu = threading.Lock()


def _valor(bruto: str) -> str:
    v = bruto.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return re.sub(r"\s+#.*$", "", v)  # comentario no fim da linha (sem aspas)


def ler_env(caminho: Path) -> tuple[dict[str, str], list[int], list[str]]:
    """(valores, linhas mal formadas, chaves duplicadas). Os VALORES nunca saem deste modulo."""
    valores: dict[str, str] = {}
    ruins, duplicadas = [], []
    for n, linha in enumerate(caminho.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if not linha.strip() or linha.lstrip().startswith("#"):
            continue
        m = LINHA.match(linha)
        if not m:
            ruins.append(n)
            continue
        if m.group(1) in valores:
            duplicadas.append(m.group(1))
        valores[m.group(1)] = _valor(m.group(2))
    return valores, ruins, sorted(set(duplicadas))


def _pode_comparar(arquivo: Path, chave: str, agora: float | None = None) -> bool:
    agora = time.monotonic() if agora is None else agora
    k = (str(arquivo), chave)
    with _mu:
        recentes = [t for t in _comparacoes.get(k, []) if agora - t < JANELA_S]
        if len(recentes) >= LIMITE_COMPARACOES:
            _comparacoes[k] = recentes
            return False
        _comparacoes[k] = [*recentes, agora]
        return True


def verificar(arquivo: Path, chaves: list[str], formatos: dict[str, str], comparar: dict[str, str], exemplo: Path | None) -> ResultadoFerramenta:
    todas = list(dict.fromkeys([*chaves, *formatos, *comparar]))
    if len(todas) > MAX_CHAVES or not all(CHAVE.fullmatch(c) for c in todas):
        raise ValidacaoDominio(f"informe ate {MAX_CHAVES} nomes de variavel validos (LETRAS_E_NUMEROS)")
    desconhecidos = sorted(set(formatos.values()) - set(FORMATOS))
    if desconhecidos:
        raise ValidacaoDominio(f"formatos aceitos: {', '.join(FORMATOS)}")
    valores, ruins, duplicadas = ler_env(arquivo)
    por_chave: dict[str, dict[str, Any]] = {}
    for c in todas:
        info: dict[str, Any] = {"existe": c in valores}
        if c in valores:
            info["vazia"] = not valores[c].strip()
            if c in formatos:
                info[f"formato_{formatos[c]}"] = bool(FORMATOS[formatos[c]](valores[c]))
            if c in comparar:
                info["igual_ao_informado"] = (hmac.compare_digest(valores[c].encode(), str(comparar[c]).encode())
                                              if _pode_comparar(arquivo, c) else "limite de comparacoes atingido; tente mais tarde")
        por_chave[c] = info
    dados: dict[str, Any] = {"arquivo": arquivo.name, "variaveis": len(valores), "linhas_mal_formadas": ruins[:20], "chaves_duplicadas": duplicadas[:20],
                             "verificacoes": por_chave}
    if exemplo is not None and exemplo.is_file():
        esperadas, _r, _d = ler_env(exemplo)
        dados["faltando_em_relacao_ao_exemplo"] = sorted(set(esperadas) - set(valores))[:MAX_CHAVES]
        dados["sobrando_em_relacao_ao_exemplo"] = sorted(set(valores) - set(esperadas))[:MAX_CHAVES]
        dados["vazias_que_o_exemplo_espera"] = sorted(k for k in esperadas if k in valores and not valores[k].strip())[:MAX_CHAVES]
    linhas = [f"{arquivo.name}: {len(valores)} variavel(is)" + (f", {len(ruins)} linha(s) mal formada(s) (linhas {ruins[:10]})" if ruins else "")]
    if duplicadas:
        linhas.append(f"duplicadas: {', '.join(duplicadas[:10])}")
    for c, info in por_chave.items():
        partes = ["existe" if info["existe"] else "NAO existe"]
        if info.get("vazia"):
            partes.append("vazia")
        partes += [f"{k.removeprefix('formato_')}={'ok' if v else 'INVALIDO'}" for k, v in info.items() if k.startswith("formato_")]
        if "igual_ao_informado" in info:
            v = info["igual_ao_informado"]
            partes.append(("igual ao informado" if v else "DIFERENTE do informado") if isinstance(v, bool) else str(v))
        linhas.append(f"- {c}: {', '.join(partes)}")
    if "faltando_em_relacao_ao_exemplo" in dados:
        linhas.append(f"faltam (vs exemplo): {', '.join(dados['faltando_em_relacao_ao_exemplo']) or 'nenhuma'}")
        if dados["vazias_que_o_exemplo_espera"]:
            linhas.append(f"vazias (o exemplo espera valor): {', '.join(dados['vazias_que_o_exemplo_espera'])}")
    return montar("env.verificar", "", "\n".join(linhas), dados, False,
                  ["valores nunca sao mostrados; so existencia, formato e igualdade (com limite de tentativas)"], tokens_origem=0)
