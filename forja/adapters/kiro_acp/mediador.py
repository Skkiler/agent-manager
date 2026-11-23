"""Mediador de permissoes: transforma N pedidos de ferramenta do Kiro em UMA pergunta de aprovacao por grupo de acoes.

Regras:
- Acoes sensiveis (segredos/credenciais) sao negadas AUTOMATICAMENTE, sem perguntar (invariante de seguranca).
- Pedidos que chegam dentro de uma janela curta sao agrupados em um unico pedido ao operador.
- Uma aprovacao pode ser "lembrada" ate o fim da execucao (mesma categoria + alvos): evita perguntar de novo.
- Nunca escolhe `allow_always` do Kiro: a memoria de decisoes e da Forja, auditavel e limitada a execucao.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

from forja.agentes.base import ControleExecucao
from forja.agentes.estilo import PADRAO, PerfilTrabalho
from forja.seguranca.acoes import FORJA_LIVRES, descrever_acao
from forja.seguranca.pastas import dentro_de_citado
from forja.seguranca.regras import avaliar as avaliar_regras

log = logging.getLogger("forja.mediador")


def _opcao(opcoes: list[dict[str, Any]], *tipos: str) -> str | None:
    for tipo in tipos:
        for o in opcoes:
            if str(o.get("kind", "")) == tipo:
                return str(o.get("optionId"))
    return None


def _rejeitar(opcoes: list[dict[str, Any]]) -> str | None:
    achada = _opcao(opcoes, "reject_once")
    if achada:
        return achada
    for o in opcoes:
        if str(o.get("kind", "")).startswith("reject"):
            return str(o.get("optionId"))
    return None  # sem opcao de rejeicao: o cliente responde 'cancelled'


class _Lote:
    def __init__(self) -> None:
        self.itens: list[dict[str, Any]] = []
        self.pronto = threading.Event()
        self.aprovados: set[str] = set()
        self.lembrar = False


class MediadorPermissoes:
    def __init__(self, ctl: ControleExecucao, workspace: Path, janela: float = 0.8, espera_max: float = 1800.0,
                 perfil: PerfilTrabalho = PADRAO, trabalho: list[Path] | None = None, consulta: list[Path] | None = None) -> None:
        self.trabalho, self.consulta = list(trabalho or []), list(consulta or [])  # pastas do projeto
        self.perfil = perfil  # nivel de autonomia: quais acoes reversiveis dentro do workspace dispensam pergunta
        self.ctl = ctl
        self.workspace = workspace
        self.janela = janela
        self.espera_max = espera_max
        self.adendos: list[str] = []
        self.perguntas = 0  # quantas vezes o operador foi realmente consultado
        self._lote: _Lote | None = None
        self._mu = threading.Lock()
        self._lembradas: set[str] = set()
        self.limite_arquivos = 0  # 0 = sem limite; o provedor define pelo nivel da tarefa (controle de escopo)
        self._escritos: set[str] = set()
        self._avisou_escopo = False
        # A pasta (trabalho/consulta) tem arquivos com cara de segredo? (provedor confere SO os nomes). Se sim, comando de varredura
        # ampla (busca/copia recursiva) nunca e aprovado sozinho: ele le o .env sem citar o nome (achado no Kiro real).
        self.pasta_com_segredos = False
        # Fora das pastas do projeto (ADR-027): 'perguntar' (padrao: pede permissao, exceto leitura do que o usuario citou no
        # pedido), 'bloquear' (nega sem perguntar) ou 'livre_leitura' (leitura fora aprovada; escrita fora continua perguntando).
        self.fora_da_pasta = "perguntar"
        self.citados: list[Path] = []  # caminhos absolutos citados pelo usuario no pedido (seguranca.pastas.caminhos_citados)
        # Pastas que a tarefa manda IGNORAR (ex.: estudo em lote: logs, dados, entrada): leitura negada sem perguntar (ADR-029)
        self.ignorar_dirs: frozenset[str] = frozenset()
        # Tarefa de ESTUDO: a pasta de consulta e exatamente o que o usuario mandou estudar; ler dentro dela dispensa pergunta
        # em qualquer nivel (so leitura simples: varredura em pasta com segredo continua perguntando)
        self.leitura_consulta_livre = False

    def _leitura_em_consulta(self, item: dict[str, Any]) -> bool:
        if item.get("categoria") != "ler" or item.get("sensivel") or item.get("varredura") or not self.consulta:
            return False
        return bool(item.get("so_consulta"))

    def _ignorada(self, item: dict[str, Any]) -> bool:
        if not self.ignorar_dirs:
            return False
        for alvo in item.get("alvos") or []:
            partes = {p.casefold() for p in Path(str(alvo)).parts[:-1]} | ({Path(str(alvo)).name.casefold()} if item.get("categoria") == "ler" else set())
            if partes & self.ignorar_dirs:
                return True
        return False

    def _conferir_escopo(self, item: dict[str, Any]) -> bool:
        """Anti 'esticar': passou do limite de arquivos escritos da tarefa, cada nova escrita deixa de ser automatica e PERGUNTA
        (mesmo nos niveis liberado/total). O usuario ve exatamente o que o agente quer mexer alem do esperado."""
        if not self.limite_arquivos or item.get("categoria") not in ("modificar_arquivos", "mover", "excluir", "excluir_forcado"):
            return False
        with self._mu:
            novos = [a for a in item.get("alvos") or [] if a not in self._escritos]
            self._escritos.update(item.get("alvos") or [])
            excedeu = len(self._escritos) > self.limite_arquivos and bool(novos)
            avisar = excedeu and not self._avisou_escopo
            self._avisou_escopo = self._avisou_escopo or excedeu
        if avisar:
            self.ctl.evento("kiro.escopo_excedido", {"limite": self.limite_arquivos, "arquivos": len(self._escritos)})
        return excedeu

    @staticmethod
    def _chave(item: dict[str, Any]) -> str:
        return f"{item['categoria']}|{','.join(sorted(item['alvos']))}"

    def decidir(self, pedido: dict[str, Any]) -> str | None:
        """Implementa DecisorPermissao. Retorna optionId (ou None => cancelar)."""
        opcoes = pedido.get("options", [])
        item = descrever_acao(pedido.get("toolCall") or {}, self.workspace, self.trabalho, self.consulta)
        rejeitar = _rejeitar(opcoes)
        permitir = _opcao(opcoes, "allow_once")
        if item["sensivel"]:
            self.ctl.evento("kiro.permissao_negada_automatica",
                            {"motivo": "acao envolve segredo/credencial", "descricao": item["descricao"]})
            return rejeitar
        if self._ignorada(item):
            self.ctl.evento("kiro.permissao_negada_automatica", {"motivo": "pasta ignorada nesta tarefa (logs/dados)", "descricao": item["descricao"]})
            return rejeitar
        if item.get("em_consulta"):  # pasta de consulta e SO leitura, em qualquer nivel
            self.ctl.evento("kiro.permissao_negada_automatica", {"motivo": "pasta de consulta e somente leitura", "descricao": item["descricao"]})
            return rejeitar
        if permitir is None:  # sem como permitir uma vez: nao arrisca allow_always
            return rejeitar
        if self.leitura_consulta_livre and self._leitura_em_consulta(item):
            # estudo: ler a pasta que o usuario mandou estudar E o pedido (segredos ja negados acima; pastas ignoradas tambem)
            self.ctl.evento("kiro.permissao_automatica", {"nivel": self.perfil.nivel, "categoria": "ler", "descricao": item["descricao"],
                                                          "motivo": "estudo: leitura da pasta estudada"})
            return permitir
        alem_do_escopo = self._conferir_escopo(item)
        varre_segredo = bool(item.get("varredura")) and self.pasta_com_segredos  # invariante: nenhuma regra do usuario afrouxa
        if varre_segredo:
            item = {**item, "risco": "alto", "descricao": item["descricao"].rstrip("?") + " (atenção: esta pasta tem arquivos de segredo, "
                    "como .env, e este comando lê muitos arquivos de uma vez; ele pode ler o segredo)?"}
            self.ctl.evento("kiro.varredura_com_segredos", {"descricao": item["descricao"][:300]})
        decisao = avaliar_regras(self.perfil.regras, item) if self.perfil.regras else None
        if decisao is not None:  # regras do usuario: auditaveis (evento com o nome da regra)
            self.ctl.evento("kiro.regra_aplicada", {"regra": decisao[1].nome[:80], "acao": decisao[0], "descricao": item["descricao"]})
            if decisao[0] == "negar":
                return rejeitar
            if decisao[0] == "aprovar" and not varre_segredo:
                return permitir
        perguntar_sempre = (decisao is not None and decisao[0] == "perguntar") or alem_do_escopo or varre_segredo
        livre = item.get("forja") in FORJA_LIVRES or (self.leitura_consulta_livre and item.get("forja") == "forja_executar_ferramenta")
        if decisao is None and item.get("categoria") == "ferramenta_forja" and livre:  # estudo: ferramentas de leitura da Forja tambem
            self.ctl.evento("kiro.permissao_automatica", {"nivel": self.perfil.nivel, "categoria": "ferramenta_forja",
                                                          "descricao": item["descricao"], "motivo": "segundo cérebro/caderno pela API da Forja"})
            return permitir
        if item.get("fora_do_workspace"):  # fora das pastas do projeto: preferencia 'acesso_fora_pasta' (ADR-027)
            if self.fora_da_pasta == "bloquear":
                self.ctl.evento("kiro.permissao_negada_automatica", {"motivo": "fora das pastas do projeto (Configurações > Segurança)",
                                                                     "descricao": item["descricao"]})
                return rejeitar
            leitura = item.get("categoria") == "ler" and not varre_segredo
            citado = leitura and bool(item.get("alvos")) and all(dentro_de_citado(a, self.citados) for a in item["alvos"])
            if leitura and not perguntar_sempre and (citado or self.fora_da_pasta == "livre_leitura"):
                self.ctl.evento("kiro.permissao_automatica", {"nivel": self.perfil.nivel, "categoria": "ler", "descricao": item["descricao"],
                                                              "motivo": "pasta citada no pedido" if citado else "leitura fora da pasta liberada"})
                return permitir
        if not perguntar_sempre and self.perfil.aprova_sozinho(item):  # auditavel: toda aprovacao automatica vira evento
            self.ctl.evento("kiro.permissao_automatica", {"nivel": self.perfil.nivel, "categoria": item["categoria"], "descricao": item["descricao"]})
            return permitir
        if not perguntar_sempre and self._chave(item) in self._lembradas:
            self.ctl.evento("kiro.permissao_reutilizada", {"descricao": item["descricao"]})
            return permitir
        return permitir if self._perguntar(item) else rejeitar

    def _perguntar(self, item: dict[str, Any]) -> bool:
        with self._mu:
            lider = self._lote is None
            if lider:
                self._lote = _Lote()
            lote = self._lote
            assert lote is not None
            lote.itens.append(item)
        if lider:
            time.sleep(self.janela)  # coleta pedidos concorrentes
            with self._mu:
                self._lote = None  # fecha o lote; novos pedidos abrem outro
            try:
                self.perguntas += 1
                decisao = self.ctl.solicitar_aprovacao(lote.itens)
                lote.aprovados = set(decisao.get("aprovados", []))
                lote.lembrar = bool(decisao.get("lembrar"))
                if decisao.get("adendo"):
                    self.adendos.append(str(decisao["adendo"]))
                if lote.lembrar:
                    self._lembradas.update(self._chave(i) for i in lote.itens if i["id"] in lote.aprovados)
            except Exception:  # noqa: BLE001 - falha ao perguntar = negar
                log.exception("falha ao solicitar aprovacao; negando grupo")
                lote.aprovados = set()
            finally:
                lote.pronto.set()
        else:
            lote.pronto.wait(timeout=self.espera_max)
        return item["id"] in lote.aprovados
