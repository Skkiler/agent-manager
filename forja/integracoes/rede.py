"""Cliente HTTP restrito para integracoes: somente HTTPS, somente o host configurado. Leitura por GET; escrita (POST/PATCH) so
existe para acoes ja APROVADAS pelo operador (ver orquestracao/acoes_externas) e com corpo JSON limitado.

Defesas (todas testadas): host unico (allowlist), sem credenciais na URL, sem redirecionamentos, DNS resolvido e checado contra
enderecos nao publicos (SSRF) com o IP FIXADO na conexao (evita DNS rebinding; SNI/certificado validados pelo nome do host),
timeouts, teto de bytes da resposta e erros que nunca carregam URL, cabecalhos ou corpo. O segredo so existe no momento da chamada.
"""

from __future__ import annotations

import ipaddress
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from forja.dominio.erros import ErroDominio, ValidacaoDominio

MAX_BYTES = 2_000_000
MAX_CORPO = 64_000  # corpo de escrita (comentario, cartao): pequeno de proposito
METODOS_ESCRITA = ("POST", "PATCH", "PUT")
TIMEOUT_S = httpx.Timeout(15.0, connect=5.0)
Resolvedor = Callable[[str, int], list[str]]


class ErroRede(ErroDominio):
    codigo = "erro_rede"
    status = 502


class RedeBloqueada(ErroDominio):
    codigo = "rede_bloqueada"
    status = 403


class LimiteExcedido(ErroDominio):
    codigo = "limite_excedido"
    status = 429


def resolver_dns(host: str, porta: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, porta, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise ErroRede("nao foi possivel resolver o endereco do servico") from e
    return list(dict.fromkeys(i[4][0] for i in infos))


def ip_publico(texto: str) -> bool:
    ip = ipaddress.ip_address(texto)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def validar_base(base_url: str) -> tuple[str, int, str]:
    """(host, porta, prefixo_de_caminho) de uma URL base aceitavel; levanta ValidacaoDominio caso contrario."""
    u = urlsplit((base_url or "").strip())
    if u.scheme != "https":
        raise ValidacaoDominio("a URL precisa usar https")
    if u.username or u.password:
        raise ValidacaoDominio("a URL nao pode conter usuario ou senha")
    if not u.hostname or u.query or u.fragment:
        raise ValidacaoDominio("URL invalida (sem host, ou com query/fragmento)")
    try:
        porta = u.port or 443
    except ValueError as e:
        raise ValidacaoDominio("porta invalida") from e
    try:
        ipaddress.ip_address(u.hostname)
        raise ValidacaoDominio("use o nome do servidor, nao um IP (o certificado e validado pelo nome)")
    except ValueError:
        pass
    return u.hostname.lower(), porta, u.path.rstrip("/")


@dataclass
class Resposta:
    status: int
    texto: str
    bytes: int
    ms: float

    def json(self) -> Any:
        import json

        try:
            return json.loads(self.texto)
        except ValueError as e:
            raise ErroRede("o servico devolveu uma resposta que nao e JSON") from e


class ClienteSeguro:
    def __init__(
        self,
        base_url: str,
        *,
        cabecalhos: Callable[[], dict[str, str]] = dict,
        permitir_rede_privada: bool = False,
        resolver: Resolvedor = resolver_dns,
        transporte: httpx.BaseTransport | None = None,
        max_bytes: int = MAX_BYTES,
    ) -> None:
        self.host, self.porta, self.prefixo = validar_base(base_url)
        self._cabecalhos = cabecalhos
        self.permitir_rede_privada = permitir_rede_privada
        self._resolver = resolver
        self._transporte = transporte
        self.max_bytes = max_bytes
        self.recurso = ""  # caminho padrao opcional (ex.: endereco .ics secreto); nunca e registrado

    def _alvo(self) -> str:
        enderecos = self._resolver(self.host, self.porta)
        if not enderecos:
            raise ErroRede("nao foi possivel resolver o endereco do servico")
        if not self.permitir_rede_privada and not all(ip_publico(e) for e in enderecos):
            raise RedeBloqueada("o endereco do servico nao e publico (rede privada/local bloqueada nas configuracoes)")
        return enderecos[0]

    def get(self, caminho: str, params: dict[str, Any] | None = None) -> Resposta:
        return self._requisitar("GET", caminho, params, None)

    def enviar(self, metodo: str, caminho: str, corpo: Any, params: dict[str, Any] | None = None, formulario: bool = False) -> Resposta:
        """Corpo JSON (ou formulario). Usado por leituras que a API exige via POST (ex.: consulta do Notion) e pelas escritas,
        que so chegam aqui depois de aprovadas (a regra fica no servico de acoes externas, nao neste cliente)."""
        if metodo not in METODOS_ESCRITA:
            raise ValidacaoDominio("metodo de escrita nao permitido")
        import json
        from urllib.parse import urlencode

        dados = (urlencode(corpo) if formulario else json.dumps(corpo, ensure_ascii=False)).encode("utf-8")
        if len(dados) > MAX_CORPO:
            raise ValidacaoDominio(f"conteudo acima do limite de {MAX_CORPO // 1000} KB")
        return self._requisitar(metodo, caminho, params, dados, "application/x-www-form-urlencoded" if formulario else "application/json")

    def _requisitar(self, metodo: str, caminho: str, params: dict[str, Any] | None, dados: bytes | None, tipo: str = "") -> Resposta:
        caminho_puro, _, consulta = caminho.partition("?")
        if consulta and params:
            raise ValidacaoDominio("use query na URL ou params, nao os dois")
        if not caminho_puro.startswith("/") or "//" in caminho_puro or ".." in caminho_puro.split("/") or "\\" in caminho_puro:
            raise ValidacaoDominio("caminho invalido")
        ip = self._alvo()
        ip_url = f"[{ip}]" if ":" in ip else ip
        url = f"https://{ip_url}:{self.porta}{self.prefixo}{caminho_puro}" + (f"?{consulta}" if consulta else "")
        cab = {"Host": self.host if self.porta == 443 else f"{self.host}:{self.porta}", "Accept": "application/json",
               "User-Agent": "forja-orquestrador"}
        if dados is not None:
            cab["Content-Type"] = tipo
        cab.update(self._cabecalhos())
        t0 = time.perf_counter()
        try:
            with httpx.Client(transport=self._transporte, timeout=TIMEOUT_S, follow_redirects=False, trust_env=False) as c:
                with c.stream(metodo, url, params=params, headers=cab, content=dados, extensions={"sni_hostname": self.host}) as r:
                    if 300 <= r.status_code < 400:
                        raise ErroRede("o servico respondeu com redirecionamento (nao seguido por seguranca)")
                    pedacos, total = [], 0
                    for p in r.iter_bytes():
                        total += len(p)
                        if total > self.max_bytes:
                            raise ErroRede("resposta acima do limite de tamanho")
                        pedacos.append(p)
                    status = r.status_code
        except ErroDominio:
            raise
        except httpx.TimeoutException as e:
            raise ErroRede("tempo esgotado ao falar com o servico") from e
        except httpx.HTTPError as e:  # TLS, conexao, protocolo: nunca repassar a mensagem (pode conter URL/IP)
            raise ErroRede("falha de conexao ou certificado com o servico") from e
        self._checar_status(status)
        return Resposta(status, b"".join(pedacos).decode("utf-8", errors="replace"), total, (time.perf_counter() - t0) * 1000)

    @staticmethod
    def _checar_status(status: int) -> None:
        if status in (401, 403):
            raise ErroRede(f"credencial recusada ou sem permissao no servico (HTTP {status})")
        if status == 404:
            raise ErroRede("recurso nao encontrado no servico (HTTP 404)")
        if status == 429:
            raise LimiteExcedido("o servico limitou as requisicoes (HTTP 429); tente mais tarde")
        if status >= 400:
            raise ErroRede(f"o servico respondeu com erro (HTTP {status})")
