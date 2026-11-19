"""Catalogo de autocompletar de codigo por linguagem (ADR-027): funcoes, metodos, bibliotecas, tecnicas e padroes comuns.

Organizado em RAMOS (ex.: `python.pandas`, `csharp.linq`, `javascript.dom`, `css.layout`). Cada ramo diz quando vale
(`detectar`: expressoes testadas no arquivo; vazio = sempre) e traz itens com assinatura, explicacao e o texto a inserir
(trecho com `${campo}` e `${0}` = cursor). O painel filtra localmente (sem ir ao servidor a cada tecla).

Fontes, em ordem: padrao (versionado em `forja/assistente/codigo/*.json`) < usuario/IA (`<dados>/codigo_usuario.json`, fora do
Git). A IA pode criar um ramo novo (ex.: uma biblioteca) ou atualizar um ramo existente; o resultado chega marcado como nao
revisado e so entra quando o usuario importa. Nada aqui executa codigo.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from forja.adapters.sqlite import tabelas as T
from forja.dominio.contratos import ObjetivoIn, ProjetoIn, TarefaIn, TransicaoIn
from forja.dominio.erros import NaoEncontrado, ValidacaoDominio
from forja.dominio.estados import EstadoTarefa

PASTA = Path(__file__).with_name("codigo")
LINGUAGENS = ("python", "csharp", "javascript", "html", "css")
ALIAS_LINGUAGEM = {"typescript": "javascript", "scss": "css", "xml": "html"}
TIPOS = ("funcao", "metodo", "classe", "modulo", "propriedade", "palavra", "trecho", "tag", "atributo", "valor", "arroba", "constante")
_ID_RAMO = re.compile(r"^(python|csharp|javascript|html|css)\.[a-z0-9][a-z0-9_.-]{0,40}$")
_JSON = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)
PROJETO = "forja-codigo"
MAX_ITENS_RAMO = 400


class _Estrito(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ItemCodigo(_Estrito):
    rotulo: str = Field(min_length=1, max_length=80)
    tipo: Literal["funcao", "metodo", "classe", "modulo", "propriedade", "palavra", "trecho", "tag", "atributo", "valor", "arroba",
                  "constante"]
    assinatura: str = Field("", max_length=200)
    doc: str = Field("", max_length=400)
    inserir: str = Field("", max_length=1500)
    apos: list[str] = Field(default_factory=list, max_length=20)  # depois de "<alvo>." (modulo/objeto), "*" = qualquer membro
    origem: Literal["padrao", "usuario", "ia"] = "padrao"
    revisado: bool = True


class Ramo(_Estrito):
    id: str
    linguagem: Literal["python", "csharp", "javascript", "html", "css"]
    rotulo: str = Field(min_length=1, max_length=80)
    descricao: str = Field("", max_length=300)
    modulo: str = Field("", max_length=80)  # nome do modulo/biblioteca para resolver apelidos (import pandas as pd -> pd.)
    detectar: list[str] = Field(default_factory=list, max_length=10)
    itens: list[ItemCodigo] = Field(default_factory=list, max_length=MAX_ITENS_RAMO)
    origem: Literal["padrao", "usuario", "ia"] = "padrao"

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not _ID_RAMO.match(v):
            raise ValueError("id do ramo: <linguagem>.<nome> (ex.: python.pandas)")
        return v

    @field_validator("detectar")
    @classmethod
    def _regex(cls, v: list[str]) -> list[str]:
        for x in v:
            if len(x) > 200:
                raise ValueError("expressao de deteccao longa demais")
            try:
                re.compile(x)
            except re.error as e:
                raise ValueError(f"expressao de deteccao invalida: {e}") from e
        return v

    @model_validator(mode="after")
    def _linguagem_do_id(self) -> Ramo:
        if not self.id.startswith(self.linguagem + "."):
            raise ValueError(f"o id do ramo deve comecar com '{self.linguagem}.'")
        return self


def expandir_grupos(ramo: dict[str, Any]) -> list[dict[str, Any]]:
    """Formato compacto dos arquivos padrao: grupos com o mesmo tipo/apos e itens [rotulo, assinatura, doc, inserir?].
    Funcao/metodo sem `inserir` vira `rotulo(${0})`; os demais inserem o proprio rotulo."""
    itens = list(ramo.get("itens") or [])
    for g in ramo.get("grupos") or []:
        tipo, apos = g["tipo"], list(g.get("apos") or [])
        for x in g["itens"]:
            rotulo, assinatura, doc = x[0], (x[1] if len(x) > 1 else ""), (x[2] if len(x) > 2 else "")
            inserir = x[3] if len(x) > 3 else (f"{rotulo}(${{0}})" if tipo in ("funcao", "metodo") else "")
            itens.append({"rotulo": rotulo, "tipo": tipo, "assinatura": assinatura, "doc": doc, "inserir": inserir, "apos": apos})
    return itens


def linguagem_catalogo(linguagem: str) -> str | None:
    lng = ALIAS_LINGUAGEM.get(linguagem, linguagem)
    return lng if lng in LINGUAGENS else None


class CatalogoCodigo:
    def __init__(self, dados_dir: Path | None = None) -> None:
        self.arquivo = (dados_dir / "codigo_usuario.json") if dados_dir else None
        self._mu = threading.Lock()
        self._padrao = self._carregar_padrao()

    # ------------------------------------------------------------------ leitura
    @staticmethod
    def _carregar_padrao() -> dict[str, Ramo]:
        ramos: dict[str, Ramo] = {}
        for arq in sorted(PASTA.glob("*.json")):
            dados = json.loads(arq.read_text(encoding="utf-8"))
            for r in dados.get("ramos", []):
                ramo = Ramo.model_validate({**{k: v for k, v in r.items() if k != "grupos"}, "itens": expandir_grupos(r)})
                ramos[ramo.id] = ramo
        return ramos

    def _usuario(self) -> dict[str, Any]:
        if self.arquivo is None or not self.arquivo.is_file():
            return {"ramos": []}
        try:
            return json.loads(self.arquivo.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"ramos": []}

    def ramos(self) -> dict[str, Ramo]:
        """Padrao + usuario/IA. Ramo do usuario com o mesmo id ACRESCENTA itens (mesmo rotulo+apos substitui o do padrao)."""
        saida = {k: v.model_copy(deep=True) for k, v in self._padrao.items()}
        for bruto in self._usuario().get("ramos", []):
            try:
                r = Ramo.model_validate(bruto)
            except ValidationError:
                continue  # arquivo editado a mao com erro: ignora so aquele ramo
            if r.id not in saida:
                saida[r.id] = r
                continue
            base = saida[r.id]
            chave = {(i.rotulo, tuple(i.apos)): n for n, i in enumerate(base.itens)}
            for it in r.itens:
                k = (it.rotulo, tuple(it.apos))
                if k in chave:
                    base.itens[chave[k]] = it
                else:
                    base.itens.append(it)
            base.detectar = list(dict.fromkeys([*base.detectar, *r.detectar]))[:10]
        return saida

    def resumo(self) -> list[dict[str, Any]]:
        return [{"id": r.id, "linguagem": r.linguagem, "rotulo": r.rotulo, "descricao": r.descricao, "modulo": r.modulo,
                 "detectar": r.detectar, "itens": len(r.itens), "origem": r.origem,
                 "nao_revisados": sum(1 for i in r.itens if not i.revisado)} for r in self.ramos().values()]

    def catalogo(self, linguagem: str, desligados: list[str] | None = None) -> dict[str, Any]:
        lng = linguagem_catalogo(linguagem)
        if lng is None:
            return {"linguagem": linguagem, "ramos": []}
        fora = set(desligados or [])
        return {"linguagem": lng, "ramos": [r.model_dump() for r in self.ramos().values() if r.linguagem == lng and r.id not in fora]}

    # ------------------------------------------------------------------ escrita (usuario/IA)
    def _gravar(self, dados: dict[str, Any]) -> None:
        if self.arquivo is None:
            raise ValidacaoDominio("sem pasta de dados para guardar o catalogo do usuario")
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.arquivo.with_suffix(".tmp")
        tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.arquivo)

    def salvar(self, ramo: Ramo, substituir: bool = False) -> Ramo:
        """Grava itens de usuario/IA num ramo (novo ou existente). substituir=True troca os itens de usuario/IA daquele ramo."""
        with self._mu:
            dados = self._usuario()
            lista = [x for x in dados.get("ramos", []) if isinstance(x, dict)]
            atual = next((x for x in lista if x.get("id") == ramo.id), None)
            novo = ramo.model_dump()
            if atual and not substituir:
                chave = {(i["rotulo"], tuple(i.get("apos") or [])): n for n, i in enumerate(atual.get("itens") or [])}
                itens = list(atual.get("itens") or [])
                for it in novo["itens"]:
                    k = (it["rotulo"], tuple(it["apos"]))
                    if k in chave:
                        itens[chave[k]] = it
                    else:
                        itens.append(it)
                atual.update({**{k: v for k, v in novo.items() if k != "itens"}, "itens": itens[:MAX_ITENS_RAMO]})
            elif atual:
                atual.clear()
                atual.update(novo)
            else:
                lista.append(novo)
            dados["ramos"] = lista
            self._gravar(dados)
        return self.ramos()[ramo.id]

    def remover_item(self, ramo_id: str, rotulo: str) -> None:
        with self._mu:
            dados = self._usuario()
            for r in dados.get("ramos", []):
                if r.get("id") == ramo_id:
                    antes = len(r.get("itens") or [])
                    r["itens"] = [i for i in r.get("itens") or [] if i.get("rotulo") != rotulo]
                    if len(r["itens"]) != antes:
                        self._gravar(dados)
                        return
        raise NaoEncontrado("so itens seus ou da IA podem ser removidos")

    def revisar(self, ramo_id: str) -> int:
        """Marca como revisados os itens da IA de um ramo."""
        with self._mu:
            dados = self._usuario()
            n = 0
            for r in dados.get("ramos", []):
                if r.get("id") == ramo_id:
                    for i in r.get("itens") or []:
                        if not i.get("revisado", True):
                            i["revisado"] = True
                            n += 1
            if not n:
                raise NaoEncontrado("nada para revisar neste ramo")
            self._gravar(dados)
            return n


FORMATO = """Formato (JSON, chaves em portugues):
{"ramos": [{"id": "<linguagem>.<nome>", "linguagem": "python|csharp|javascript|html|css", "rotulo": "<nome curto>",
  "descricao": "<1 frase>", "modulo": "<nome do import/pacote, se for biblioteca>",
  "detectar": ["<regex que, achada no arquivo, liga o ramo; ex.: ^\\\\s*(import|from)\\\\s+polars>"],
  "itens": [{"rotulo": "<nome que o usuario digita>", "tipo": "funcao|metodo|classe|modulo|propriedade|palavra|trecho|tag|atributo|valor|arroba|constante",
             "assinatura": "<assinatura curta>", "doc": "<1-2 frases em portugues>",
             "inserir": "<texto inserido; ${campo} = campo a preencher, ${0} = cursor; vazio = rotulo + (${0}) para funcoes>",
             "apos": ["<modulo ou objeto antes do ponto, ex.: polars; '*' = depois de qualquer objeto; vazio = no inicio>"]}]}]}"""

REGRAS = """Regras:
- Base: documentacao oficial da linguagem/biblioteca (pode pesquisar na web se a ferramenta estiver disponivel). Nao leia arquivos de
  projetos do usuario nem segredos. Nao rode comandos que alterem nada.
- No maximo 80 itens por ramo, os mais usados primeiro. Inclua padroes e tecnicas comuns como "trecho" (ex.: context manager,
  async/await, tratamento de erro, teste), com ${campos} para preencher.
- Assinaturas reais (nomes e ordem dos parametros como na documentacao). Textos em portugues do Brasil, curtos e claros.
- Responda com UM bloco ```json``` com o objeto acima (pode haver texto antes, mas o bloco e o que sera importado)."""


class CodigoServico:
    """Pedidos a IA para criar ou atualizar ramos do catalogo, e importacao do resultado (sempre revisavel)."""

    def __init__(self, catalogo: CatalogoCodigo, servico: Any) -> None:
        self.catalogo = catalogo
        self.servico = servico

    def salvar_item(self, ramo_id: str, item: dict[str, Any], ramo_meta: dict[str, Any] | None = None) -> dict[str, Any]:
        ramos = self.catalogo.ramos()
        base = ramos.get(ramo_id)
        meta = {"id": ramo_id, "linguagem": ramo_id.split(".", 1)[0], "rotulo": ramo_id.split(".", 1)[-1], **(ramo_meta or {})}
        if base is not None:
            meta.update({"linguagem": base.linguagem, "rotulo": base.rotulo, "descricao": base.descricao, "modulo": base.modulo})
        try:
            ramo = Ramo.model_validate({**meta, "origem": "usuario" if base is None else base.origem,
                                        "itens": [{**item, "origem": "usuario", "revisado": True}]})
        except ValidationError as e:
            raise ValidacaoDominio("item invalido: " + "; ".join(f"{'.'.join(map(str, x['loc']))} {x['msg']}" for x in e.errors()[:5])) from e
        self.catalogo.salvar(ramo)
        return {"ramo": ramo_id, "rotulo": ramo.itens[0].rotulo}

    def pedir_ia(self, linguagem: str, ramo_id: str = "", pedido: str = "", executar: bool = True) -> dict[str, Any]:
        lng = linguagem_catalogo(linguagem)
        if lng is None:
            raise ValidacaoDominio(f"linguagem sem catalogo: use {', '.join(LINGUAGENS)}")
        pedido = " ".join((pedido or "").split())[:500]
        ramos = self.catalogo.ramos()
        if ramo_id and ramo_id not in ramos:
            raise NaoEncontrado(f"ramo {ramo_id} nao existe (deixe vazio para criar um novo)")
        if not ramo_id and not pedido:
            raise ValidacaoDominio("diga o que buscar (ex.: biblioteca polars, padroes de async) ou escolha um ramo para atualizar")
        existente = ramos.get(ramo_id) if ramo_id else None
        projeto = next(iter(self.servico.listar(T.Projeto, nome=PROJETO)), None)
        if projeto is None:
            projeto, _ = self.servico.criar_projeto(ProjetoIn(nome=PROJETO, descricao="Catalogo de autocompletar de codigo do editor"))
        alvo = f"o ramo {ramo_id}" if existente else f"um ramo novo de {lng}"
        objetivo, _ = self.servico.criar_objetivo(ObjetivoIn(projeto_id=projeto["id"], titulo=f"Autocompletar: {ramo_id or pedido}"[:200],
                                                             prioridade=4, criterios_sucesso=["Ramo valido para o autocompletar do editor"]))
        descricao = (f"Atualize {alvo} do catalogo de autocompletar de codigo do editor da Forja.\n"
                     + (f"Pedido do usuario: {pedido}\n" if pedido else "")
                     + (f"Ramo atual: {existente.rotulo} ({existente.descricao}). Itens ja existentes: "
                        f"{', '.join(i.rotulo for i in existente.itens[:120])}. Corrija o que estiver errado e acrescente o que falta; "
                        f"mantenha o id {ramo_id}.\n" if existente else "")
                     + "\n" + FORMATO + "\n\n" + REGRAS)
        tarefa, _ = self.servico.criar_tarefa(TarefaIn(
            objetivo_id=objetivo["id"], titulo=f"Autocompletar {lng}: {ramo_id or pedido}"[:200], descricao=descricao,
            criterios_aceite=["Um bloco ```json``` com a lista 'ramos' no formato pedido"], especialidade="documentacao",
            modo="analise", entrada={"codigo_assistente": {"linguagem": lng, "ramo": ramo_id}}))
        for destino in (EstadoTarefa.CLASSIFICADA, EstadoTarefa.PREPARADA):
            tarefa, _ = self.servico.transicionar(tarefa["id"], TransicaoIn(para=destino, expected_version=tarefa["versao_estado"]))
        execucao = None
        if executar:
            execucao = self.servico.criar_execucao(tarefa["id"])
            self.servico.iniciar_execucao(execucao["id"], "operador")
        return {"tarefa_id": tarefa["id"], "execucao_id": execucao["id"] if execucao else None}

    def importar(self, tarefa_id: str) -> dict[str, Any]:
        tarefa = self.servico.obter(T.Tarefa, tarefa_id)
        pedido = (tarefa.get("entrada") or {}).get("codigo_assistente")
        if not pedido:
            raise ValidacaoDominio("esta tarefa nao e um pedido de autocompletar de codigo")
        texto = ""
        for a in sorted(self.servico.listar(T.Artefato, tarefa_id=tarefa_id), key=lambda a: a.get("criado_em") or "", reverse=True):
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
        importados, recusados = [], []
        for bruto in (dados.get("ramos") or [])[:5]:
            if not isinstance(bruto, dict):
                continue
            if pedido.get("ramo"):
                bruto = {**bruto, "id": pedido["ramo"]}  # atualizar um ramo: o id e o pedido, nao o que a IA escreveu
            itens, ruins = [], 0
            for it in (bruto.get("itens") or [])[:MAX_ITENS_RAMO]:
                try:
                    itens.append(ItemCodigo.model_validate({**it, "origem": "ia", "revisado": False}))
                except (ValidationError, TypeError):
                    ruins += 1
            try:
                ramo = Ramo.model_validate({**{k: v for k, v in bruto.items() if k != "itens"}, "linguagem": pedido["linguagem"],
                                            "origem": "ia", "itens": [i.model_dump() for i in itens]})
            except (ValidationError, TypeError) as e:
                recusados.append(f"{bruto.get('id', '?')}: {str(e).splitlines()[0][:120]}")
                continue
            if not ramo.itens:
                recusados.append(f"{ramo.id}: nenhum item valido")
                continue
            self.catalogo.salvar(ramo)
            importados.append({"ramo": ramo.id, "itens": len(ramo.itens), "recusados": ruins})
        if not importados:
            raise ValidacaoDominio("nada aproveitavel na resposta da IA: " + "; ".join(recusados[:3]))
        return {"importados": importados, "recusados": recusados}
