"""Acoes externas: ESCRITA em servicos (comentar no Jira/GitHub, mudar status, criar cartao) com aprovacao por acao.

Fluxo (todas as etapas testadas):
  1. alguem (agente via ferramenta/MCP, ou o operador) PROPOE: a integracao precisa estar pronta e com escrita ligada; os
     parametros sao validados sem rede e o conteudo que sairia da maquina e recusado se parecer credencial;
  2. a proposta vira UMA pergunta em linguagem natural ("Posso comentar na issue ABC-1 do Jira: «...»?") e um aviso no quadro;
  3. o operador aprova ou nega, com adendo livre (registrado); so a aprovacao executa, UMA vez (transicao atomica por versao);
  4. o resultado (resumo curto) e o desfecho ficam auditados. Propostas nao decididas expiram.
Nada aqui contorna a politica de rede: a execucao passa pelo mesmo cliente seguro, limite por minuto e allowlist da integracao.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from forja.adapters.sqlite import tabelas as T
from forja.adapters.sqlite.repositorio import RepositorioSqlite, novo_id
from forja.dominio.erros import Conflito, ConflitoVersao, ErroDominio, NaoEncontrado, ValidacaoDominio
from forja.dominio.quadro import MensagemIn, TipoMensagem
from forja.dominio.tempo import Relogio, RelogioSistema, iso
from forja.observabilidade.sanitizar import sanitizar_texto

log = logging.getLogger("forja.acoes_externas")
VALIDADE = timedelta(hours=24)
ESTADOS = ("pendente", "negada", "executando", "executada", "falhou", "expirada")
MAX_PENDENTES = 50


class AcoesExternasServico:
    def __init__(self, repo: RepositorioSqlite, integracoes: Any, quadro: Any | None = None, relogio: Relogio | None = None) -> None:
        self.repo, self.integracoes, self.quadro = repo, integracoes, quadro
        self.relogio = relogio or RelogioSistema()

    def _agora(self) -> str:
        return iso(self.relogio.agora())

    # ------------------------------------------------------------------ propor
    def propor(self, integracao: str, acao: str, params: dict[str, Any], solicitado_por: str = "operador",
               tarefa_id: str | None = None, dedup_key: str | None = None) -> tuple[dict[str, Any], bool]:
        """Devolve (acao, criada). Repetir a mesma proposta (mesmo solicitante + dedup_key) devolve a original."""
        if not isinstance(params, dict):
            raise ValidacaoDominio("parametros devem ser um objeto")
        self.expirar()
        if dedup_key:
            with self.repo.leitura() as t:
                achadas = t.listar(T.AcaoExterna, solicitado_por=solicitado_por, dedup_key=dedup_key, limite=1)
            if achadas:
                return achadas[0], False
        normalizados, descricao, risco = self.integracoes.preparar_escrita(integracao, acao, params)
        agora = self._agora()
        with self.repo.escrita() as t:
            if len(t.listar(T.AcaoExterna, estado="pendente", limite=MAX_PENDENTES + 1)) >= MAX_PENDENTES:
                raise Conflito(f"ha {MAX_PENDENTES} acoes externas aguardando decisao; decida algumas antes de propor novas")
            linha = t.inserir(T.AcaoExterna, id=novo_id("ACX"), versao=1, integracao=integracao, acao=acao, parametros=normalizados,
                              descricao=descricao[:400], risco=risco, estado="pendente", solicitado_por=solicitado_por[:100],
                              tarefa_id=tarefa_id, dedup_key=dedup_key, adendo="", resultado="", criado_em=agora)
            t.emitir_evento("acao_externa.proposta", agora, {"id": linha["id"], "integracao": integracao, "acao": acao, "risco": risco})
        self._avisar(linha)
        return linha, True

    def _avisar(self, linha: dict[str, Any]) -> None:
        if self.quadro is None:
            return
        try:
            self.quadro.publicar(MensagemIn(
                origem="sistema", destino="operador", tipo=TipoMensagem.APONTAMENTO, prioridade=1 if linha["risco"] == "alto" else 2,
                assunto=f"Aprovar acao externa: {linha['descricao']}"[:120], payload={"acao_externa": linha["id"], "risco": linha["risco"]},
                tarefa_id=None, dedup_key=f"acx:{linha['id']}"), ator="sistema")
        except Exception:  # noqa: BLE001 - o aviso e informativo; a acao continua pendente e listada
            log.exception("falha ao avisar o quadro sobre acao externa")

    # ------------------------------------------------------------------ consultar
    def listar(self, estado: str | None = None, limite: int = 50) -> list[dict[str, Any]]:
        if estado is not None and estado not in ESTADOS:
            raise ValidacaoDominio(f"estado deve ser um de {', '.join(ESTADOS)}")
        self.expirar()
        with self.repo.leitura() as t:
            linhas = t.listar(T.AcaoExterna, **({"estado": estado} if estado else {}), limite=500)
        return sorted(linhas, key=lambda x: x["criado_em"], reverse=True)[:limite]

    def obter(self, id_: str) -> dict[str, Any]:
        with self.repo.leitura() as t:
            linha = t.obter(T.AcaoExterna, id_)
        if linha is None:
            raise NaoEncontrado(f"acao externa {id_} nao encontrada")
        return linha

    def expirar(self) -> int:
        limite = iso(self.relogio.agora() - VALIDADE)
        n = 0
        with self.repo.escrita() as t:
            for a in t.listar(T.AcaoExterna, estado="pendente", limite=500):
                if a["criado_em"] < limite:
                    t.atualizar(T.AcaoExterna, a["id"], estado="expirada", versao=a["versao"] + 1, decidido_em=self._agora(), decidido_por="sistema:validade")
                    t.emitir_evento("acao_externa.expirada", self._agora(), {"id": a["id"]})
                    n += 1
        return n

    # ------------------------------------------------------------------ decidir e executar
    def decidir(self, id_: str, aprovar: bool, expected_version: int, ator: str = "operador", adendo: str = "") -> dict[str, Any]:
        self.expirar()
        adendo = sanitizar_texto(adendo or "")[:1000]
        agora = self._agora()
        with self.repo.escrita() as t:
            a = t.obter(T.AcaoExterna, id_)
            if a is None:
                raise NaoEncontrado(f"acao externa {id_} nao encontrada")
            if a["versao"] != expected_version:
                raise ConflitoVersao(f"A acao mudou (versao {a['versao']}); recarregue antes de decidir.")
            if a["estado"] != "pendente":
                raise Conflito(f"a acao esta '{a['estado']}' e nao pode mais ser decidida")
            novo = "executando" if aprovar else "negada"
            t.atualizar(T.AcaoExterna, id_, estado=novo, versao=a["versao"] + 1, decidido_por=ator[:100], decidido_em=agora, adendo=adendo)
            t.emitir_evento("acao_externa.decidida", agora, {"id": id_, "aprovada": aprovar})
        if not aprovar:
            return self.obter(id_)
        return self._executar(id_)

    def _executar(self, id_: str) -> dict[str, Any]:
        a = self.obter(id_)
        try:
            resultado, estado = self.integracoes.executar_escrita(a["integracao"], a["acao"], a["parametros"]), "executada"
        except ErroDominio as e:
            resultado, estado = f"nao executada: {e.mensagem}", "falhou"
        except Exception:  # noqa: BLE001 - detalhe so no log (pode conter dados do servico)
            log.exception("falha inesperada ao executar acao externa", extra={"acao_externa": id_})
            resultado, estado = "nao executada: falha inesperada (ver log)", "falhou"
        agora = self._agora()
        with self.repo.escrita() as t:
            atual = t.obter(T.AcaoExterna, id_)
            t.atualizar(T.AcaoExterna, id_, estado=estado, versao=atual["versao"] + 1, resultado=sanitizar_texto(str(resultado))[:500], executado_em=agora)
            t.emitir_evento(f"acao_externa.{estado}", agora, {"id": id_})
        return self.obter(id_)

    def recuperar(self) -> int:
        """Na subida do servidor: execucao interrompida no meio NAO e repetida as cegas (pode ter chegado ao servico)."""
        n = 0
        with self.repo.escrita() as t:
            for a in t.listar(T.AcaoExterna, estado="executando", limite=500):
                t.atualizar(T.AcaoExterna, a["id"], estado="falhou", versao=a["versao"] + 1,
                            resultado="interrompida pelo reinicio do servidor; confira no servico antes de propor de novo")
                n += 1
        return n
