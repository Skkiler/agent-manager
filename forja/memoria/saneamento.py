"""Saneamento de conteudo antes de gravar/indexar: PII, segredos e deteccao de prompt injection.

Heuristico por natureza: reduz risco, nao o elimina. Todo conteudo recuperado continua sendo tratado como DADO
nao confiavel (nunca como instrucao) pelos consumidores.
"""

from __future__ import annotations

import re
import unicodedata

from forja.observabilidade.sanitizar import REDACTED, redigir_segredos

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_CPF = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
_CNPJ = re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b")
_TELEFONE = re.compile(r"(?<!\d)(?:\+?55\s?)?\(?\d{2}\)?[\s.-]?9?\d{4}[\s.-]?\d{4}(?!\d)")
_CARTAO = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")

_INJECAO = [re.compile(p, re.IGNORECASE) for p in (
    r"ignor(e|ar|em)\s+(todas?\s+)?(as\s+)?(instru[cç][oõ]es|regras|ordens)\s*(anteriores|acima|previas)?",
    r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|rules|prompts?)",
    r"disregard\s+(the\s+)?(system|previous)\s+(prompt|instructions)",
    r"(revele|mostre|exiba|imprima|reveal|show|print|leak)\s+.{0,40}"
    r"(\.env|senha|password|token|segredo|secret|api[_ -]?key|credencia)",
    r"(system\s+prompt|prompt\s+do\s+sistema|instru[cç][oõ]es\s+do\s+sistema)",
    r"voc[eê]\s+agora\s+[eé]\s+|you\s+are\s+now\s+",
    r"(execute|rode|run)\s+.{0,30}(rm\s+-rf|remove-item|curl\s|wget\s|invoke-webrequest|powershell\s+-enc)",
    r"<\s*(system|assistant)\s*>|\[\s*inst\s*\]",
)]


def _luhn(digitos: str) -> bool:
    soma, alt = 0, False
    for d in reversed(digitos):
        n = int(d)
        if alt:
            n = n * 2 - 9 if n * 2 > 9 else n * 2
        soma += n
        alt = not alt
    return soma % 10 == 0


def _cartao(m: re.Match[str]) -> str:
    bruto = re.sub(r"\D", "", m.group(0))
    return REDACTED if 13 <= len(bruto) <= 19 and _luhn(bruto) else m.group(0)


def redigir_pii(texto: str) -> tuple[str, list[str]]:
    """Retorna (texto_redigido, tipos_encontrados). Segredos tambem sao redigidos."""
    achados: list[str] = []

    def troca(padrao: re.Pattern[str], nome: str, s: str) -> str:
        novo, n = padrao.subn(REDACTED, s)
        if n:
            achados.append(nome)
        return novo

    s = redigir_segredos(texto)
    if s != texto:
        achados.append("segredo")
    s = troca(_EMAIL, "email", s)
    s = troca(_CNPJ, "cnpj", s)
    s = troca(_CPF, "cpf", s)
    antes = s
    s = _CARTAO.sub(_cartao, s)
    if s != antes:
        achados.append("cartao")
    s = troca(_TELEFONE, "telefone", s)
    return s, sorted(set(achados))


def redigir_objeto(obj: object, _nivel: int = 0) -> object:
    """Redige PII/segredos em TODAS as strings de uma estrutura JSON, preservando a forma (nunca vira JSON invalido)."""
    if _nivel > 8:
        return "[profundidade-limitada]"
    if isinstance(obj, dict):
        return {str(k): redigir_objeto(v, _nivel + 1) for k, v in list(obj.items())[:100]}
    if isinstance(obj, list | tuple):
        return [redigir_objeto(v, _nivel + 1) for v in list(obj)[:200]]
    if isinstance(obj, str):
        return redigir_pii(obj)[0]
    return obj if isinstance(obj, int | float | bool) or obj is None else redigir_pii(str(obj))[0]


def detectar_injecao(texto: str) -> list[str]:
    """Padroes tipicos de prompt injection em documentos. Retorna os trechos suspeitos (curtos)."""
    achados: list[str] = []
    for p in _INJECAO:
        m = p.search(texto)
        if m:
            achados.append(m.group(0)[:80])
    return achados


def estimar_tokens(texto: str) -> int:
    """ESTIMATIVA grosseira (~4 caracteres por token); nao e contagem do provedor."""
    return max(1, (len(texto) + 3) // 4)


def normalizar_consulta(q: str) -> list[str]:
    """Tokens seguros para FTS5 (sem operadores): letras/digitos/_ , minusculas, sem acento nao e aplicado aqui."""
    q = unicodedata.normalize("NFKC", q)
    return [t for t in re.findall(r"\w+", q, flags=re.UNICODE) if t][:12]


def consulta_fts(tokens: list[str], modo: str = "and") -> str:
    """Monta MATCH seguro: cada token entre aspas (neutraliza AND/OR/NEAR/colunas); prefixo no ultimo token."""
    if not tokens:
        return ""
    termos = [f'"{t.replace(chr(34), "")}"' for t in tokens]
    termos[-1] += "*"
    return (" OR " if modo == "or" else " ").join(termos)
