"""Briefing: a resposta do agente em secoes de conversa (entendimento, resposta, premissas, decisoes, proximos passos).

Puro e tolerante: se o modelo ignorar o formato, cai em uma unica mensagem 'resposta' (nunca perde conteudo nem falha).
As DECISOES sao o ponto central da comunicacao organica: o agente as agrupa todas, cada uma com recomendacao e
alternativas, para o desenvolvedor responder UMA vez em texto livre (em vez de uma pergunta por turno).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

SECOES = ("entendimento", "plano", "resposta", "evidencias", "premissas", "decisoes", "riscos", "proximos_passos", "notas")
_ALIASES = {
    "entendimento": "entendimento", "resumo": "entendimento", "contexto": "entendimento",
    "resposta": "resposta", "resultado": "resposta", "analise": "resposta", "conclusao": "resposta",
    "premissas": "premissas", "suposicoes": "premissas", "hipoteses": "premissas",
    "decisoes": "decisoes", "decisoes para voce": "decisoes", "decisoes para voce decidir": "decisoes",
    "perguntas": "decisoes", "precisa de voce": "decisoes", "decisoes necessarias": "decisoes",
    "riscos": "riscos", "riscos e cuidados": "riscos",
    "evidencias": "evidencias", "evidencia": "evidencias", "verificacao": "evidencias", "o que foi feito": "evidencias",
    "plano": "plano", "plano de execucao": "plano", "plano de acao": "plano",
    "notas": "notas", "notas para o segundo cerebro": "notas",
    "proximos passos": "proximos_passos", "proximo passo": "proximos_passos", "proximos": "proximos_passos",
}
_TITULO = re.compile(r"^\s{0,3}#{1,4}\s+(?P<t>.+?)\s*#*\s*$")
_ITEM = re.compile(r"^\s*(?:(?P<n>\d+)[.)]|[-*•])\s+(?P<corpo>.+)$")
_REC = re.compile(r"(?i)\b(?:recomendo|recomenda[cç][aã]o|sugiro)\s*:\s*")
_ALT = re.compile(r"(?i)\balternativas?\s*:\s*")
_NENHUMA = re.compile(r"(?i)^\W*(nenhum[a]?|n[aã]o h[aá]|sem|n/?a|nada)\b")


def _norm(s: str) -> str:
    sem = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return re.sub(r"[^a-z ]+", "", sem.casefold()).strip()


@dataclass
class Decisao:
    numero: int
    pergunta: str
    recomendacao: str = ""
    alternativas: list[str] = field(default_factory=list)

    def como_dict(self) -> dict[str, object]:
        return {"numero": self.numero, "pergunta": self.pergunta, "recomendacao": self.recomendacao,
                "alternativas": self.alternativas}


@dataclass
class Briefing:
    secoes: dict[str, str] = field(default_factory=dict)
    decisoes: list[Decisao] = field(default_factory=list)
    estruturado: bool = False  # False = o modelo nao seguiu o formato; texto integral em 'resposta'

    @property
    def precisa_do_usuario(self) -> bool:
        return bool(self.decisoes)


def _decisoes(texto: str) -> list[Decisao]:
    itens: list[tuple[int, str]] = []
    for linha in texto.splitlines():
        m = _ITEM.match(linha)
        if m:
            itens.append((int(m.group("n")) if m.group("n") else len(itens) + 1, m.group("corpo").strip()))
        elif itens and linha.strip():  # continuacao de linha do item anterior
            n, corpo = itens[-1]
            itens[-1] = (n, f"{corpo} {linha.strip()}")
    if not itens and texto.strip() and not _NENHUMA.match(texto.strip()):
        itens = [(1, " ".join(texto.split()))]
    decisoes = []
    for numero, corpo in itens:
        if _NENHUMA.match(corpo):
            continue
        rec = _REC.search(corpo)
        pergunta = corpo[: rec.start()].rstrip(" -—–:;.") if rec else corpo
        recomendacao, alternativas = "", []
        if rec:
            resto = corpo[rec.end():]
            alt = _ALT.search(resto)
            recomendacao = (resto[: alt.start()] if alt else resto).strip(" .;")
            if alt:
                alternativas = [a.strip(" .") for a in re.split(r";|\bou\b", resto[alt.end():]) if a.strip(" .")]
        decisoes.append(Decisao(numero, pergunta.strip() or corpo, recomendacao, alternativas))
    return decisoes


def parse(texto: str) -> Briefing:
    """Divide em secoes por titulos Markdown. Sem nenhum titulo reconhecido => nao estruturado (tudo em 'resposta')."""
    atual: str | None = None
    blocos: dict[str, list[str]] = {}
    em_codigo = False
    for linha in texto.splitlines():
        if linha.lstrip().startswith("```"):
            em_codigo = not em_codigo
        m = None if em_codigo else _TITULO.match(linha)
        if m:
            chave = _ALIASES.get(_norm(m.group("t")))
            if chave:
                atual = chave
                blocos.setdefault(chave, [])
                continue
        if atual is not None:
            blocos[atual].append(linha)
    secoes = {k: "\n".join(v).strip() for k, v in blocos.items() if "\n".join(v).strip()}
    if not secoes:
        return Briefing({"resposta": texto.strip()} if texto.strip() else {}, [], estruturado=False)
    decisoes = _decisoes(secoes["decisoes"]) if "decisoes" in secoes else []
    if "decisoes" in secoes and not decisoes:
        del secoes["decisoes"]  # "Nenhuma decisao necessaria" nao vira pergunta
    return Briefing(secoes, decisoes, estruturado=True)


def resumo_para_retomada(b: Briefing, limite: int = 420) -> str:
    """O MINIMO que o agente precisa lembrar ao retomar (nao reenvia a resposta anterior inteira)."""
    base = b.secoes.get("entendimento") or b.secoes.get("resposta", "")
    base = " ".join(base.split())
    return base if len(base) <= limite else base[: limite - 1].rstrip() + "…"
