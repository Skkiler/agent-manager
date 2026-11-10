"""Politica de pastas das ferramentas de arquivo: ativacao, pastas PERMITIDAS e pastas PROIBIDAS.

Regras (todas testadas):
  * desligada por padrao (no codigo); o usuario liga e escolhe as pastas pela tela;
  * PROIBIDA vence PERMITIDA, em qualquer profundidade;
  * pastas PROTEGIDAS nunca podem ser liberadas por configuracao: os dados do proprio usuario da Forja (credenciais, banco,
    memoria) e qualquer `.git`;
  * a mesma checagem vale para caminhos pedidos e para percursos de diretorio (mapa, varredura, cofre), sem revelar se algo
    existe dentro de uma pasta proibida.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from forja.dominio.erros import ValidacaoDominio

MAX_PASTAS = 30


@dataclass(frozen=True)
class PoliticaPastas:
    ativa: bool = False
    permitidas: tuple[Path, ...] = ()
    proibidas: tuple[Path, ...] = ()
    mascarar_emails: bool = True  # e-mails sempre mascarados, mesmo que o agente peca os enderecos completos


_atual: ContextVar[PoliticaPastas | None] = ContextVar("politica_pastas", default=None)
_protegidas: list[Path] = []  # definido no startup: pasta de dados do usuario


def definir_protegidas(pastas: list[Path]) -> None:
    _protegidas[:] = [_real(p) for p in pastas]


@contextmanager
def aplicar(politica: PoliticaPastas) -> Iterator[None]:
    token = _atual.set(politica)
    try:
        yield
    finally:
        _atual.reset(token)


def _real(p: Path) -> Path:
    return Path(os.path.normcase(str(Path(p).expanduser().resolve())))


def _dentro(p: Path, base: Path) -> bool:
    return p == base or base in p.parents


def protegido(caminho: Path) -> bool:
    """Dentro de um `.git` ou dos dados do usuario: nunca acessivel por ferramenta, com qualquer configuracao."""
    r = _real(caminho)
    return ".git" in {parte.lower() for parte in r.parts} or any(_dentro(r, base) for base in _protegidas)


def proibido(caminho: Path) -> bool:
    """True se o caminho e protegido ou cai dentro de uma pasta proibida da politica em vigor (fora de ferramentas: so protegidas)."""
    if protegido(caminho):
        return True
    pol = _atual.get()
    if pol is None or not pol.proibidas:
        return False
    r = _real(caminho)
    return any(_dentro(r, _real(b)) for b in pol.proibidas)


def validar_pasta(texto: str, rotulo: str, *, deve_existir: bool = True) -> Path:
    """Valida uma pasta digitada pelo usuario. Levanta ValidacaoDominio com uma mensagem acionavel."""
    bruto = (texto or "").strip().strip('"')
    if not bruto or "\x00" in bruto:
        raise ValidacaoDominio(f"{rotulo}: informe um caminho")
    p = Path(bruto).expanduser()
    if not p.is_absolute():
        raise ValidacaoDominio(f"{rotulo}: use o caminho completo (ex.: C:\\Notas ou /home/voce/notas)")
    r = p.resolve()
    if r == Path(r.anchor):
        raise ValidacaoDominio(f"{rotulo}: nao e permitido liberar a raiz do disco inteira ({r.anchor})")
    if deve_existir and not r.is_dir():
        raise ValidacaoDominio(f"{rotulo}: a pasta nao existe ou nao e uma pasta")
    if protegido(r):
        raise ValidacaoDominio(f"{rotulo}: esta pasta e protegida (dados da propria Forja ou .git) e nunca pode ser liberada")
    return r


def validar_lista(textos: list[str], rotulo: str, *, deve_existir: bool = True) -> list[str]:
    if len(textos) > MAX_PASTAS:
        raise ValidacaoDominio(f"{rotulo}: no maximo {MAX_PASTAS} pastas")
    vistas: dict[str, None] = {}
    for t in textos:
        vistas.setdefault(str(validar_pasta(t, rotulo, deve_existir=deve_existir)), None)
    return list(vistas)
