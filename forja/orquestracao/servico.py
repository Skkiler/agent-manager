"""Casos de uso do nucleo: tarefas, maquina de estados, execucoes, aprovacoes, locks e recuperacao.

Sem HTTP e sem SQL: persiste pelo repositorio; executa agentes por ProvedorAgente.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import uuid
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from forja.adapters.sqlite import tabelas as T
from forja.adapters.sqlite.repositorio import RepositorioSqlite, Tx, novo_id
from forja.agentes.base import ControleExecucao, ProvedorAgente
from forja.dominio.contratos import (
    ObjetivoIn,
    ProjetoIn,
    ResultadoAgente,
    TarefaIn,
    TransicaoIn,
)
from forja.dominio.erros import (
    Conflito,
    ConflitoVersao,
    IdempotenciaConflito,
    NaoEncontrado,
    OrcamentoExcedido,
    TransicaoInvalida,
    TransicaoReservada,
    ValidacaoDominio,
)
from forja.dominio.estados import (
    RESERVADAS_AO_ORQUESTRADOR,
    EstadoExecucao,
    EstadoTarefa,
    eh_terminal,
    validar_transicao,
)
from forja.dominio.quadro import MensagemIn, TipoMensagem
from forja.dominio.tempo import Relogio, RelogioSistema, iso, somar
from forja.observabilidade.sanitizar import sanitizar
from forja.orquestracao.aprovacoes import AprovacoesMixin, _Espera
from forja.orquestracao.conversa_contexto import ConversaContextoMixin

log = logging.getLogger("forja.servico")


ET, EE = EstadoTarefa, EstadoExecucao
_EXEC_ABERTAS = (EE.PENDENTE, EE.EXECUTANDO, EE.PAUSADA, EE.AGUARDANDO_APROVACAO)
_EXEC_ABERTAS_V = frozenset(x.value for x in _EXEC_ABERTAS)
_FALHA_PROPAGA = (ET.FALHOU, ET.CANCELADA, ET.EXPIRADA)


def _aviso_quadro(estado_exec: str, tarefa: dict, execucao_id: str, resumo: str) -> MensagemIn | None:
    """Traduz o desfecho de uma execucao em mensagem tipada do quadro (None = nada a avisar). Idempotente por execucao+estado."""
    base: dict[str, Any] = {"origem": "sistema", "tarefa_id": tarefa["id"], "referencias": [f"execucao:{execucao_id}", f"tarefa:{tarefa['id']}"],
                            "dedup_key": f"exec:{execucao_id}:{estado_exec}"[:100]}
    titulo = str(tarefa.get("titulo", ""))[:70]
    resumo = str(sanitizar(resumo))[:300]
    if estado_exec == EE.PAUSADA.value and tarefa["estado"] == ET.BLOQUEADA.value:
        return MensagemIn(**base, destino="operador", tipo=TipoMensagem.APONTAMENTO, prioridade=2, assunto=f"Decisao necessaria: {titulo}", payload={"resumo": resumo})
    if estado_exec == EE.CONCLUIDA.value:
        return MensagemIn(**base, destino="master", tipo=TipoMensagem.EVENTO, prioridade=3, assunto=f"Concluida: {titulo}", payload={"resumo": resumo})
    if estado_exec in (EE.FALHOU.value, EE.EXPIRADA.value):
        return MensagemIn(**base, destino="master", tipo=TipoMensagem.APONTAMENTO, prioridade=1 if estado_exec == EE.FALHOU.value else 2,
                          assunto=f"{'Falhou' if estado_exec == EE.FALHOU.value else 'Expirou'}: {titulo}", payload={"resumo": resumo})
    return None


class Servico(ConversaContextoMixin, AprovacoesMixin):
    def __init__(
        self,
        repo: RepositorioSqlite,
        provedor: ProvedorAgente,
        artefatos_dir: Path,
        max_workers: int = 2,
        lock_lease_seconds: int = 900,
        relogio: Relogio | None = None,
        executor: Executor | None = None,
        espera_aprovacao_s: float = 900.0,
        construtor_contexto: Any | None = None,
    ) -> None:
        self.construtor_contexto = (
            construtor_contexto  # ConstrutorContexto (opcional): memoria -> prompt, com orcamento
        )
        self.contexto_ativo = True  # preferencia do usuario (menu de configuracoes): False = nenhum contexto de memoria
        self.espera_aprovacao_s = espera_aprovacao_s
        self.quadro: Any | None = None  # QuadroServico (opcional): o orquestrador avisa o master/operador, sem depender dele
        self._esperas: dict[str, _Espera] = {}
        self.repo = repo
        self.provedor = provedor
        self.artefatos_dir = artefatos_dir
        self.lease = lock_lease_seconds
        self.relogio = relogio or RelogioSistema()
        self._pool: Executor = executor or ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="forja-exec")
        self._ativos: dict[str, ControleExecucao] = {}
        self._futuros: dict[str, Future] = {}
        self._expirando: set[str] = set()
        self._mu = threading.Lock()

    # ------------------------------------------------------------------ utilidades
    def _ts(self) -> str:
        return iso(self.relogio.agora())

    def _ev(
        self,
        t: Tx,
        tipo: str,
        tarefa: dict | None = None,
        execucao_id: str | None = None,
        payload: dict | None = None,
        dedup: str | None = None,
        projeto_id: str | None = None,
    ) -> None:
        t.emitir_evento(
            tipo,
            self._ts(),
            payload,
            projeto_id=projeto_id or (tarefa or {}).get("projeto_id"),
            tarefa_id=(tarefa or {}).get("id"),
            execucao_id=execucao_id,
            correlation_id=(tarefa or {}).get("correlation_id"),
            dedup_key=dedup,
        )

    def _emitir_avulso(
        self, tipo: str, tarefa_id: str | None = None, execucao_id: str | None = None, payload: dict | None = None
    ) -> None:
        with self.repo.escrita() as t:
            tarefa = t.obter(T.Tarefa, tarefa_id) if tarefa_id else None
            self._ev(t, tipo, tarefa, execucao_id, payload)

    def _idempotente(self, escopo: str, chave: str | None, corpo: Any, fn) -> tuple[dict, bool]:
        with self.repo.escrita() as t:
            h = hashlib.sha256(json.dumps(corpo, sort_keys=True, default=str).encode()).hexdigest()
            if chave:
                ex = t.obter_idempotencia(escopo, chave)
                if ex:
                    if ex["request_hash"] != h:
                        raise IdempotenciaConflito("Idempotency-Key reutilizada com corpo diferente.")
                    return ex["resposta"], True
            res = fn(t)
            if chave:
                t.gravar_idempotencia(
                    escopo=escopo, chave=chave, request_hash=h, status_code=201, resposta=res, criado_em=self._ts()
                )
            return res, False

    # ------------------------------------------------------------------ criacao
    def criar_projeto(self, d: ProjetoIn, chave: str | None = None) -> tuple[dict, bool]:
        def fn(t: Tx) -> dict:
            if t.listar(T.Projeto, nome=d.nome):
                raise Conflito(f"Projeto {d.nome!r} ja existe.")
            p = t.inserir(
                T.Projeto, id=novo_id("P"), nome=d.nome, descricao=d.descricao, estado="ativo", criado_em=self._ts()
            )
            self._ev(t, "projeto.criado", payload={"nome": d.nome}, projeto_id=p["id"])
            return p

        return self._idempotente("projeto", chave, d.model_dump(), fn)

    def criar_objetivo(self, d: ObjetivoIn, chave: str | None = None) -> tuple[dict, bool]:
        def fn(t: Tx) -> dict:
            if t.obter(T.Projeto, d.projeto_id) is None:
                raise NaoEncontrado(f"Projeto {d.projeto_id} nao encontrado.")
            o = t.inserir(
                T.Objetivo,
                id=novo_id("OBJ"),
                projeto_id=d.projeto_id,
                titulo=d.titulo,
                descricao=d.descricao,
                prioridade=d.prioridade,
                criterios_sucesso=d.criterios_sucesso,
                orcamento=d.orcamento.model_dump(),
                criado_em=self._ts(),
            )
            self._ev(t, "objetivo.criado", payload={"titulo": d.titulo}, projeto_id=d.projeto_id)
            return o

        return self._idempotente("objetivo", chave, d.model_dump(), fn)

    def criar_tarefa(self, d: TarefaIn, chave: str | None = None) -> tuple[dict, bool]:
        def fn(t: Tx) -> dict:
            obj = t.obter(T.Objetivo, d.objetivo_id)
            if obj is None:
                raise NaoEncontrado(f"Objetivo {d.objetivo_id} nao encontrado.")
            for dep in set(d.dependencias):
                dt = t.obter(T.Tarefa, dep)
                if dt is None:
                    raise ValidacaoDominio(f"Dependencia {dep} nao existe.")
                if dt["projeto_id"] != obj["projeto_id"]:
                    raise ValidacaoDominio(f"Dependencia {dep} pertence a outro projeto.")
            agora = self._ts()
            corr = novo_id("corr")
            tarefa = t.inserir(
                T.Tarefa,
                id=novo_id("T"),
                objetivo_id=d.objetivo_id,
                projeto_id=obj["projeto_id"],
                titulo=d.titulo,
                descricao=d.descricao,
                criterios_aceite=d.criterios_aceite,
                dependencias=sorted(set(d.dependencias)),
                especialidade=d.especialidade,
                modo=d.modo,
                recursos=d.recursos.model_dump(),
                orcamento=d.orcamento.model_dump(),
                politicas=d.politicas.model_dump(),
                entrada=d.entrada,
                contexto_refs=d.contexto_refs,
                estado=ET.RASCUNHO.value,
                versao_estado=1,
                tentativas=0,
                motivo_estado="",
                correlation_id=corr,
                criado_em=agora,
                atualizado_em=agora,
            )
            self._ev(
                t,
                "tarefa.criada",
                tarefa,
                payload={"titulo": d.titulo, "estado": "rascunho"},
                dedup=f"tarefa:{tarefa['id']}:v1",
            )
            return tarefa

        return self._idempotente("tarefa", chave, d.model_dump(), fn)

    # ------------------------------------------------------------------ consultas
    def obter(self, cls: type, id_: str) -> dict:
        with self.repo.leitura() as t:
            r = t.obter(cls, id_)
        if r is None:
            raise NaoEncontrado(f"{cls.__tablename__} {id_} nao encontrado.")
        return r

    def listar(self, cls: type, limite: int = 500, **filtros: Any) -> list[dict]:
        with self.repo.leitura() as t:
            return t.listar(cls, limite=limite, **filtros)

    def progresso_objetivo(self, objetivo_id: str) -> dict:
        with self.repo.leitura() as t:
            obj = t.obter(T.Objetivo, objetivo_id)
            if obj is None:
                raise NaoEncontrado(f"Objetivo {objetivo_id} nao encontrado.")
            por_estado = t.tarefas_por_estado(objetivo_id)
        total = sum(por_estado.values())
        concl = por_estado.get(ET.CONCLUIDA.value, 0)
        return {
            **obj,
            "tarefas_por_estado": por_estado,
            "total_tarefas": total,
            "concluidas_verificadas": concl,
            "completo": total > 0 and concl == total,
        }

    def eventos_apos(self, seq: int, limite: int = 500, projeto_id: str | None = None) -> list[dict]:
        with self.repo.leitura() as t:
            return t.eventos_apos(seq, limite, projeto_id)

    def ultimo_seq(self) -> int:
        with self.repo.leitura() as t:
            return t.ultimo_seq()

    def listar_locks(self) -> list[dict]:
        with self.repo.leitura() as t:
            return t.listar_locks()

    def obter_artefato(self, artefato_id: str, com_conteudo: bool = False) -> dict:
        a = self.obter(T.Artefato, artefato_id)
        if com_conteudo:
            caminho = (self.artefatos_dir / a["caminho_relativo"]).resolve()
            if self.artefatos_dir.resolve() not in caminho.parents:
                raise ValidacaoDominio("Caminho de artefato invalido.")
            dados = caminho.read_bytes()
            if hashlib.sha256(dados).hexdigest() != a["sha256"]:
                raise Conflito("Integridade do artefato violada (hash difere).")
            a = {**a, "conteudo": dados.decode("utf-8", errors="replace")}
        return a

    # ------------------------------------------------------------------ maquina de estados
    def _mudar(
        self,
        t: Tx,
        tarefa: dict,
        para: EstadoTarefa,
        motivo: str = "",
        ator: str = "sistema",
        esperado: int | None = None,
        **extra: Any,
    ) -> dict:
        atual = EstadoTarefa(tarefa["estado"])
        validar_transicao(atual, para)
        ver = tarefa["versao_estado"] if esperado is None else esperado
        if para == ET.CONCLUIDA and t.contar_evidencias(tarefa["id"]) == 0:
            raise Conflito("Conclusao exige ao menos uma evidencia de aceite.")
        ok = t.atualizar_tarefa_condicional(
            tarefa["id"], atual.value, ver, estado=para.value, motivo_estado=motivo, atualizado_em=self._ts(), **extra
        )
        if not ok:
            raise ConflitoVersao("Versao de estado desatualizada (alteracao concorrente).")
        if eh_terminal(para) or para == ET.PRONTA:
            t.liberar_locks(tarefa["id"])
        nova = t.obter(T.Tarefa, tarefa["id"])
        self._ev(
            t,
            f"tarefa.{para.value}",
            nova,
            payload={
                "de": atual.value,
                "para": para.value,
                "versao": nova["versao_estado"],
                "motivo": motivo,
                "ator": ator,
            },
            dedup=f"tarefa:{nova['id']}:v{nova['versao_estado']}",
        )
        if para == ET.CONCLUIDA or para in _FALHA_PROPAGA:
            self._reavaliar_dependentes(t, nova)
        return nova

    def _avaliar_dependencias(self, t: Tx, tarefa_id: str) -> dict:
        tarefa = t.obter(T.Tarefa, tarefa_id)
        if tarefa is None or tarefa["estado"] not in (ET.PREPARADA.value, ET.AGUARDANDO_DEPENDENCIAS.value):
            return tarefa  # type: ignore[return-value]
        estados = [(t.obter(T.Tarefa, d) or {}).get("estado") for d in tarefa["dependencias"]]
        if any(e in {s.value for s in _FALHA_PROPAGA} for e in estados):
            if tarefa["estado"] == ET.PREPARADA.value:
                tarefa = self._mudar(t, tarefa, ET.AGUARDANDO_DEPENDENCIAS, "dependencia terminal sem sucesso")
            return self._mudar(t, tarefa, ET.FALHOU, "dependencia falhou, foi cancelada ou expirou")
        if all(e == ET.CONCLUIDA.value for e in estados):
            return self._mudar(t, tarefa, ET.PRONTA, "dependencias satisfeitas")
        if tarefa["estado"] == ET.PREPARADA.value:
            return self._mudar(t, tarefa, ET.AGUARDANDO_DEPENDENCIAS, "aguardando dependencias")
        return tarefa

    def _reavaliar_dependentes(self, t: Tx, origem: dict) -> None:
        for d in t.listar(T.Tarefa, projeto_id=origem["projeto_id"], estado=ET.AGUARDANDO_DEPENDENCIAS.value):
            if origem["id"] in d["dependencias"]:
                self._avaliar_dependencias(t, d["id"])

    def transicionar(
        self, tarefa_id: str, d: TransicaoIn, ator: str = "operador", chave: str | None = None
    ) -> tuple[dict, bool]:
        if d.para in RESERVADAS_AO_ORQUESTRADOR:
            raise TransicaoReservada(f"Transicao para {d.para.value} e reservada ao orquestrador.")
        if d.para == ET.CANCELADA:
            with self.repo.leitura() as t:
                abertas = [e for e in t.listar(T.Execucao, tarefa_id=tarefa_id) if e["estado"] in _EXEC_ABERTAS_V]
            sinalizadas = False
            for e in abertas:
                with self._mu:
                    sinalizadas = sinalizadas or e["id"] in self._ativos
                self.cancelar_execucao(e["id"], "cancelamento da tarefa", ator)
            if sinalizadas:  # worker vivo finaliza a tarefa como 'cancelada' de forma cooperativa
                return self.obter(T.Tarefa, tarefa_id), False

        def fn(t: Tx) -> dict:
            tarefa = t.obter(T.Tarefa, tarefa_id)
            if tarefa is None:
                raise NaoEncontrado(f"Tarefa {tarefa_id} nao encontrada.")
            if tarefa["estado"] == ET.CANCELADA.value and d.para == ET.CANCELADA:
                return tarefa  # idempotente: ja cancelada (inclusive pelo cancelamento de execucao acima)
            if tarefa["versao_estado"] != d.expected_version:
                raise ConflitoVersao(
                    f"expected_version={d.expected_version} mas a versao atual e {tarefa['versao_estado']}."
                )
            nova = self._mudar(t, tarefa, d.para, d.motivo, ator, esperado=d.expected_version)
            if d.para == ET.PREPARADA:
                nova = self._avaliar_dependencias(t, tarefa_id)
            return nova

        return self._idempotente(f"transicao:{tarefa_id}", chave, d.model_dump(mode="json"), fn)

    # ------------------------------------------------------------------ execucoes
    def criar_execucao(self, tarefa_id: str) -> dict:
        with self.repo.escrita() as t:
            tarefa = t.obter(T.Tarefa, tarefa_id)
            if tarefa is None:
                raise NaoEncontrado(f"Tarefa {tarefa_id} nao encontrada.")
            if tarefa["estado"] != ET.PRONTA.value:
                raise TransicaoInvalida(f"Tarefa em {tarefa['estado']}; apenas tarefas 'pronta' podem executar.")
            abertas = [e for e in t.listar(T.Execucao, tarefa_id=tarefa_id) if e["estado"] in _EXEC_ABERTAS_V]
            if abertas:
                raise Conflito(f"Tarefa ja possui execucao aberta ({abertas[0]['id']}).")
            ex = t.inserir(
                T.Execucao,
                id=novo_id("EX"),
                tarefa_id=tarefa_id,
                estado=EE.PENDENTE.value,
                agente_id=self.provedor.id,
                tentativa=0,
                checkpoint={},
                correlation_id=tarefa["correlation_id"],
                criado_em=self._ts(),
            )
            self._ev(t, "execucao.criada", tarefa, ex["id"], {"agente": self.provedor.id, "mock": self.provedor.mock})
            return ex

    def iniciar_execucao(self, execucao_id: str, ator: str = "operador") -> dict:
        try:
            resultado = self._iniciar_tx(execucao_id, ator)
        except (OrcamentoExcedido, Conflito) as e:
            if e.codigo in {"orcamento_excedido", "recurso_bloqueado"}:
                with self.repo.leitura() as t:
                    ex = t.obter(T.Execucao, execucao_id)
                self._emitir_avulso(
                    f"execucao.{e.codigo}", ex["tarefa_id"] if ex else None, execucao_id, {"motivo": e.mensagem}
                )
            raise
        if resultado["estado"] == EE.EXECUTANDO.value:
            self._submeter(execucao_id)
        return resultado

    def _iniciar_tx(self, execucao_id: str, ator: str) -> dict:
        with self.repo.escrita() as t:
            ex = t.obter(T.Execucao, execucao_id)
            if ex is None:
                raise NaoEncontrado(f"Execucao {execucao_id} nao encontrada.")
            tarefa = t.obter(T.Tarefa, ex["tarefa_id"])
            agora = self.relogio.agora()
            if ex["estado"] == EE.PENDENTE.value:
                if tarefa["estado"] != ET.PRONTA.value:
                    raise TransicaoInvalida(f"Tarefa em {tarefa['estado']}; esperado 'pronta'.")
                if tarefa["tentativas"] + 1 > tarefa["orcamento"]["max_tentativas"]:
                    raise OrcamentoExcedido("max_tentativas excedido.")
                t.adquirir_locks(tarefa["recursos"]["escrita"], tarefa["id"], iso(agora), iso(somar(agora, self.lease)))
                tarefa = self._mudar(t, tarefa, ET.ATRIBUIDA, "execucao iniciada", ator)
                tarefa = self._mudar(
                    t, tarefa, ET.EXECUTANDO, "agente executando", ator, tentativas=tarefa["tentativas"] + 1
                )
                t.atualizar(
                    T.Execucao,
                    ex["id"],
                    estado=EE.EXECUTANDO.value,
                    tentativa=tarefa["tentativas"],
                    iniciado_em=iso(agora),
                    deadline=iso(somar(agora, tarefa["orcamento"]["max_duracao_segundos"])),
                )
                self._ev(t, "execucao.iniciada", tarefa, ex["id"], {"mock": self.provedor.mock})
                if tarefa["politicas"].get("exige_aprovacao"):
                    ap = t.inserir(
                        T.Aprovacao,
                        id=novo_id("AP"),
                        tarefa_id=tarefa["id"],
                        execucao_id=ex["id"],
                        acao="executar_tarefa",
                        estado="pendente",
                        criado_em=self._ts(),
                        justificativa=f"Politica exige aprovacao: {tarefa['titulo']}",
                    )
                    self._mudar(t, tarefa, ET.AGUARDANDO_APROVACAO, "aguardando aprovacao", ator)
                    t.atualizar(T.Execucao, ex["id"], estado=EE.AGUARDANDO_APROVACAO.value)
                    self._ev(t, "aprovacao.solicitada", tarefa, ex["id"], {"aprovacao_id": ap["id"]})
            elif ex["estado"] == EE.PAUSADA.value:
                if ex["deadline"] and ex["deadline"] <= iso(agora):
                    raise OrcamentoExcedido("max_duracao_segundos excedido; execucao expirada.")
                if tarefa["estado"] != ET.BLOQUEADA.value:
                    raise TransicaoInvalida(f"Tarefa em {tarefa['estado']}; esperado 'bloqueada'.")
                t.adquirir_locks(tarefa["recursos"]["escrita"], tarefa["id"], iso(agora), iso(somar(agora, self.lease)))
                tarefa = self._mudar(t, tarefa, ET.EXECUTANDO, "execucao retomada", ator)
                t.atualizar(T.Execucao, ex["id"], estado=EE.EXECUTANDO.value)
                self._ev(t, "execucao.retomada", tarefa, ex["id"], {"checkpoint": ex["checkpoint"]})
            else:
                raise Conflito(f"Execucao em {ex['estado']} nao pode ser iniciada.")
            return t.obter(T.Execucao, execucao_id)

    def _submeter(self, execucao_id: str) -> None:
        ctl = ControleExecucao(
            persistir_checkpoint=lambda cp: self._salvar_checkpoint(execucao_id, cp),
            emitir=lambda tipo, p: self._emitir_exec(execucao_id, tipo, p),
            aprovar=lambda itens: self._solicitar_durante(execucao_id, ctl, itens),
        )
        with self._mu:
            self._ativos[execucao_id] = ctl
            self._futuros[execucao_id] = self._pool.submit(self._rodar, execucao_id, ctl)

    def aguardar(self, execucao_id: str, timeout: float = 10.0) -> None:
        with self._mu:
            f = self._futuros.get(execucao_id)
        if f is not None:
            f.result(timeout=timeout)

    def _salvar_checkpoint(self, execucao_id: str, cp: dict) -> None:
        with self.repo.escrita() as t:
            t.atualizar(T.Execucao, execucao_id, checkpoint=sanitizar(cp))

    def _emitir_exec(self, execucao_id: str, tipo: str, payload: dict) -> None:
        with self.repo.escrita() as t:
            ex = t.obter(T.Execucao, execucao_id)
            tarefa = t.obter(T.Tarefa, ex["tarefa_id"]) if ex else None
            self._ev(t, tipo, tarefa, execucao_id, payload)

    def _rodar(self, execucao_id: str, ctl: ControleExecucao) -> None:
        try:
            with self.repo.leitura() as t:
                ex = t.obter(T.Execucao, execucao_id)
                tarefa = t.obter(T.Tarefa, ex["tarefa_id"])
                tarefa["adendos_operador"] = [
                    a["adendo"]
                    for a in t.listar(T.Aprovacao, execucao_id=execucao_id, estado="aprovada")
                    if a["origem"] == "pre_execucao" and a["adendo"]
                ]
                tarefa["retomada"] = self._dados_de_retomada(t, tarefa, execucao_id)
            pacote = self._montar_contexto(execucao_id, tarefa)
            self._emitir_exec(execucao_id, "agente.iniciado", {"agente": self.provedor.id, "mock": self.provedor.mock})
            res = self.provedor.executar(tarefa, ex["checkpoint"] or {}, ctl)
            self._registrar_uteis(execucao_id, pacote, res)
        except Exception:  # noqa: BLE001 - isolamento do provedor
            log.exception("falha no provedor de agente", extra={"execucao_id": execucao_id})
            res = ResultadoAgente(
                estado="falhou",
                resumo="Erro interno no provedor de agente.",
                agente_id=self.provedor.id,
                mock=self.provedor.mock,
            )
        try:
            self._finalizar(execucao_id, ctl, res)
        except Exception:  # noqa: BLE001
            log.exception("falha ao finalizar execucao", extra={"execucao_id": execucao_id})
        finally:
            with self._mu:
                self._ativos.pop(execucao_id, None)
                self._expirando.discard(execucao_id)


    def _gravar_artefato(self, conteudo: str) -> tuple[str, str, int]:
        dados = conteudo.encode("utf-8")
        sha = hashlib.sha256(dados).hexdigest()
        rel = f"{sha[:2]}/{sha}"
        destino = self.artefatos_dir / rel
        destino.parent.mkdir(parents=True, exist_ok=True)
        if not destino.exists():
            # .tmp UNICO por escritor: o blob e enderecado por conteudo, entao execucoes concorrentes com resposta
            # identica disputam o mesmo destino (um .tmp compartilhado falhava com PermissionError no Windows).
            tmp = destino.with_name(f"{destino.name}.{uuid.uuid4().hex}.tmp")
            try:
                tmp.write_bytes(dados)
                try:
                    tmp.replace(destino)
                except OSError:
                    if not destino.exists():  # outro escritor vencer a corrida e aceitavel: conteudo identico (hash)
                        raise
            finally:
                tmp.unlink(missing_ok=True)
        return sha, rel, len(dados)

    def _finalizar(self, execucao_id: str, ctl: ControleExecucao, res: ResultadoAgente) -> None:
        gravados = {a.nome: (a, *self._gravar_artefato(a.conteudo)) for a in res.artefatos}
        with self.repo.escrita() as t:
            ex = t.obter(T.Execucao, execucao_id)
            tarefa = t.obter(T.Tarefa, ex["tarefa_id"])
            if ex["estado"] in {EE.CONCLUIDA.value, EE.FALHOU.value, EE.CANCELADA.value, EE.EXPIRADA.value}:
                return
            # nada fica pendente sem worker
            for ap in t.listar(T.Aprovacao, execucao_id=execucao_id, estado="pendente"):
                t.atualizar(
                    T.Aprovacao,
                    ap["id"],
                    estado="negada",
                    decidido_por="sistema:execucao_encerrada",
                    decidido_em=self._ts(),
                    escopo={"aprovados": [], "lembrar": False},
                )
            tarefa = t.obter(T.Tarefa, tarefa["id"])
            if eh_terminal(EstadoTarefa(tarefa["estado"])):
                t.atualizar(T.Execucao, execucao_id, estado=EE.CANCELADA.value, finalizado_em=self._ts())
                return
            if (
                tarefa["estado"] == ET.AGUARDANDO_APROVACAO.value
                and not ctl.cancelado()
                and execucao_id not in self._expirando
            ):
                tarefa = self._mudar(t, tarefa, ET.EXECUTANDO, "pedido de aprovacao encerrado")
            agora = self._ts()
            resumo = sanitizar(res.model_dump(exclude={"artefatos", "mensagens"}))
            anteriores = int(((ex.get("resultado") or {}).get("chamadas_acumuladas")) or 0)
            total_chamadas = anteriores + res.consumo.chamadas_modelo  # orcamento vale para a TAREFA, nao por retomada
            resumo["chamadas_acumuladas"] = total_chamadas
            self._persistir_mensagens(t, tarefa, execucao_id, res)
            fim: dict[str, Any] = {"resultado": resumo, "finalizado_em": agora}
            if execucao_id in self._expirando:
                t.atualizar(T.Execucao, execucao_id, estado=EE.EXPIRADA.value, **fim)
                self._mudar(t, tarefa, ET.EXPIRADA, "max_duracao_segundos excedido")
                self._ev(t, "execucao.expirada", tarefa, execucao_id)
            elif ctl.cancelado() or res.estado == "cancelada":
                t.atualizar(T.Execucao, execucao_id, estado=EE.CANCELADA.value, **fim)
                self._mudar(t, tarefa, ET.CANCELADA, "execucao cancelada")
                self._ev(t, "execucao.cancelada", tarefa, execucao_id)
            elif res.estado in ("pausada", "bloqueada"):
                t.atualizar(T.Execucao, execucao_id, estado=EE.PAUSADA.value, resultado=resumo)
                self._mudar(t, tarefa, ET.BLOQUEADA, res.estado + ": " + res.resumo[:200])
                self._ev(t, f"execucao.{res.estado}", tarefa, execucao_id, {"pendencias": res.pendencias})
            elif res.estado == "falhou" or total_chamadas > tarefa["orcamento"]["max_chamadas_modelo"]:
                motivo = res.resumo if res.estado == "falhou" else "max_chamadas_modelo excedido"
                t.atualizar(T.Execucao, execucao_id, estado=EE.FALHOU.value, **fim)
                self._mudar(t, tarefa, ET.FALHOU, motivo[:500])
                self._ev(t, "execucao.falhou", tarefa, execucao_id, {"motivo": motivo})
            else:
                self._concluir(t, tarefa, execucao_id, res, gravados, fim)
        self._avisar_quadro(execucao_id)

    def _avisar_quadro(self, execucao_id: str) -> None:
        """Publica no quadro o desfecho que exige atencao. Melhor esforco: falha aqui nunca altera o resultado da execucao."""
        if self.quadro is None:
            return
        try:
            with self.repo.leitura() as t:
                ex = t.obter(T.Execucao, execucao_id)
                tarefa = t.obter(T.Tarefa, ex["tarefa_id"]) if ex else None
            if not ex or not tarefa:
                return
            aviso = _aviso_quadro(ex["estado"], tarefa, execucao_id, (ex.get("resultado") or {}).get("resumo", ""))
            if aviso is not None:
                self.quadro.publicar(aviso, ator="sistema")
        except Exception:  # noqa: BLE001 - o quadro e informativo
            log.exception("falha ao publicar no quadro", extra={"execucao_id": execucao_id})

    def _concluir(self, t: Tx, tarefa: dict, execucao_id: str, res: ResultadoAgente, gravados: dict, fim: dict) -> None:
        ids_art: dict[str, str] = {}
        for nome, (a, sha, rel, tam) in gravados.items():
            row = t.inserir(
                T.Artefato,
                id=novo_id("ART"),
                tarefa_id=tarefa["id"],
                execucao_id=execucao_id,
                nome=nome,
                tipo=a.tipo,
                sha256=sha,
                caminho_relativo=rel,
                tamanho=tam,
                origem=res.agente_id,
                criado_em=self._ts(),
            )
            ids_art[nome] = row["id"]
        for ev in res.evidencias:
            t.inserir(
                T.Evidencia,
                id=novo_id("EVID"),
                tarefa_id=tarefa["id"],
                execucao_id=execucao_id,
                tipo=ev.tipo,
                resumo=ev.resumo,
                artefato_id=ids_art.get(ev.artefato or ""),
                simulada=ev.simulada or res.mock,
                criado_em=self._ts(),
            )
        tarefa = self._mudar(t, tarefa, ET.VALIDANDO, "validando resultado")
        # Verificacao deterministica: evidencia presente e integridade dos artefatos gravados.
        integros = all(
            hashlib.sha256((self.artefatos_dir / rel).read_bytes()).hexdigest() == sha
            for (_a, sha, rel, _n) in gravados.values()
        )
        if res.evidencias and integros:
            t.atualizar(T.Execucao, execucao_id, estado=EE.CONCLUIDA.value, **fim)
            nova = self._mudar(t, tarefa, ET.CONCLUIDA, "criterios verificados")
            self._ev(
                t, "execucao.concluida", nova, execucao_id, {"evidencias": len(res.evidencias), "simulada": res.mock}
            )
        else:
            t.atualizar(T.Execucao, execucao_id, estado=EE.FALHOU.value, **fim)
            self._mudar(t, tarefa, ET.FALHOU, "validacao reprovada: sem evidencia ou artefato corrompido")
            self._ev(t, "execucao.falhou", tarefa, execucao_id, {"motivo": "validacao_reprovada"})

    # ------------------------------------------------------------------ pausa / cancelamento / expiracao
    def pausar_execucao(self, execucao_id: str) -> dict:
        with self._mu:
            ctl = self._ativos.get(execucao_id)
        ex = self.obter(T.Execucao, execucao_id)
        if ex["estado"] != EE.EXECUTANDO.value:
            raise Conflito(f"Execucao em {ex['estado']} nao pode ser pausada.")
        if ctl is None:
            raise Conflito("Execucao sem worker ativo; reinicie o servidor para recuperacao ou cancele.")
        ctl.pausar_ev.set()
        self._emitir_avulso("execucao.pausa_solicitada", ex["tarefa_id"], execucao_id)
        return ex

    def cancelar_execucao(self, execucao_id: str, motivo: str = "", ator: str = "operador") -> dict:
        with self._mu:
            ctl = self._ativos.get(execucao_id)
        if ctl is not None:
            ctl.cancelar_ev.set()
            self._emitir_avulso("execucao.cancelamento_solicitado", None, execucao_id, {"ator": ator, "motivo": motivo})
            return self.obter(T.Execucao, execucao_id)
        with self.repo.escrita() as t:
            ex = t.obter(T.Execucao, execucao_id)
            if ex is None:
                raise NaoEncontrado(f"Execucao {execucao_id} nao encontrada.")
            if ex["estado"] not in _EXEC_ABERTAS_V:
                raise Conflito(f"Execucao em {ex['estado']} nao pode ser cancelada.")
            tarefa = t.obter(T.Tarefa, ex["tarefa_id"])
            t.atualizar(T.Execucao, execucao_id, estado=EE.CANCELADA.value, finalizado_em=self._ts())
            for ap in t.listar(T.Aprovacao, execucao_id=execucao_id, estado="pendente"):
                t.atualizar(T.Aprovacao, ap["id"], estado="negada", decidido_por=ator, decidido_em=self._ts())
            if tarefa["estado"] in (
                ET.EXECUTANDO.value,
                ET.BLOQUEADA.value,
                ET.AGUARDANDO_APROVACAO.value,
                ET.ATRIBUIDA.value,
            ):
                self._mudar(t, tarefa, ET.CANCELADA, motivo or "execucao cancelada", ator)
            self._ev(t, "execucao.cancelada", tarefa, execucao_id, {"ator": ator, "motivo": motivo})
            return t.obter(T.Execucao, execucao_id)

    def expirar_vencidas(self) -> int:
        """Aplica max_duracao_segundos. Execucoes vivas sao sinalizadas; orfas expiram direto."""
        agora = self._ts()
        n = 0
        with self.repo.escrita() as t:
            for estado in (EE.EXECUTANDO, EE.PAUSADA, EE.AGUARDANDO_APROVACAO):
                for ex in t.listar(T.Execucao, estado=estado.value):
                    if not ex["deadline"] or ex["deadline"] > agora:
                        continue
                    with self._mu:
                        ctl = self._ativos.get(ex["id"])
                        if ctl is not None:
                            self._expirando.add(ex["id"])
                    n += 1
                    if ctl is not None:
                        ctl.cancelar_ev.set()
                        continue
                    tarefa = t.obter(T.Tarefa, ex["tarefa_id"])
                    t.atualizar(T.Execucao, ex["id"], estado=EE.EXPIRADA.value, finalizado_em=agora)
                    self._mudar(t, tarefa, ET.EXPIRADA, "max_duracao_segundos excedido")
                    self._ev(t, "execucao.expirada", tarefa, ex["id"])
        return n


    # ------------------------------------------------------------------ ciclo de vida
    def recuperar(self) -> dict:
        """Pos-crash/restart: execucoes 'executando' sem worker viram 'pausada' (retomaveis)."""
        recuperadas = 0
        with self.repo.escrita() as t:
            t.purgar_locks_expirados(self._ts())
            for ex in t.listar(T.Execucao, estado=EE.EXECUTANDO.value):
                with self._mu:
                    if ex["id"] in self._ativos:
                        continue
                tarefa = t.obter(T.Tarefa, ex["tarefa_id"])
                t.atualizar(T.Execucao, ex["id"], estado=EE.PAUSADA.value)
                if tarefa["estado"] == ET.EXECUTANDO.value:
                    tarefa = self._mudar(t, tarefa, ET.BLOQUEADA, "reinicio_servidor: retomavel pelo checkpoint")
                self._ev(t, "execucao.recuperada", tarefa, ex["id"], {"checkpoint": ex["checkpoint"]})
                recuperadas += 1
            # Pedidos de aprovacao feitos DURANTE a execucao ficam orfaos se o worker morreu: nega e deixa retomavel.
            for ex in t.listar(T.Execucao, estado=EE.AGUARDANDO_APROVACAO.value):
                pend = [
                    a
                    for a in t.listar(T.Aprovacao, execucao_id=ex["id"], estado="pendente")
                    if a["origem"] == "durante_execucao"
                ]
                with self._mu:
                    if not pend or ex["id"] in self._ativos:
                        continue
                for a in pend:
                    t.atualizar(
                        T.Aprovacao,
                        a["id"],
                        estado="negada",
                        decidido_por="sistema:reinicio",
                        decidido_em=self._ts(),
                        escopo={"aprovados": [], "lembrar": False},
                    )
                tarefa = t.obter(T.Tarefa, ex["tarefa_id"])
                t.atualizar(T.Execucao, ex["id"], estado=EE.PAUSADA.value)
                if tarefa["estado"] == ET.AGUARDANDO_APROVACAO.value:
                    # AGUARDANDO_APROVACAO -> EXECUTANDO -> BLOQUEADA: retomavel pelo checkpoint
                    tarefa = self._mudar(t, tarefa, ET.EXECUTANDO, "reinicio_servidor")
                    tarefa = self._mudar(t, tarefa, ET.BLOQUEADA, "reinicio_servidor: pedido de aprovacao negado")
                self._ev(t, "execucao.recuperada", tarefa, ex["id"], {"motivo": "aprovacao_pendente_orfa"})
                recuperadas += 1
            t.emitir_evento("servidor.iniciado", self._ts(), {"execucoes_recuperadas": recuperadas})
        expiradas = self.expirar_vencidas()
        return {"recuperadas": recuperadas, "expiradas": expiradas}

    def encerrar(self, timeout: float = 15.0) -> None:
        """Shutdown gracioso: pede pausa cooperativa (checkpoint) e aguarda workers."""
        with self._mu:
            for ctl in self._ativos.values():
                ctl.pausar_ev.set()
            futuros = list(self._futuros.values())
        for f in futuros:
            try:
                f.result(timeout=timeout)
            except Exception:  # noqa: BLE001
                log.exception("worker nao encerrou limpo")
        self._pool.shutdown(wait=True)
        try:
            self._emitir_avulso("servidor.encerrado")
        except Exception:  # noqa: BLE001
            log.exception("nao foi possivel registrar encerramento")
        finally:
            self.repo.fechar()
