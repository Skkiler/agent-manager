"""Comandos do usuario e documentacao de comandos por IA.

A IA so DOCUMENTA (explicacao, sintaxe, opcoes, tipos, riscos): o resultado chega como proposta (`revisado=False`) e o usuario
revisa antes de usar. Nada aqui executa comando. A tarefa criada e de analise (somente leitura) e o pedido nao leva dados do
projeto, so o nome do programa e o formato do catalogo.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from forja.adapters.sqlite import tabelas as T
from forja.assistente.comandos import Assistente, Comando, Receita
from forja.dominio.contratos import ObjetivoIn, ProjetoIn, TarefaIn, TransicaoIn
from forja.dominio.erros import NaoEncontrado, ValidacaoDominio
from forja.dominio.estados import EstadoTarefa

PROJETO = "forja-comandos"
_PROGRAMA = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,59}$")
_JSON = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)

FORMATO = """Formato (JSON, chaves em portugues):
{"comandos": [{"id": "<programa>.<sub>", "programa": "<executavel>", "aliases": [], "sub": ["<subcomando>"], "area": "git|docker|python|node|terminal|http|<outra>",
  "resumo": "<1 frase>", "sintaxe": "<uso>", "descricao": "<2-3 frases>", "risco": "baixo|medio|alto", "motivo": "<por que e arriscado, se for>",
  "opcoes": [{"nomes": ["-x", "--xis"], "descricao": "...", "valor": null|"texto|inteiro|porta|portas|escolha|caminho|url|ramo|remoto|imagem|container",
              "opcoes": ["<valores, se escolha>"], "risco": null|"medio|alto", "motivo": "", "interativo": false, "reduz_risco": null|"baixo"}],
  "argumentos": [{"nome": "...", "tipo": "texto|inteiro|caminho|url|...", "descricao": "...", "obrigatorio": false, "multiplos": false}],
  "subcomandos": [{"nome": "...", "descricao": "...", "risco": null|"medio|alto", "motivo": ""}],
  "exemplos": [{"linha": "...", "explicacao": "..."}]}],
 "receitas": [{"id": "<area>.<nome>", "area": "...", "titulo": "...", "descricao": "...", "variaveis": [{"nome": "snake_case", "rotulo": "...", "tipo": "texto", "padrao": "..."}],
  "passos": [{"comando": "<linha com {variavel}>", "explicacao": "..."}]}]}"""

REGRAS = """Regras:
- Documente o programa pedido com base na documentacao oficial e/ou na saida de `<programa> --help` (pode rodar SO o --help/--version,
  nada que altere arquivos). Nao leia arquivos do projeto nem segredos.
- Um item em "comandos" por subcomando importante (no maximo 15). Opcoes mais usadas (no maximo 15 por comando).
- risco "alto" para o que apaga, sobrescreve, publica ou reescreve historico; "medio" para o que altera arquivos/servicos; "baixo" para leitura.
- "valor" diz o TIPO esperado pela opcao (ex.: inteiro para contagens): o painel usa isso para apontar erros de digitacao.
- Ate 3 receitas (passo a passo) para tarefas comuns com esse programa, com {variaveis} configuraveis.
- Textos em portugues do Brasil, curtos e claros para quem nao e especialista.
- Responda com UM bloco ```json``` com o objeto acima (pode haver texto antes, mas o bloco e o que sera importado)."""


class AssistenteServico:
    def __init__(self, assistente: Assistente, servico: Any) -> None:
        self.assistente = assistente
        self.servico = servico

    # ------------------------------------------------------------------ comandos do usuario
    def salvar(self, comando: dict[str, Any] | None, receita: dict[str, Any] | None) -> dict[str, Any]:
        try:
            c = Comando.model_validate({**comando, "origem": "usuario", "revisado": True}) if comando else None
            r = Receita.model_validate({**receita, "origem": "usuario"}) if receita else None
        except ValidationError as e:
            raise ValidacaoDominio("comando invalido: " + "; ".join(f"{'.'.join(map(str, x['loc']))} {x['msg']}" for x in e.errors()[:5])) from e
        if not c and not r:
            raise ValidacaoDominio("informe um comando ou uma receita")
        self.assistente.salvar_usuario([c] if c else None, [r] if r else None)
        return {"comando": c.id if c else None, "receita": r.id if r else None}

    def remover(self, id_: str) -> dict[str, Any]:
        cat = self.assistente.atual()
        if not any(x.id == id_ and x.origem != "padrao" for x in [*cat.comandos, *cat.receitas]):
            raise NaoEncontrado("so comandos e receitas seus (ou da IA) podem ser removidos")
        self.assistente.salvar_usuario(remover=id_)
        return {"removido": id_}

    def revisar(self, id_: str) -> dict[str, Any]:
        c = next((x for x in self.assistente.atual().comandos if x.id == id_ and x.origem == "ia"), None)
        if c is None:
            raise NaoEncontrado("comando da IA nao encontrado")
        self.assistente.salvar_usuario([c.model_copy(update={"revisado": True})])
        return {"revisado": id_}

    # ------------------------------------------------------------------ IA documenta um programa
    def pedir_ia(self, programa: str, detalhe: str = "", executar: bool = True) -> dict[str, Any]:
        programa = (programa or "").strip()
        if not _PROGRAMA.match(programa):
            raise ValidacaoDominio("nome de programa invalido (ex.: kubectl, terraform, gh, poetry)")
        conhecidos = [c.id for c in self.assistente.atual().comandos if c.programa.lower() == programa.lower()]
        projeto = next(iter(self.servico.listar(T.Projeto, nome=PROJETO)), None)
        if projeto is None:
            projeto, _ = self.servico.criar_projeto(ProjetoIn(nome=PROJETO, descricao="Documentacao de comandos para o assistente do terminal"))
        objetivo, _ = self.servico.criar_objetivo(ObjetivoIn(projeto_id=projeto["id"], titulo=f"Documentar o comando {programa}", prioridade=4,
                                                             criterios_sucesso=["Entradas do catalogo validas para o assistente do terminal"]))
        descricao = (f"Documente o programa de linha de comando `{programa}` para o assistente do terminal da Forja "
                     f"(explicacao, autocompletar, erros de tipo e risco).\n"
                     + (f"Foco pedido pelo usuario: {detalhe.strip()[:500]}\n" if detalhe.strip() else "")
                     + (f"Ja existem no catalogo: {', '.join(conhecidos[:20])} (complete ou corrija).\n" if conhecidos else "")
                     + "\n" + FORMATO + "\n\n" + REGRAS)
        tarefa, _ = self.servico.criar_tarefa(TarefaIn(
            objetivo_id=objetivo["id"], titulo=f"Documentar comando: {programa}"[:200], descricao=descricao,
            criterios_aceite=["Um bloco ```json``` com a lista 'comandos' no formato pedido", "Riscos classificados (baixo/medio/alto)"],
            especialidade="documentacao", modo="analise", entrada={"comando_assistente": programa}))
        for destino in (EstadoTarefa.CLASSIFICADA, EstadoTarefa.PREPARADA):
            tarefa, _ = self.servico.transicionar(tarefa["id"], TransicaoIn(para=destino, expected_version=tarefa["versao_estado"]))
        execucao = None
        if executar:
            execucao = self.servico.criar_execucao(tarefa["id"])
            self.servico.iniciar_execucao(execucao["id"], "operador")
        return {"tarefa_id": tarefa["id"], "execucao_id": execucao["id"] if execucao else None}

    def importar(self, tarefa_id: str) -> dict[str, Any]:
        tarefa = self.servico.obter(T.Tarefa, tarefa_id)
        if not (tarefa.get("entrada") or {}).get("comando_assistente"):
            raise ValidacaoDominio("esta tarefa nao e um pedido de documentacao de comando")
        artefatos = sorted(self.servico.listar(T.Artefato, tarefa_id=tarefa_id), key=lambda a: a.get("criado_em") or "", reverse=True)
        texto = ""
        for a in artefatos:
            if str(a.get("nome", "")).endswith(".md"):
                texto = self.servico.obter_artefato(a["id"], com_conteudo=True).get("conteudo", "")
                if "```json" in texto:
                    break
        blocos = _JSON.findall(texto)
        if not blocos:
            raise ValidacaoDominio("a resposta da IA ainda nao tem um bloco ```json``` (a tarefa terminou?)")
        try:
            dados = json.loads(blocos[-1])
        except json.JSONDecodeError as e:
            raise ValidacaoDominio(f"o JSON da IA esta invalido (linha {e.lineno}): {e.msg}") from e
        comandos, receitas, recusados = [], [], []
        for item in (dados.get("comandos") or [])[:30]:
            try:
                comandos.append(Comando.model_validate({**item, "origem": "ia", "revisado": False}))
            except (ValidationError, TypeError) as e:
                recusados.append(f"{(item or {}).get('id', '?')}: {str(e).splitlines()[0][:120]}")
        for item in (dados.get("receitas") or [])[:5]:
            try:
                receitas.append(Receita.model_validate({**item, "origem": "ia"}))
            except (ValidationError, TypeError) as e:
                recusados.append(f"{(item or {}).get('id', '?')}: {str(e).splitlines()[0][:120]}")
        padrao = {c.id for c in self.assistente.atual().comandos if c.origem == "padrao"}
        comandos = [c.model_copy(update={"id": f"{c.id}.ia"}) if c.id in padrao else c for c in comandos]  # nunca troca o padrao
        if not comandos and not receitas:
            raise ValidacaoDominio("nada aproveitavel na resposta da IA: " + "; ".join(recusados[:3]))
        self.assistente.salvar_usuario(comandos, receitas)
        return {"comandos": [c.id for c in comandos], "receitas": [r.id for r in receitas], "recusados": recusados}
