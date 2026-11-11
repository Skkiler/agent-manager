"""Busca SEMANTICA opcional (embeddings locais), por nivel: inativo (padrao) | fallback | ativo.

Por que inativo por padrao: para codigo, o mercado (Claude Code, estudos de 2026) prefere busca lexical/agentica; na medicao
da Forja (ADR-017) o hibrido so ajudou como reforco, e o custo dominante e indexar (modelo ~220 MB, minutos de CPU).
- fallback: so entra quando a busca lexical esta INSEGURA (menos de 2 resultados ou margem 1o-2o < 30% do 1o), o melhor
  gatilho medido (recall@5 0,222 vs 0,163 da lexical);
- ativo: sempre funde (RRF) o ranking semantico com o lexical.
Regras: dependencia OPCIONAL (fastembed); checa hardware (>= 8 GB de RAM) e mede a velocidade antes de usar; o modelo e
baixado uma unica vez na 1a ativacao (rede: aceito ao escolher o nivel); a ACL e aplicada ANTES da pontuacao; textos vem
do indice ja redigido (nada novo sai do computador). Indexacao incremental por hash, em segundo plano.
"""

from __future__ import annotations

import ctypes
import hashlib
import importlib.util
import logging
import os
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

from sqlalchemy import text

from forja.adapters.sqlite.repositorio import RepositorioSqlite, Tx

log = logging.getLogger("forja.memoria.semantica")
MODOS = ("inativo", "fallback", "ativo")
MODELO_PADRAO = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MARGEM_FALLBACK = 0.30
RAM_MINIMA_GB = 8.0
LOTE = 64
MAX_TEXTO = 2000


class Embedder(Protocol):
    modelo: str

    def vetores(self, textos: list[str]) -> list[list[float]]: ...


class EmbedderFastembed:
    def __init__(self, modelo: str = MODELO_PADRAO) -> None:
        from fastembed import TextEmbedding  # dependencia OPCIONAL

        self.modelo = modelo
        self._m = TextEmbedding(model_name=modelo)

    def vetores(self, textos: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in self._m.embed(textos, batch_size=LOTE)]


def ram_total_gb() -> float | None:
    try:
        if os.name == "nt":
            class _Mem(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = _Mem()
            m.dwLength = ctypes.sizeof(_Mem)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):  # type: ignore[attr-defined]
                return m.ullTotalPhys / 1024**3
            return None
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3
    except (OSError, ValueError, AttributeError):
        return None


def disponibilidade() -> tuple[bool, str]:
    if not (importlib.util.find_spec("fastembed") and importlib.util.find_spec("numpy")):
        return False, "dependencia opcional ausente: pip install fastembed"
    ram = ram_total_gb()
    if ram is not None and ram < RAM_MINIMA_GB:
        return False, f"memoria insuficiente ({ram:.1f} GB; minimo {RAM_MINIMA_GB:.0f} GB)"
    return True, ""


def _sha(*partes: str) -> str:
    return hashlib.sha256("\x1f".join(partes).encode("utf-8", "replace")).hexdigest()


def _no_escopo(ns: str, alvo: list[str]) -> bool:
    """Mesma regra do filtro SQL (memoria_fts._filtro_ns): igual ou subnamespace (prefixo + '/')."""
    return any(ns == a or ns.startswith(a + "/") for a in alvo)


def margem_insegura(pontuacoes: list[float]) -> bool:
    """Gatilho do modo fallback: nenhum resultado, ou o 1o nao se destaca do 2o. Um unico acerto = margem total (confiante)."""
    if not pontuacoes or pontuacoes[0] <= 0:
        return True
    if len(pontuacoes) == 1:
        return False
    return (pontuacoes[0] - pontuacoes[1]) / pontuacoes[0] < MARGEM_FALLBACK


class IndiceSemantico:
    def __init__(self, repo: RepositorioSqlite, fabrica: Callable[[], Embedder] | None = None,
                 checar: Callable[[], tuple[bool, str]] | None = None) -> None:
        self.repo = repo
        self.modo = "inativo"
        self._fabrica = fabrica or EmbedderFastembed
        self._checar = checar or disponibilidade
        self._emb: Embedder | None = None
        self._mu = threading.RLock()
        self._thread: threading.Thread | None = None
        self._sujo = threading.Event()
        self._matriz: tuple[str, Any, list[tuple[str, str, str]]] | None = None  # (modelo, np.ndarray, [(origem, ref, ns)])
        self.motivo = ""
        self.ms_por_bloco: float | None = None
        self.ultimo_erro = ""

    # ------------------------------------------------------------------ estado
    def definir_modo(self, modo: str) -> None:
        self.modo = modo if modo in MODOS else "inativo"
        if self.modo != "inativo":
            self.agendar()

    def disponivel(self) -> bool:
        ok, self.motivo = self._checar()
        return ok

    def estado(self) -> dict[str, Any]:
        ok = self.disponivel()
        with self.repo.leitura() as t:
            n = int(t.s.execute(text("SELECT count(*) FROM vetor_semantico")).scalar() or 0)
            total = int(t.s.execute(text("SELECT count(*) FROM codigo_trecho")).scalar() or 0) + int(
                t.s.execute(text("SELECT count(*) FROM memoria")).scalar() or 0)
        return {"modo": self.modo, "disponivel": ok, "motivo": self.motivo, "vetores": n, "documentos": total,
                "ms_por_bloco": self.ms_por_bloco, "indexando": bool(self._thread and self._thread.is_alive()),
                "ultimo_erro": self.ultimo_erro, "modelo": getattr(self._emb, "modelo", MODELO_PADRAO)}

    def _embedder(self) -> Embedder:
        with self._mu:
            if self._emb is None:
                emb = self._fabrica()
                t0 = time.perf_counter()  # benchmark curto ANTES de indexar tudo (orientacao: medir antes de ativar o pesado)
                emb.vetores(["benchmark de velocidade da forja"] * 8)
                self.ms_por_bloco = round((time.perf_counter() - t0) * 1000 / 8, 2)
                self._emb = emb
            return self._emb

    # ------------------------------------------------------------------ indexacao incremental
    def _pendentes(self, t: Tx, modelo: str, limite: int) -> list[tuple[str, str, str, str, str, str]]:
        """(chave, origem, ref, namespace, sha, texto) dos documentos sem vetor ou com vetor desatualizado."""
        existentes = dict(t.s.execute(text("SELECT chave, sha FROM vetor_semantico WHERE modelo = :m"), {"m": modelo}).all())
        saida = []
        for rid, arq, ns, txt in t.s.execute(text(
                "SELECT c.id, c.arquivo_id, a.namespace, f.texto FROM codigo_trecho c JOIN arquivo_indexado a ON a.id = c.arquivo_id "
                "JOIN codigo_fts f ON f.rowid = c.id WHERE a.estado = 'ativo'")):
            chave, sha = f"c:{rid}", _sha(txt or "")
            if existentes.get(chave) != sha:
                saida.append((chave, "codigo", f"{arq}|{rid}", ns, sha, (txt or "")[:MAX_TEXTO]))
            if len(saida) >= limite:
                return saida
        for mid, ns, tit, res, cont in t.s.execute(text("SELECT id, namespace, titulo, resumo, conteudo FROM memoria")):
            corpo = f"{tit}\n{res}\n{cont or ''}"[:MAX_TEXTO]
            chave, sha = f"m:{mid}", _sha(corpo)
            if existentes.get(chave) != sha:
                saida.append((chave, "memoria", mid, ns, sha, corpo))
            if len(saida) >= limite:
                break
        return saida

    def _remover_orfaos(self, t: Tx) -> int:
        r1 = t.s.execute(text("DELETE FROM vetor_semantico WHERE origem = 'codigo' AND CAST(substr(chave, 3) AS INTEGER) NOT IN "
                              "(SELECT id FROM codigo_trecho)")).rowcount
        r2 = t.s.execute(text("DELETE FROM vetor_semantico WHERE origem = 'memoria' AND ref NOT IN (SELECT id FROM memoria)")).rowcount
        return (r1 or 0) + (r2 or 0)

    def sincronizar(self, limite: int = 100_000, prazo_s: float = 600.0) -> int:
        """Gera vetores so do que falta ou mudou. Retorna quantos foram gravados."""
        if self.modo == "inativo" or not self.disponivel():
            return 0
        import numpy as np

        emb = self._embedder()
        fim = time.monotonic() + prazo_s
        feitos = 0
        with self.repo.escrita() as t:
            self._remover_orfaos(t)
        while time.monotonic() < fim and feitos < limite:
            with self.repo.leitura() as t:
                lote = self._pendentes(t, emb.modelo, LOTE)
            if not lote:
                break
            vets = np.asarray(emb.vetores([x[5] for x in lote]), dtype=np.float32)
            vets /= np.maximum(np.linalg.norm(vets, axis=1, keepdims=True), 1e-9)
            with self.repo.escrita() as t:
                t.s.execute(text("INSERT OR REPLACE INTO vetor_semantico(chave, origem, ref, namespace, sha, modelo, dim, vetor) "
                                 "VALUES (:c, :o, :r, :n, :s, :m, :d, :v)"),
                            [{"c": c, "o": o, "r": r, "n": n, "s": s, "m": emb.modelo, "d": int(v.shape[0]), "v": v.tobytes()}
                             for (c, o, r, n, s, _x), v in zip(lote, vets, strict=True)])
            feitos += len(lote)
        with self._mu:
            self._matriz = None
        return feitos

    def agendar(self) -> None:
        """Indexa em segundo plano (uma thread por vez). Chamar de novo durante a indexacao so marca 'sujo'."""
        if self.modo == "inativo":
            return
        with self._mu:
            if self._thread and self._thread.is_alive():
                self._sujo.set()
                return

            def trabalhar() -> None:
                while True:
                    self._sujo.clear()
                    try:
                        self.sincronizar()
                        self.ultimo_erro = ""
                    except Exception as e:  # noqa: BLE001 - indexacao em segundo plano nunca derruba o servidor
                        self.ultimo_erro = type(e).__name__
                        log.warning("indexacao semantica falhou: %s", type(e).__name__)
                        return
                    if not self._sujo.is_set():
                        return

            self._thread = threading.Thread(target=trabalhar, name="forja-semantica", daemon=True)
            self._thread.start()

    # ------------------------------------------------------------------ consulta
    def _carregar(self, modelo: str) -> tuple[Any, list[tuple[str, str, str]]]:
        import numpy as np

        with self._mu:
            if self._matriz and self._matriz[0] == modelo:
                return self._matriz[1], self._matriz[2]
            with self.repo.leitura() as t:
                linhas = t.s.execute(text("SELECT origem, ref, namespace, dim, vetor FROM vetor_semantico WHERE modelo = :m"),
                                     {"m": modelo}).all()
            if not linhas:
                return None, []
            matriz = np.vstack([np.frombuffer(v, dtype=np.float32, count=d) for _o, _r, _n, d, v in linhas])
            meta = [(o, r, n) for o, r, n, _d, _v in linhas]
            self._matriz = (modelo, matriz, meta)
            return matriz, meta

    def buscar(self, consulta: str, namespaces: list[str], limite: int = 50) -> tuple[list[dict], list[dict]]:
        """(hits de memoria, hits de codigo) no formato dos hidratadores. ACL filtrada ANTES de pontuar."""
        if self.modo == "inativo" or not self.disponivel():
            return [], []
        import numpy as np

        emb = self._embedder()
        matriz, meta = self._carregar(emb.modelo)
        if matriz is None:
            return [], []
        idx = np.array([i for i, (_o, _r, ns) in enumerate(meta) if _no_escopo(ns, namespaces)], dtype=np.int64)
        if idx.size == 0:
            return [], []
        q = np.asarray(emb.vetores([consulta])[0], dtype=np.float32)
        q /= max(float(np.linalg.norm(q)), 1e-9)
        notas = matriz[idx] @ q
        ordem = idx[np.argsort(-notas)[: limite * 3]]
        mem, cod = [], []
        with self.repo.leitura() as t:
            for i in ordem:
                origem, ref, _ns = meta[int(i)]
                if origem == "memoria" and len(mem) < limite:
                    m = t.s.execute(text("SELECT resumo FROM memoria WHERE id = :i"), {"i": ref}).first()
                    if m:
                        mem.append({"memoria_id": ref, "trecho": (m[0] or "")[:300]})
                elif origem == "codigo" and len(cod) < limite:
                    arq, rid = ref.split("|", 1)
                    r = t.s.execute(text("SELECT c.linha_ini, c.linha_fim, f.texto FROM codigo_trecho c JOIN codigo_fts f ON f.rowid = c.id "
                                         "WHERE c.id = :r"), {"r": int(rid)}).first()
                    if r:
                        cod.append({"arquivo_id": arq, "linha_ini": r[0], "linha_fim": r[1], "trecho": "\n".join((r[2] or "").splitlines()[:12])})
        return mem, cod
