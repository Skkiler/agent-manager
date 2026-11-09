"""Dominio da memoria (secao 9 da orientacao): tipos, estados epistemologicos, ontologia, namespaces e ACL.

Puro: sem I/O. Regras de validade vivem aqui para serem testadas sem banco.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from forja.dominio.erros import Conflito, ErroDominio, ValidacaoDominio


class AcessoNegado(ErroDominio):
    codigo = "acesso_negado"
    status = 403


class TipoMemoria(StrEnum):
    SEMANTICA = "semantica"
    PROCEDIMENTAL = "procedimental"
    EPISODICA = "episodica"
    ESTRUTURAL = "estrutural"
    DECISORIA = "decisoria"
    OPERACIONAL = "operacional"


class EstadoMemoria(StrEnum):
    CANDIDATO = "candidato"
    OBSERVADO = "observado"
    VERIFICADO = "verificado"
    VALIDADO = "validado"
    CONTESTADO = "contestado"
    OBSOLETO = "obsoleto"
    SUBSTITUIDO = "substituido"
    REVOGADO = "revogado"


M = EstadoMemoria
TRANSICOES_MEMORIA: dict[EstadoMemoria, frozenset[EstadoMemoria]] = {
    M.CANDIDATO: frozenset({M.OBSERVADO, M.VERIFICADO, M.CONTESTADO, M.SUBSTITUIDO, M.REVOGADO}),
    M.OBSERVADO: frozenset({M.VERIFICADO, M.CONTESTADO, M.OBSOLETO, M.SUBSTITUIDO, M.REVOGADO}),
    M.VERIFICADO: frozenset({M.VALIDADO, M.CONTESTADO, M.OBSOLETO, M.SUBSTITUIDO, M.REVOGADO}),
    M.VALIDADO: frozenset({M.CONTESTADO, M.OBSOLETO, M.SUBSTITUIDO, M.REVOGADO}),
    M.CONTESTADO: frozenset({M.OBSERVADO, M.VERIFICADO, M.OBSOLETO, M.SUBSTITUIDO, M.REVOGADO}),
    M.OBSOLETO: frozenset({M.REVOGADO}),
    M.SUBSTITUIDO: frozenset({M.REVOGADO}),
    M.REVOGADO: frozenset(),
}
# Estados que nao participam de recuperacao padrao nem de deteccao de conflito.
INATIVOS = frozenset({M.OBSOLETO, M.SUBSTITUIDO, M.REVOGADO})

# Ontologia inicial (secao 9.3)
NOS = frozenset({
    "Projeto", "Repositorio", "Branch", "Arquivo", "Simbolo", "Componente", "Tecnologia", "Portal", "Servico",
    "Endpoint", "Contrato", "RegraNegocio", "Decisao", "Procedimento", "Ferramenta", "Erro", "Causa", "Solucao",
    "Teste", "Evidencia", "Episodio", "Documento", "Versao",
})
ARESTAS = frozenset({
    "PERTENCE_A", "DEPENDE_DE", "IMPLEMENTA", "IMPORTA", "CHAMA", "VALIDA", "CAUSADO_POR", "CORRIGE",
    "DOCUMENTADO_EM", "REUTILIZAVEL_EM", "SUBSTITUI", "INCOMPATIVEL_COM", "BASEADO_EM", "OBSERVADO_EM", "VALIDO_PARA",
})
ESTADOS_ARESTA = frozenset({"candidato", "observado", "verificado", "validado", "contestado", "obsoleto"})

SENSIBILIDADES = ("publico", "pessoal", "empresa", "terceiros")
_NS_RE = re.compile(r"^(publico|pessoal|terceiros|empresa/[a-z0-9][a-z0-9._-]{0,40})(/[a-z0-9][a-z0-9._-]{0,40}){0,4}$")


def validar_namespace(ns: str) -> str:
    """Formato: publico|pessoal|terceiros|empresa/<id>, com sub-niveis opcionais (ex.: publico/demo-portal-x)."""
    if not isinstance(ns, str) or len(ns) > 200 or not _NS_RE.match(ns):
        raise ValidacaoDominio(
            "namespace invalido (use publico | pessoal | terceiros | empresa/<id>, com subniveis opcionais).")
    return ns


def sensibilidade_de(ns: str) -> str:
    return ns.split("/", 1)[0]


def namespace_dentro_de(ns: str, base: str) -> bool:
    return ns == base or ns.startswith(base + "/")


@dataclass(frozen=True)
class Principal:
    """Quem consulta. `namespaces` sao prefixos permitidos (ex.: 'publico', 'empresa/acme/projeto-x')."""

    id: str
    namespaces: frozenset[str] = field(default_factory=frozenset)

    def pode(self, ns: str) -> bool:
        return any(namespace_dentro_de(ns, base) for base in self.namespaces)

    def exigir(self, ns: str) -> None:
        if not self.pode(ns):
            raise AcessoNegado(f"Sem acesso ao namespace {ns!r}.")

    def filtrar(self, solicitados: list[str]) -> list[str]:
        """Interseccao ACL x pedido. Pedido fora da ACL e ERRO (nunca silenciosamente ampliado ou ignorado)."""
        if not solicitados:
            raise ValidacaoDominio("informe ao menos um namespace explicito.")
        for ns in solicitados:
            validar_namespace(ns)
            self.exigir(ns)
        return list(dict.fromkeys(solicitados))


def validar_transicao_memoria(atual: EstadoMemoria, destino: EstadoMemoria) -> None:
    if destino not in TRANSICOES_MEMORIA[atual]:
        raise Conflito(f"Transicao de memoria {atual.value} -> {destino.value} nao permitida.")
