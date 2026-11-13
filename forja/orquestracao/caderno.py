"""Caderno da tarefa e ficha de estado: contexto que fica FORA da janela do agente e e consultado sob demanda.

Pratica de mercado (context engineering, 2025-2026): limpar o que ja foi resolvido, guardar fora da janela e CONSULTAR em vez de
carregar sempre. O ACP nao deixa a Forja apagar mensagens de dentro da sessao do Kiro; por isso a Forja:
- da ao agente um caderno (MCP `forja_caderno_salvar/consultar`) para registrar o que ja resolveu, entendeu ou decidiu;
- anota sozinha o que observa (arquivos alterados, testes, decisoes do usuario);
- monta, sem LLM, a FICHA DE ESTADO (objetivo, criterios, caderno, arquivos, testes) usada quando a sessao e trocada por
  estar grande demais, e na retomada. O texto bruto nunca e apagado: continua no banco e nos artefatos.
"""

from __future__ import annotations

from typing import Any

from forja.adapters.sqlite import tabelas as T
from forja.adapters.sqlite.repositorio import RepositorioSqlite, Tx, novo_id
from forja.dominio.erros import NaoEncontrado, ValidacaoDominio
from forja.dominio.tempo import Relogio, RelogioSistema, iso
from forja.observabilidade.sanitizar import redigir_segredos, sanitizar_texto

TIPOS = ("resolvido", "decisao", "arquivo", "erro", "pendencia", "fato")
MAX_ITENS_POR_TAREFA = 300
MAX_TEXTO = 600
MAX_FICHA = 2400


class Caderno:
    def __init__(self, repo: RepositorioSqlite, relogio: Relogio | None = None) -> None:
        self.repo = repo
        self.relogio = relogio or RelogioSistema()

    def salvar(self, tarefa_id: str, tipo: str, texto: str, ref: str = "", origem: str = "agente",
               execucao_id: str | None = None) -> dict[str, Any]:
        if tipo not in TIPOS:
            raise ValidacaoDominio(f"tipo deve ser um de {', '.join(TIPOS)}")
        limpo = " ".join(sanitizar_texto(redigir_segredos(str(texto or ""))).split())[:MAX_TEXTO]
        if not limpo:
            raise ValidacaoDominio("texto vazio")
        with self.repo.escrita() as t:
            if t.obter(T.Tarefa, tarefa_id) is None:
                raise NaoEncontrado(f"Tarefa {tarefa_id} nao encontrada.")
            existentes = t.listar(T.CadernoItem, ordem=T.CadernoItem.criado_em, tarefa_id=tarefa_id, limite=MAX_ITENS_POR_TAREFA + 1)
            igual = next((i for i in existentes if i["tipo"] == tipo and i["texto"] == limpo), None)
            if igual:
                return igual  # idempotente: o agente repetir a mesma nota nao duplica
            if len(existentes) >= MAX_ITENS_POR_TAREFA:
                raise ValidacaoDominio(f"caderno cheio ({MAX_ITENS_POR_TAREFA} itens); consolide antes de registrar mais")
            return t.inserir(T.CadernoItem, id=novo_id("CAD"), tarefa_id=tarefa_id, execucao_id=execucao_id, tipo=tipo, texto=limpo,
                             ref=sanitizar_texto(str(ref or ""))[:200], origem=origem[:32], criado_em=iso(self.relogio.agora()))

    def listar(self, tarefa_id: str, q: str = "", tipo: str = "") -> list[dict[str, Any]]:
        with self.repo.leitura() as t:
            itens = t.listar(T.CadernoItem, ordem=T.CadernoItem.criado_em, tarefa_id=tarefa_id, limite=MAX_ITENS_POR_TAREFA)
        termo = q.casefold().strip()
        return [i for i in itens if (not tipo or i["tipo"] == tipo) and (not termo or termo in i["texto"].casefold() or termo in i["ref"].casefold())]

    # ------------------------------------------------------------------ ficha de estado (deterministica)
    def ficha(self, t: Tx, tarefa: dict[str, Any], execucao_id: str | None = None, limite: int = MAX_FICHA) -> str:
        itens = t.listar(T.CadernoItem, ordem=T.CadernoItem.criado_em, tarefa_id=tarefa["id"], limite=MAX_ITENS_POR_TAREFA)
        partes = [f"Objetivo: {sanitizar_texto(tarefa['titulo'])[:200]}"]
        crit = "; ".join(str(c)[:120] for c in (tarefa.get("criterios_aceite") or [])[:6])
        if crit:
            partes.append(f"Criterios: {crit}")
        rotulo = {"resolvido": "Ja resolvido", "decisao": "Decidido", "arquivo": "Arquivos entendidos", "erro": "Erros ja corrigidos",
                  "pendencia": "Pendente", "fato": "Fatos"}
        for tipo in ("decisao", "resolvido", "erro", "arquivo", "pendencia", "fato"):
            do_tipo = [i for i in itens if i["tipo"] == tipo][-8:]
            if do_tipo:
                partes.append(f"{rotulo[tipo]}:\n" + "\n".join(f"- {i['texto']}" + (f" ({i['ref']})" if i["ref"] else "") for i in do_tipo))
        if execucao_id:
            alterados, testes = [], ""
            for e in t.eventos_da_execucao(execucao_id, 3000):
                p = e["payload"] or {}
                if e["tipo"] == "kiro.ferramenta" and p.get("tipo") in ("edit", "delete", "move") and p.get("status") == "completed":
                    tit = " ".join(str(p.get("titulo") or "").split())[:80]
                    if tit and tit not in alterados:
                        alterados.append(tit)
                elif e["tipo"] == "kiro.testes_forja":
                    testes = f"testes da Forja {'passaram' if p.get('ok') else 'falharam'} ({p.get('falhas', 0)} falha(s))"
            if alterados:
                partes.append("Alteracoes ja feitas:\n" + "\n".join(f"- {a}" for a in alterados[-12:]))
            if testes:
                partes.append(f"Ultima verificacao: {testes}")
        texto = "\n".join(partes)
        return texto if len(texto) <= limite else texto[: limite - 1] + "…"
