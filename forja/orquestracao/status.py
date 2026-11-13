"""Relatos de status legiveis, com custo minimo.

Duas camadas:
1. SEM LLM, em tempo real: frases montadas a partir dos eventos ('lendo auth.py', 'testes da Forja falharam'). Mesmo codigo da
   oficina (Projecao). `GET /execucoes/{id}/status`.
2. COM modelo barato (parte 'status' = haiku, esforco baixo), SO em marcos (tarefa terminou ou parou), EM LOTE: varias tarefas
   numa chamada, fora do caminho critico, com teto por hora. Cada chamada ao Kiro carrega o system prompt dele, entao agrupar
   e o que faz valer a pena. Sem Kiro (ou falha), cai na frase deterministica (rotulada).
O relato vai para a conversa da tarefa e, se a tarefa veio de um master/sub-master, para a conversa dele.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable
from typing import Any

from forja.adapters.sqlite import tabelas as T
from forja.adapters.sqlite.repositorio import RepositorioSqlite, novo_id
from forja.dominio.tempo import Relogio, RelogioSistema, iso
from forja.observabilidade.sanitizar import sanitizar_texto
from forja.orquestracao.oficina import Projecao
from forja.seguranca import spotlight

log = logging.getLogger("forja.status")
MODOS = ("desligado", "deterministico", "marcos")
MAX_POR_LOTE, MAX_POR_HORA, ESPERA_LOTE_S = 6, 20, 45.0
_TITULO = re.compile(r"^#{2,4}\s*(T-[A-Za-z0-9]+)\s*$", re.MULTILINE)
ROTULO_ESTADO = {"concluida": "concluída", "bloqueada": "precisa de você", "falhou": "falhou", "cancelada": "cancelada", "expirada": "expirou"}


def linha_do_tempo(repo: RepositorioSqlite, execucao_id: str, limite: int = 15) -> dict[str, Any]:
    with repo.leitura() as t:
        ex = t.obter(T.Execucao, execucao_id)
        if ex is None:
            return {}
        tarefa = t.obter(T.Tarefa, ex["tarefa_id"]) or {}
        eventos = t.eventos_da_execucao(execucao_id, 3000)
    p = Projecao(tarefa.get("modo") or "", ex["agente_id"].startswith("mock"))
    frases = []
    for e in eventos:
        f = p.aplicar(e["tipo"], e["payload"] or {})
        if f and (not frases or frases[-1]["texto"] != f):
            frases.append({"ts": e["ts"], "texto": f})
    return {"execucao_id": execucao_id, "tarefa_id": ex["tarefa_id"], "titulo": tarefa.get("titulo", ""), "estado": ex["estado"],
            "agora": p.descricao(tarefa.get("titulo", "")), "linha": frases[-limite:]}


def frase_deterministica(tarefa: dict[str, Any], ex: dict[str, Any]) -> str:
    res = ex.get("resultado") or {}
    estado = ROTULO_ESTADO.get(tarefa["estado"], tarefa["estado"])
    pend = [p for p in res.get("pendencias") or [] if not p.startswith("Revise")][:2]
    return (f"{tarefa['titulo'][:80]}: {estado}. {sanitizar_texto(res.get('resumo') or '')[:200]}"
            + (f" Pendências: {'; '.join(pend)[:200]}." if pend else "")).strip()


class StatusServico:
    def __init__(self, repo: RepositorioSqlite, turno: Callable[[str, str], str] | None = None, relogio: Relogio | None = None) -> None:
        self.repo = repo
        self.turno = turno  # (texto, parte) -> resposta; None = so deterministico
        self.relogio = relogio or RelogioSistema()
        self.modo = "marcos"
        self.publicar: list[Callable[[str, str, str], None]] = []  # (tarefa_id, texto, origem) -> conversa do master etc.
        self._fila: list[str] = []
        self._na_conversa: dict[str, bool] = {}
        self._mu = threading.Lock()
        self._chamadas: list[float] = []
        self._timer: threading.Timer | None = None

    def ao_finalizar(self, execucao_id: str, res: Any) -> None:
        if self.modo == "desligado" or res.estado in ("pausada",) or (res.mensagens and res.mensagens[0].tipo == "subtarefas"):
            return
        with self.repo.leitura() as t:
            ex = t.obter(T.Execucao, execucao_id)
            tarefa = t.obter(T.Tarefa, ex["tarefa_id"]) if ex else None
        if tarefa is None or (tarefa.get("entrada") or {}).get("coordenacao"):
            return  # o turno do master ja e um relato
        # Se o agente ja falou na conversa da tarefa, o relato iria duplicar: so vai para quem acompanha (master etc.).
        na_conversa = not res.mensagens
        if not na_conversa and not (self.publicar and (tarefa.get("entrada") or {}).get("coordenacao_id")):
            return
        if self.modo == "deterministico" or res.mock or self.turno is None:
            self._gravar(tarefa["id"], frase_deterministica(tarefa, ex), "deterministico", na_conversa)
            return
        with self._mu:
            self._na_conversa[execucao_id] = na_conversa
            self._fila.append(execucao_id)
            cheia = len(self._fila) >= MAX_POR_LOTE
            if self._timer is None or cheia:
                if self._timer is not None:
                    self._timer.cancel()
                self._timer = threading.Timer(0 if cheia else ESPERA_LOTE_S, self.processar)
                self._timer.daemon = True
                self._timer.start()

    def _pode_chamar(self) -> bool:
        agora = time.monotonic()
        with self._mu:
            self._chamadas = [x for x in self._chamadas if agora - x < 3600]
            if len(self._chamadas) >= MAX_POR_HORA:
                return False
            self._chamadas.append(agora)
            return True

    def processar(self) -> int:
        """Esvazia a fila em lotes: UMA chamada barata por lote. Devolve quantas tarefas foram relatadas."""
        with self._mu:
            fila, self._fila, self._timer = self._fila[:], [], None
        feitos = 0
        for i in range(0, len(fila), MAX_POR_LOTE):
            feitos += self._lote(fila[i:i + MAX_POR_LOTE])
        return feitos

    def _lote(self, ids: list[str]) -> int:
        itens = []
        with self.repo.leitura() as t:
            for eid in dict.fromkeys(ids):
                ex = t.obter(T.Execucao, eid)
                tarefa = t.obter(T.Tarefa, ex["tarefa_id"]) if ex else None
                if tarefa:
                    itens.append((tarefa, ex))
        if not itens:
            return 0
        blocos = []
        for tarefa, ex in itens:
            lt = linha_do_tempo(self.repo, ex["id"], 10)
            fatos = "; ".join(f["texto"] for f in lt.get("linha", []))[:500]
            blocos.append(f"### {tarefa['id']}\n{frase_deterministica(tarefa, ex)}\nEventos: {fatos}")
        textos: dict[str, str] = {}
        if self._pode_chamar():
            pedido = ("Para CADA tarefa abaixo, escreva para o usuario 1 a 3 frases claras em portugues: o que foi feito, o resultado e, "
                      "se houver, o que falta dele. Use SO os fatos dados; nao invente. Responda com '### <id>' seguido das frases.\n"
                      + spotlight.REGRA + "\n" + spotlight.envolver("TAREFAS", "\n".join(blocos)[:5000], spotlight.codigo()))
            try:
                resposta = self.turno(pedido, "status")  # type: ignore[misc]
                partes = _TITULO.split(resposta)
                textos = {partes[i].strip(): " ".join(partes[i + 1].split())[:600] for i in range(1, len(partes) - 1, 2)}
            except Exception as e:  # noqa: BLE001 - relato e conveniencia: cai na frase deterministica
                log.info("resumo de status por modelo indisponivel: %s", type(e).__name__)
        for tarefa, ex in itens:
            texto = textos.get(tarefa["id"])
            with self._mu:
                na_conversa = self._na_conversa.pop(ex["id"], True)
            self._gravar(tarefa["id"], texto or frase_deterministica(tarefa, ex), "modelo" if texto else "deterministico", na_conversa)
        return len(itens)

    def _gravar(self, tarefa_id: str, texto: str, origem: str, na_conversa: bool = True) -> None:
        agora = iso(self.relogio.agora())
        with self.repo.escrita() as t:
            if na_conversa:
                from sqlalchemy import func, select

                ordem = int(t.s.scalar(select(func.coalesce(func.max(T.Mensagem.ordem), 0))
                                       .where(T.Mensagem.tarefa_id == tarefa_id)) or 0) + 1
                t.inserir(T.Mensagem, id=novo_id("MSG"), tarefa_id=tarefa_id, ordem=ordem, execucao_id=None, papel="sistema",
                          tipo="status", conteudo=texto, dados={"origem": origem}, criado_em=agora)
            t.emitir_evento("status.resumo", agora, {"origem": origem}, tarefa_id=tarefa_id)
        for fn in list(self.publicar):
            try:
                fn(tarefa_id, texto, origem)
            except Exception:  # noqa: BLE001
                log.exception("falha ao publicar status")
