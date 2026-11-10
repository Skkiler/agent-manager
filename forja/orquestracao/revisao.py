"""Revisao do esquema: o operador pede que um agente reavalie a plataforma (melhorias possiveis x ponto agradavel).

O orquestrador coleta fatos DETERMINISTICOS (versoes, uso das ferramentas, modelos configurados, volume de tarefas e
memoria) e cria uma tarefa de analise com criterios de aceite que exigem evidencia e fontes. Nao altera nada sozinho
e nao executa sem pedido explicito (executar=true), pois executar consome creditos do provedor.
"""

from __future__ import annotations

import json
import platform
from importlib import metadata
from typing import Any

from forja import __version__
from forja.adapters.sqlite import tabelas as T
from forja.dominio.contratos import ObjetivoIn, ProjetoIn, TarefaIn, TransicaoIn
from forja.dominio.estados import EstadoTarefa
from forja.ferramentas.catalogo import Catalogo
from forja.orquestracao.configuracao_servico import ConfiguracaoServico
from forja.orquestracao.servico import Servico

ESCOPOS = ("arquitetura", "busca_e_memoria", "ferramentas", "interface", "seguranca", "custo_e_modelos")
BIBLIOTECAS = ("fastapi", "pydantic", "sqlalchemy", "alembic", "uvicorn")
PROJETO = "forja-revisoes"
MAX_SNAPSHOT = 3500

CRITERIOS = [
    "Separa o que ja esta adequado (com a evidencia que sustenta) do que pode melhorar",
    "Cada melhoria traz beneficio esperado, custo/risco e esforco, em ordem de prioridade",
    "Toda afirmacao sobre modelos, bibliotecas ou pesquisas recentes cita a fonte e a data",
    "Diz explicitamente quando nada precisa mudar agora e o que monitorar",
    "Nao altera arquivos nem executa comandos que escrevam em disco",
]


def _versao(pacote: str) -> str:
    try:
        return metadata.version(pacote)
    except metadata.PackageNotFoundError:
        return "?"


class RevisaoServico:
    def __init__(self, servico: Servico, catalogo: Catalogo, configuracao: ConfiguracaoServico) -> None:
        self.servico = servico
        self.catalogo = catalogo
        self.configuracao = configuracao

    def snapshot(self) -> dict[str, Any]:
        """Fatos medidos agora. Nada aqui e opiniao: o agente decide o que fazer com eles."""
        with self.servico.repo.leitura() as t:
            tarefas: dict[str, int] = {}
            for tf in t.listar(T.Tarefa, limite=5000):
                tarefas[tf["estado"]] = tarefas.get(tf["estado"], 0) + 1
            memorias: dict[str, int] = {}
            for m in t.listar(T.Memoria, limite=5000):
                memorias[m["estado"]] = memorias.get(m["estado"], 0) + 1
        cfg = self.configuracao.obter()
        uso = self.catalogo.estatisticas()
        return {
            "forja": __version__,
            "python": platform.python_version(),
            "bibliotecas": {b: _versao(b) for b in BIBLIOTECAS},
            "ferramentas": {"total": len(self.catalogo.ferramentas),
                            "com_uso": {k: {"chamadas": v["chamadas"], "erros": v["erros"], "fallbacks": v["fallbacks"]}
                                        for k, v in uso.items()},
                            "sem_uso": sorted(set(self.catalogo.ferramentas) - set(uso))},
            "modelos": {p["id"]: p["modelo_efetivo"] for p in cfg["partes"] if p["usa_modelo"]},
            "tarefas_por_estado": tarefas,
            "memorias_por_estado": memorias,
        }

    def montar_descricao(self, escopo: list[str], pesquisar_web: bool, snap: dict[str, Any]) -> str:
        fatos = json.dumps(snap, ensure_ascii=False, separators=(",", ":"))
        if len(fatos) > MAX_SNAPSHOT:
            fatos = fatos[:MAX_SNAPSHOT] + "...(cortado)"
        pesquisa = ("Se tiver ferramenta de pesquisa, busque novidades de modelos e praticas relevantes e CITE fontes e datas. "
                    if pesquisar_web else "Nao pesquise na web: baseie-se nos fatos abaixo e no repositorio. ")
        return (f"Reavalie a plataforma Forja nos eixos: {', '.join(escopo)}. {pesquisa}"
                "Pergunta central: ha melhorias que valem o custo agora (novos modelos, pesquisas, bibliotecas, simplificacoes) "
                "ou o esquema esta num ponto agradavel? Responda com secoes: Entendimento, Adequado hoje, Melhorias "
                "priorizadas (beneficio, custo, risco), Fontes, Decisoes para voce. Fatos medidos agora: " + fatos)

    def solicitar(self, escopo: list[str], pesquisar_web: bool = False, executar: bool = False) -> dict[str, Any]:
        snap = self.snapshot()
        projeto = next(iter(self.servico.listar(T.Projeto, nome=PROJETO)), None)
        if projeto is None:
            projeto, _ = self.servico.criar_projeto(ProjetoIn(nome=PROJETO, descricao="Revisoes periodicas do esquema"))
        objetivo, _ = self.servico.criar_objetivo(ObjetivoIn(
            projeto_id=projeto["id"], titulo=f"Revisao ({', '.join(escopo)})", prioridade=3,
            criterios_sucesso=["Relatorio com melhorias priorizadas ou confirmacao de que nada precisa mudar"]))
        tarefa, _ = self.servico.criar_tarefa(TarefaIn(
            objetivo_id=objetivo["id"], titulo=f"Revisao do esquema: {', '.join(escopo)}"[:200],
            descricao=self.montar_descricao(escopo, pesquisar_web, snap), criterios_aceite=CRITERIOS,
            especialidade="arquitetura", modo="analise",
            entrada={"revisao": True, "escopo": escopo, "pesquisar_web": pesquisar_web}))
        for destino in (EstadoTarefa.CLASSIFICADA, EstadoTarefa.PREPARADA):
            tarefa, _ = self.servico.transicionar(
                tarefa["id"], TransicaoIn(para=destino, expected_version=tarefa["versao_estado"]))
        execucao = None
        if executar:
            execucao = self.servico.criar_execucao(tarefa["id"])
            self.servico.iniciar_execucao(execucao["id"], "operador")
        return {"tarefa": tarefa, "execucao_id": execucao["id"] if execucao else None, "snapshot": snap}
