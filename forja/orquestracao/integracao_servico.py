"""Integracoes de rede configuraveis: estado, prontidao, chamadas limitadas e auditadas.

Guarda no banco apenas configuracao NAO secreta (host, projetos permitidos, NOMES de variaveis). O valor do segredo e lido do
ambiente no instante da chamada e nunca e devolvido por API, gravado ou registrado. Tudo nasce DESLIGADO.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import ValidationError

from forja.adapters.sqlite import tabelas as T
from forja.adapters.sqlite.repositorio import RepositorioSqlite
from forja.dominio.erros import ConflitoVersao, NaoEncontrado, ValidacaoDominio
from forja.dominio.tempo import Relogio, RelogioSistema, iso
from forja.ferramentas.contrato import ResultadoFerramenta
from forja.integracoes import ambiente
from forja.integracoes.conectores import CONECTORES, Conector
from forja.integracoes.config import ConfigIntegracao
from forja.integracoes.rede import ErroRede, LimiteExcedido, Resolvedor, resolver_dns

PREFIXO_ID = "integracao."


class IntegracaoServico:
    def __init__(self, repo: RepositorioSqlite, relogio: Relogio | None = None, ler: Callable[[str], str | None] = ambiente.ler,
                 resolver: Resolvedor = resolver_dns, transporte: httpx.BaseTransport | None = None,
                 agora: Callable[[], float] = time.monotonic) -> None:
        self.repo, self.relogio, self._ler = repo, relogio or RelogioSistema(), ler
        self._resolver, self._transporte, self._agora = resolver, transporte, agora
        self._chamadas: dict[str, deque[float]] = {}
        self._mu = threading.Lock()

    # ------------------------------------------------------------------ configuracao
    def _conector(self, id_: str) -> Conector:
        c = CONECTORES.get(id_)
        if c is None:
            raise NaoEncontrado(f"integracao {id_!r} nao existe ou nao e configuravel")
        return c

    def _ler_cfg(self, id_: str) -> tuple[ConfigIntegracao, int]:
        with self.repo.leitura() as t:
            linha = t.obter(T.Configuracao, PREFIXO_ID + id_)
        if linha is None:
            return ConfigIntegracao(), 0
        return ConfigIntegracao.model_validate(linha["valor"]), linha["versao"]

    def estado(self, id_: str) -> dict[str, Any]:
        """Estado seguro para a API/tela: nunca contem valor de segredo, so se a variavel esta presente."""
        con = self._conector(id_)
        cfg, versao = self._ler_cfg(id_)
        variaveis = {nome: self._ler(nome) is not None for nome in con.usadas(cfg) if nome}
        faltando = [n for n, ok in variaveis.items() if not ok]
        configurada = bool(cfg.host_permitido)
        return {
            "id": id_, "versao": versao, "configuracao": cfg.model_dump(), "configurada": configurada,
            "variaveis": variaveis, "pronta": cfg.ativo and configurada and not faltando,
            "motivo": ("desligada" if not cfg.ativo else "nao configurada" if not configurada
                       else f"faltam variaveis no ambiente: {', '.join(faltando)}" if faltando else "pronta"),
            "campos": [c.__dict__ for c in con.campos],
        }

    def pronta(self, id_: str) -> bool:
        try:
            return bool(self.estado(id_)["pronta"])
        except NaoEncontrado:
            return False

    def salvar(self, id_: str, bruto: dict[str, Any], expected_version: int) -> dict[str, Any]:
        con = self._conector(id_)
        try:
            cfg = con.normalizar(ConfigIntegracao.model_validate(bruto))
        except ValidationError as e:
            partes = [f"{'.'.join(map(str, x['loc'])) or 'configuracao'}: {str(x['msg']).removeprefix('Value error, ')}" for x in e.errors()[:3]]
            raise ValidacaoDominio("; ".join(partes)[:400]) from e
        agora = iso(self.relogio.agora())
        with self.repo.escrita() as t:
            linha = t.obter(T.Configuracao, PREFIXO_ID + id_)
            atual = linha["versao"] if linha else 0
            if expected_version != atual:
                raise ConflitoVersao(f"A integracao mudou (versao {atual}); recarregue antes de salvar.")
            valor = cfg.model_dump()
            if linha is None:
                t.inserir(T.Configuracao, id=PREFIXO_ID + id_, valor=valor, versao=1, atualizado_em=agora)
            else:
                t.atualizar(T.Configuracao, PREFIXO_ID + id_, valor=valor, versao=atual + 1, atualizado_em=agora)
            t.emitir_evento("integracao.configurada", agora, {"integracao": id_, "ativo": cfg.ativo, "versao": atual + 1})
        return self.estado(id_)

    # ------------------------------------------------------------------ chamadas
    def _limitar(self, id_: str, cfg: ConfigIntegracao) -> None:
        agora = self._agora()
        with self._mu:
            fila = self._chamadas.setdefault(id_, deque())
            while fila and agora - fila[0] > 60:
                fila.popleft()
            if len(fila) >= cfg.limite_por_minuto:
                raise LimiteExcedido(f"limite de {cfg.limite_por_minuto} chamadas por minuto atingido para {id_}")
            fila.append(agora)

    def _auditar(self, id_: str, acao: str, ok: bool, ms: float) -> None:
        """Evento SO com metadados (integracao, acao, resultado, tempo): nunca parametros, URL ou conteudo."""
        with self.repo.escrita() as t:
            t.emitir_evento("integracao.chamada", iso(self.relogio.agora()), {"integracao": id_, "acao": acao, "ok": ok, "ms": round(ms)})

    def _preparar(self, id_: str) -> tuple[Conector, ConfigIntegracao]:
        con = self._conector(id_)
        e = self.estado(id_)
        if not e["pronta"]:
            raise ValidacaoDominio(f"integracao {id_!r} indisponivel: {e['motivo']}")
        return con, ConfigIntegracao.model_validate(e["configuracao"])

    def executar(self, id_: str, acao: str, params: dict[str, Any]) -> ResultadoFerramenta:
        con, cfg = self._preparar(id_)
        runner = getattr(con, acao, None)
        if acao.startswith("_") or acao in ("normalizar", "cliente", "testar", "host", "cabecalhos", "usadas") or not callable(runner):
            raise NaoEncontrado(f"acao {acao!r} nao existe em {id_}")
        self._limitar(id_, cfg)
        t0 = time.perf_counter()
        try:
            cliente = con.cliente(cfg, ler=self._ler, resolver=self._resolver, transporte=self._transporte)
            r = runner(cliente, cfg, **params)
        except Exception:
            self._auditar(id_, acao, False, (time.perf_counter() - t0) * 1000)
            raise
        self._auditar(id_, acao, True, (time.perf_counter() - t0) * 1000)
        return r

    def testar(self, id_: str) -> dict[str, Any]:
        """Chamada de leitura minima para validar rede, certificado e credencial. Nao devolve conteudo."""
        con, cfg = self._preparar(id_)
        self._limitar(id_, cfg)
        t0 = time.perf_counter()
        try:
            con.testar(con.cliente(cfg, ler=self._ler, resolver=self._resolver, transporte=self._transporte), cfg)
        except ErroRede as e:
            self._auditar(id_, "testar", False, (time.perf_counter() - t0) * 1000)
            return {"ok": False, "mensagem": e.mensagem, "codigo": e.codigo}
        except Exception as e:  # ErroDominio (bloqueio, validacao) devolve a mensagem de dominio; o resto e generico
            self._auditar(id_, "testar", False, (time.perf_counter() - t0) * 1000)
            return {"ok": False, "mensagem": getattr(e, "mensagem", "falha inesperada ao testar"), "codigo": getattr(e, "codigo", "erro")}
        ms = (time.perf_counter() - t0) * 1000
        self._auditar(id_, "testar", True, ms)
        return {"ok": True, "mensagem": "conexao e credencial validas", "ms": round(ms)}
