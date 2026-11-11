"""Preferencias do usuario: leitura, validacao, gravacao versionada e aplicacao imediata aos componentes em execucao."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from forja.adapters.sqlite import tabelas as T
from forja.adapters.sqlite.repositorio import RepositorioSqlite
from forja.agentes.estilo import PerfilTrabalho, validar_metodos, validar_observacoes
from forja.dominio.erros import ConflitoVersao, ValidacaoDominio
from forja.dominio.tempo import Relogio, RelogioSistema, iso
from forja.preferencias.registro import CATEGORIAS, EDITAVEIS, POR_ID, PREFERENCIAS, Preferencia
from forja.seguranca.pastas import PoliticaPastas, validar_lista

log = logging.getLogger("forja.preferencias")
CHAVE = "preferencias"
Aplicador = Callable[[Any], None]


def validar_valor(p: Preferencia, valor: Any) -> Any:
    """Normaliza e valida UM valor conforme o tipo declarado no registro. Levanta ValidacaoDominio com mensagem acionavel."""
    if p.tipo == "bool":
        if not isinstance(valor, bool):
            raise ValidacaoDominio(f"{p.rotulo}: use verdadeiro ou falso")
        return valor
    if p.tipo == "int":
        if isinstance(valor, bool) or not isinstance(valor, int):
            raise ValidacaoDominio(f"{p.rotulo}: informe um numero inteiro")
        if not (p.minimo or 0) <= valor <= (p.maximo or 10**9):
            raise ValidacaoDominio(f"{p.rotulo}: use um valor entre {p.minimo} e {p.maximo} {p.unidade}".strip())
        return valor
    if p.tipo == "selecao":
        if valor not in {v for v, _ in p.opcoes}:
            raise ValidacaoDominio(f"{p.rotulo}: escolha uma das opcoes ({', '.join(v for v, _ in p.opcoes)})")
        return valor
    if p.tipo == "tags":
        return validar_metodos(valor)
    if p.tipo == "texto":
        return validar_observacoes(valor)
    if p.tipo == "pastas":
        if not isinstance(valor, list) or not all(isinstance(x, str) for x in valor):
            raise ValidacaoDominio(f"{p.rotulo}: informe uma lista de caminhos")
        return validar_lista(valor, p.rotulo, deve_existir=p.id == "pastas_permitidas")
    raise ValidacaoDominio(f"{p.rotulo}: nao pode ser alterada aqui")


class PreferenciasServico:
    def __init__(self, repo: RepositorioSqlite, relogio: Relogio | None = None, sementes: dict[str, Any] | None = None) -> None:
        self.repo, self.relogio = repo, relogio or RelogioSistema()
        self.sementes = dict(sementes or {})  # valores vindos do ambiente (ex.: APP_TOOLS_ROOTS) enquanto o usuario nao salvou
        self._aplicadores: dict[str, list[Aplicador]] = {}
        self._mu = threading.Lock()
        self._guardados: dict[str, Any] = {}
        self._versao = 0
        self._carregar()

    # ------------------------------------------------------------------ leitura
    def _carregar(self) -> None:
        with self.repo.leitura() as t:
            linha = t.obter(T.Configuracao, CHAVE)
        with self._mu:
            self._guardados = dict((linha or {}).get("valor") or {})
            self._versao = (linha or {}).get("versao", 0)

    def valor(self, id_: str) -> Any:
        with self._mu:
            if id_ in self._guardados:
                return self._guardados[id_]
        return self.sementes.get(id_, POR_ID[id_].padrao)

    def _fonte(self, id_: str) -> str:
        return "usuario" if id_ in self._guardados else "ambiente" if id_ in self.sementes else "padrao"

    def perfil_trabalho(self) -> PerfilTrabalho:
        return PerfilTrabalho(nivel=self.valor("nivel_autonomia"), metodos=tuple(self.valor("metodos_acao")),
                              observacoes=self.valor("observacoes_guia"), correcao=self.valor("correcao_automatica"),
                              testes_timeout_s=int(self.valor("testes_tempo_maximo")))

    def politica_pastas(self) -> PoliticaPastas:
        return PoliticaPastas(
            ativa=bool(self.valor("ferramentas_arquivos_ativas")),
            permitidas=tuple(Path(p) for p in self.valor("pastas_permitidas")),
            proibidas=tuple(Path(p) for p in self.valor("pastas_proibidas")),
            mascarar_emails=bool(self.valor("mascarar_enderecos_email")))

    def avisos(self) -> list[str]:
        """Combinacoes que funcionam mas provavelmente nao sao o que o usuario quer."""
        av = []
        ativa, perm, proib = self.valor("ferramentas_arquivos_ativas"), self.valor("pastas_permitidas"), self.valor("pastas_proibidas")
        if ativa and not perm:
            av.append("Leitura de arquivos ligada, mas nenhuma pasta permitida: as ferramentas de arquivo continuam indisponiveis.")
        if perm and not ativa:
            av.append("Ha pastas permitidas, mas a leitura de arquivos esta desligada.")
        for a in perm:
            for b in proib:
                if Path(a).resolve() == Path(b).resolve() or Path(b).resolve() in Path(a).resolve().parents:
                    av.append(f"A pasta permitida '{a}' esta dentro de uma proibida e ficara inacessivel (proibida vence).")
        return av

    def estado(self) -> dict[str, Any]:
        categorias = []
        for c in CATEGORIAS:
            itens = []
            for p in PREFERENCIAS:
                if p.categoria != c.id:
                    continue
                d = asdict(p)
                d["exemplos"] = list(d["exemplos"])  # asdict ja converteu os dataclasses aninhados
                d["opcoes"] = [list(o) for o in p.opcoes]
                d["valor"] = self.valor(p.id) if p.persistida else None
                d["fonte"] = self._fonte(p.id) if p.persistida else None
                itens.append(d)
            categorias.append({**asdict(c), "itens": itens})
        return {"versao": self._versao, "categorias": categorias, "avisos": self.avisos()}

    # ------------------------------------------------------------------ escrita
    def registrar_aplicador(self, id_: str, fn: Aplicador) -> None:
        self._aplicadores.setdefault(id_, []).append(fn)

    def aplicar_todos(self) -> None:
        """Aplica os valores atuais aos componentes (chamado na subida do servidor)."""
        for id_ in self._aplicadores:
            self._aplicar(id_)

    def _aplicar(self, id_: str) -> None:
        for fn in self._aplicadores.get(id_, []):
            try:
                fn(self.valor(id_))
            except Exception:  # noqa: BLE001 - uma preferencia mal aplicada nunca derruba o servidor
                log.exception("falha ao aplicar preferencia", extra={"preferencia": id_})

    def atualizar(self, mudancas: dict[str, Any], expected_version: int) -> dict[str, Any]:
        if not mudancas:
            raise ValidacaoDominio("nenhuma mudanca informada")
        validados: dict[str, Any] = {}
        for id_, valor in mudancas.items():
            if id_ not in EDITAVEIS:
                raise ValidacaoDominio(f"preferencia desconhecida ou nao editavel: {id_!r}")
            validados[id_] = validar_valor(POR_ID[id_], valor)
        return self._gravar(lambda atual: {**atual, **validados}, expected_version, list(validados))

    def restaurar(self, ids: list[str], expected_version: int) -> dict[str, Any]:
        for i in ids:
            if i not in EDITAVEIS:
                raise ValidacaoDominio(f"preferencia desconhecida: {i!r}")
        return self._gravar(lambda atual: {k: v for k, v in atual.items() if k not in ids}, expected_version, list(ids))

    def _gravar(self, transformar: Callable[[dict], dict], expected_version: int, ids: list[str]) -> dict[str, Any]:
        agora = iso(self.relogio.agora())
        with self.repo.escrita() as t:
            linha = t.obter(T.Configuracao, CHAVE)
            atual = linha["versao"] if linha else 0
            if expected_version != atual:
                raise ConflitoVersao(f"As preferencias mudaram (versao {atual}); recarregue antes de salvar.")
            valor = transformar(dict((linha or {}).get("valor") or {}))
            if linha is None:
                t.inserir(T.Configuracao, id=CHAVE, valor=valor, versao=1, atualizado_em=agora)
            else:
                t.atualizar(T.Configuracao, CHAVE, valor=valor, versao=atual + 1, atualizado_em=agora)
            t.emitir_evento("preferencias.atualizadas", agora, {"ids": ids, "versao": atual + 1})  # so ids: valores podem ser caminhos pessoais
        self._carregar()
        for i in ids:
            self._aplicar(i)
        return self.estado()
