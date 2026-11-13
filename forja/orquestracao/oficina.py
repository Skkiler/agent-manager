"""Oficina (pixel art): PROJECAO de leitura do estado real das execucoes. Nada aqui decide ou executa.

Para cada execucao ativa (ou esperando voce): o papel do agente (planejador, executor, testador, revisor, estudante),
a acao atual (lendo, digitando, comando, web, pensando, aguardando), o orcamento consumido e uma descricao em texto
(acessibilidade). O replay devolve a mesma projecao quadro a quadro, a partir dos eventos gravados da execucao.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from forja.adapters.sqlite import tabelas as T
from forja.adapters.sqlite.repositorio import RepositorioSqlite
from forja.dominio.erros import NaoEncontrado
from forja.dominio.tempo import Relogio, RelogioSistema, iso

PAPEIS = {"planejador": "Planejador", "executor": "Executor", "testador": "Testador", "revisor": "Revisor", "estudante": "Estudante",
          "simulado": "Agente simulado"}
ACOES = {"lendo": "lendo arquivos", "digitando": "editando arquivos", "comando": "rodando um comando", "web": "pesquisando na web",
         "pensando": "pensando", "aguardando": "aguardando você", "concluido": "terminou", "parado": "parado"}
_KIND = {"read": "lendo", "search": "lendo", "edit": "digitando", "delete": "digitando", "move": "digitando", "execute": "comando",
         "fetch": "web", "think": "pensando"}
MAX_AGENTES = 16
MAX_QUADROS = 600


def _segundos(a: str, b: str) -> float:
    try:
        return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds()
    except (TypeError, ValueError):
        return 0.0


class Projecao:
    """Estado incremental de UMA execucao, alimentado evento a evento (o mesmo codigo serve a oficina e ao replay)."""

    def __init__(self, modo: str = "", mock: bool = False) -> None:
        self.papel = "estudante" if modo == "estudo" else "simulado" if mock else "executor"
        self.acao = "pensando"
        self.ferramentas = 0
        self.ultimo = ""
        self.planejando = False
        self.aguardando = False
        self.nivel = ""  # simples | normal | complexa (cor do personagem)

    def aplicar(self, tipo: str, p: dict[str, Any]) -> str:
        """Atualiza com um evento; devolve a frase curta do que aconteceu ('' = sem mudanca visivel)."""
        frase = ""
        if tipo == "kiro.rota":
            self.nivel = str(p.get("nivel") or "")
            if p.get("parte") == "revisao":
                self.papel = "revisor"
            if p.get("planejar"):
                self.papel, self.planejando = "planejador", True
                frase = "classificou a tarefa como complexa: vai planejar antes de executar"
            else:
                frase = f"tarefa de nivel {p.get('nivel', '?')}"
        elif tipo == "kiro.configuracao":
            parte = p.get("parte")
            if parte == "planejamento":
                self.papel = "planejador"
            elif self.papel == "planejador" and parte not in (None, "planejamento"):
                self.papel = "executor"
            modelo = (p.get("aplicados") or {}).get("modelo")
            frase = f"modelo {modelo}" if modelo else ""
        elif tipo == "kiro.plano":
            self.planejando = False
            if self.papel == "planejador":
                self.papel = "executor"
            frase = "plano pronto" + (f" com {p.get('subtarefas')} subtarefas" if p.get("subtarefas") else "")
        elif tipo == "kiro.ferramenta":
            if p.get("status") not in ("completed", "failed"):
                self.ferramentas += 1
            self.acao = _KIND.get(str(p.get("tipo") or ""), "pensando")
            self.aguardando = False
            frase = str(p.get("titulo") or "")[:80]
        elif tipo in ("kiro.testes_forja", "kiro.correcao"):
            self.papel, self.acao = "testador", "comando"
            if tipo == "kiro.testes_forja":
                frase = f"testes da Forja {'passaram' if p.get('ok') else 'falharam'}"
        elif tipo == "aprovacao.solicitada":
            self.acao, self.aguardando = "aguardando", True
            frase = "pediu sua aprovacao"
        elif tipo in ("aprovacao.aprovada", "aprovacao.negada", "aprovacao.expirada", "execucao.retomada"):
            self.aguardando = False
            self.acao = "pensando"
            frase = "aprovacao respondida"
        elif tipo in ("execucao.concluida",):
            self.acao, self.aguardando = "concluido", False
            frase = "concluiu a tarefa"
        elif tipo in ("execucao.falhou", "execucao.cancelada", "execucao.expirada"):
            self.acao, self.aguardando = "parado", False
            frase = tipo.split(".", 1)[1]
        elif tipo in ("execucao.bloqueada", "execucao.pausada"):
            self.acao, self.aguardando = "aguardando", True
            frase = "precisa de você"
        elif tipo == "kiro.orcamento":
            frase = "a Forja interrompeu: orcamento ou laco"
        if frase:
            self.ultimo = frase
        return frase

    def descricao(self, titulo: str) -> str:
        return f"{PAPEIS.get(self.papel, self.papel)} da tarefa '{titulo[:60]}': {ACOES.get(self.acao, self.acao)}" + (
            f" ({self.ultimo})" if self.ultimo and self.acao != "aguardando" else "")


class OficinaServico:
    def __init__(self, repo: RepositorioSqlite, max_ferramentas: Any = None, relogio: Relogio | None = None) -> None:
        self.repo = repo
        self.max_ferramentas = max_ferramentas  # () -> int | None (orcamento rigido do provedor real)
        self.relogio = relogio or RelogioSistema()

    def _limite(self) -> int | None:
        try:
            return int(self.max_ferramentas()) if callable(self.max_ferramentas) else None
        except Exception:  # noqa: BLE001
            return None

    def cena(self, projeto_id: str | None = None) -> dict[str, Any]:
        agora = iso(self.relogio.agora())
        limite = self._limite()
        agentes = []
        with self.repo.leitura() as t:
            execs = []
            for estado in ("executando", "aguardando_aprovacao", "pausada"):
                execs += t.listar(T.Execucao, estado=estado, limite=50)
            execs.sort(key=lambda e: e["criado_em"], reverse=True)
            for ex in execs:
                tarefa = t.obter(T.Tarefa, ex["tarefa_id"])
                if tarefa is None or (projeto_id and tarefa["projeto_id"] != projeto_id):
                    continue
                if ex["estado"] == "pausada" and tarefa["estado"] != "bloqueada":
                    continue
                proj = Projecao(tarefa.get("modo") or "", ex["agente_id"].startswith("mock"))
                for ev in t.eventos_da_execucao(ex["id"], 3000):
                    proj.aplicar(ev["tipo"], ev["payload"] or {})
                pendentes = len(t.listar(T.Aprovacao, execucao_id=ex["id"], estado="pendente"))
                if pendentes or tarefa["estado"] in ("bloqueada", "aguardando_aprovacao"):
                    proj.acao, proj.aguardando = "aguardando", True
                orc = tarefa.get("orcamento") or {}
                chamadas = int(((ex.get("resultado") or {}).get("chamadas_acumuladas")) or 0)
                tempo_max = int(orc.get("max_duracao_segundos") or 0)
                decorrido = _segundos(ex["iniciado_em"], agora) if ex.get("iniciado_em") else 0.0
                fracoes = [x for x in (proj.ferramentas / limite if limite else None,
                                       chamadas / orc["max_chamadas_modelo"] if orc.get("max_chamadas_modelo") else None,
                                       decorrido / tempo_max if tempo_max and ex["estado"] == "executando" else None) if x is not None]
                fracao = round(min(1.0, max(fracoes) if fracoes else 0.0), 3)
                agentes.append({
                    "execucao_id": ex["id"], "tarefa_id": tarefa["id"], "titulo": tarefa["titulo"], "projeto_id": tarefa["projeto_id"],
                    "estado": tarefa["estado"], "nivel": proj.nivel, "papel": proj.papel, "papel_rotulo": PAPEIS.get(proj.papel, proj.papel), "acao": proj.acao,
                    "acao_rotulo": ACOES.get(proj.acao, proj.acao), "aguardando": proj.aguardando, "aprovacoes_pendentes": pendentes,
                    "ferramentas": proj.ferramentas, "max_ferramentas": limite, "chamadas_modelo": chamadas,
                    "max_chamadas_modelo": orc.get("max_chamadas_modelo"), "segundos": int(decorrido), "max_segundos": tempo_max or None,
                    "orcamento": fracao, "ultimo": proj.ultimo, "descricao": proj.descricao(tarefa["titulo"]),
                })
                if len(agentes) >= MAX_AGENTES:
                    break
        esperando = sum(a["aguardando"] for a in agentes)
        resumo = (f"{len(agentes)} agente(s) na oficina" + (f", {esperando} aguardando você" if esperando else "") + ". "
                  + " ".join(a["descricao"] + "." for a in agentes)) if agentes else "Oficina vazia: nenhuma execução ativa."
        return {"gerado_em": agora, "agentes": agentes, "aguardando": esperando, "resumo": resumo}

    def replay(self, execucao_id: str) -> dict[str, Any]:
        with self.repo.leitura() as t:
            ex = t.obter(T.Execucao, execucao_id)
            if ex is None:
                raise NaoEncontrado(f"Execucao {execucao_id} nao encontrada.")
            tarefa = t.obter(T.Tarefa, ex["tarefa_id"]) or {}
            eventos = t.eventos_da_execucao(execucao_id, 5000)
        proj = Projecao(tarefa.get("modo") or "", ex["agente_id"].startswith("mock"))
        quadros = []
        inicio = eventos[0]["ts"] if eventos else ""
        for ev in eventos:
            frase = proj.aplicar(ev["tipo"], ev["payload"] or {})
            if not frase and ev["tipo"] not in ("execucao.iniciada", "agente.iniciado"):
                continue
            quadros.append({"seq": ev["seq"], "t": round(_segundos(inicio, ev["ts"]), 2), "tipo": ev["tipo"], "papel": proj.papel,
                            "acao": proj.acao, "ferramentas": proj.ferramentas, "texto": frase or "começou",
                            "descricao": proj.descricao(tarefa.get("titulo", ""))})
            if len(quadros) >= MAX_QUADROS:
                break
        return {"execucao_id": execucao_id, "tarefa_id": ex["tarefa_id"], "titulo": tarefa.get("titulo", ""), "estado": ex["estado"],
                "duracao": quadros[-1]["t"] if quadros else 0, "quadros": quadros}
