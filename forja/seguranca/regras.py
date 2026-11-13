"""Regras de controle definidas pelo usuario para as acoes dos agentes (antes de cada ferramenta).

Cada regra casa por categoria da acao, trecho do comando/descricao e/ou padrao de caminho, e decide: negar, perguntar ou
aprovar. Quando varias casam, vale a MAIS restritiva (negar > perguntar > aprovar), independente da ordem.
Invariantes que nenhuma regra afrouxa: segredos/credenciais sao sempre negados; pastas de consulta sao so leitura; e
'aprovar' nunca vale para acao de risco alto/critico, fora da pasta de trabalho ou de categoria que sempre pergunta
(excluir, publicar, descartar alteracoes, instalar dependencias, acessar a rede, nao identificada). Regras so apertam ou
dispensam perguntas de acoes ja reversiveis.
"""

from __future__ import annotations

from fnmatch import fnmatch
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from forja.agentes.estilo import SEMPRE_PERGUNTA
from forja.dominio.erros import ValidacaoDominio

CATEGORIAS = ("qualquer", "ler", "modificar_arquivos", "executar_comando", "mover", "excluir", "excluir_forcado", "publicar",
              "descartar_alteracoes", "instalar_dependencias", "acessar_rede", "ferramenta_forja", "outra")
MAX_REGRAS = 30
_PESO = {"negar": 3, "perguntar": 2, "aprovar": 1}


class Regra(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    nome: Annotated[str, Field(min_length=1, max_length=80)]
    categoria: Literal[CATEGORIAS] = "qualquer"  # type: ignore[valid-type]
    comando_contem: Annotated[str, Field(max_length=120)] = ""
    caminho_glob: Annotated[str, Field(max_length=200)] = ""
    acao: Literal["negar", "perguntar", "aprovar"]
    ativa: bool = True

    def casa(self, item: dict[str, Any]) -> bool:
        if not self.ativa:
            return False
        if self.categoria != "qualquer" and item.get("categoria") != self.categoria:
            return False
        if self.comando_contem:
            texto = f"{item.get('descricao', '')} {item.get('tecnico', '')}".casefold()
            if self.comando_contem.casefold() not in texto:
                return False
        if self.caminho_glob:
            padrao = self.caminho_glob.replace("\\", "/").casefold()
            alvos = [str(a).replace("\\", "/").casefold() for a in item.get("alvos") or []]
            if not any(fnmatch(a, padrao) or fnmatch(a.rsplit("/", 1)[-1], padrao) for a in alvos):
                return False
        return bool(self.categoria != "qualquer" or self.comando_contem or self.caminho_glob)  # regra vazia nao casa tudo


def validar_regras(valor: Any) -> list[dict[str, Any]]:
    if not isinstance(valor, list):
        raise ValidacaoDominio("regras: informe uma lista")
    if len(valor) > MAX_REGRAS:
        raise ValidacaoDominio(f"regras: no maximo {MAX_REGRAS}")
    saida = []
    for i, bruto in enumerate(valor, start=1):
        try:
            r = Regra.model_validate(bruto)
        except ValidationError as e:
            erro = e.errors()[0]
            raise ValidacaoDominio(f"regra {i}: campo {'.'.join(map(str, erro.get('loc', [])))} invalido ({erro.get('msg', '')})") from None
        if not (r.categoria != "qualquer" or r.comando_contem or r.caminho_glob):
            raise ValidacaoDominio(f"regra {i} ('{r.nome}'): defina ao menos categoria, trecho do comando ou caminho")
        saida.append(r.model_dump())
    return saida


def carregar(valor: Any) -> tuple[Regra, ...]:
    """Valores ja validados (preferencia salva) -> regras. Item invalido e descartado (nunca derruba a execucao)."""
    regras = []
    for bruto in valor or []:
        try:
            regras.append(Regra.model_validate(bruto))
        except ValidationError:
            continue
    return tuple(regras)


def pode_aprovar(item: dict[str, Any]) -> bool:
    return not (item.get("sensivel") or item.get("fora_do_workspace") or item.get("em_consulta")
                or item.get("risco") in ("alto", "critico") or item.get("categoria", "outra") in SEMPRE_PERGUNTA)


def avaliar(regras: tuple[Regra, ...], item: dict[str, Any]) -> tuple[str, Regra] | None:
    """A decisao mais restritiva entre as regras que casam; 'aprovar' em acao protegida vira 'perguntar'."""
    casadas = [r for r in regras if r.casa(item)]
    if not casadas:
        return None
    r = max(casadas, key=lambda x: _PESO[x.acao])
    if r.acao == "aprovar" and not pode_aprovar(item):
        return "perguntar", r
    return r.acao, r
