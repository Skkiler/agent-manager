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
import re
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

    def permite(self, caminho: Path) -> bool:
        """Pasta dentro de uma permitida, fora das proibidas e das protegidas (dados do usuario, .git)."""
        if not self.ativa or protegido(caminho):
            return False
        r = _real(caminho)
        return any(_dentro(r, _real(b)) for b in self.permitidas) and not any(_dentro(r, _real(b)) for b in self.proibidas)


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


# ------------------------------------------------------------------ caminhos citados pelo usuario (ADR-027)
_CITADO = re.compile(r"(?<![\w/\\])(?:[A-Za-z]:[\\/]|~[\\/]|/(?=[\w.~-]))[^\s\"'<>|*?`,;()\[\]{}]*")
ACESSO_FORA = ("bloquear", "perguntar", "livre_leitura")


def caminhos_citados(texto: str, limite: int = 10) -> list[Path]:
    """Pastas/arquivos ABSOLUTOS que o usuario escreveu no pedido ("olhe C:\\dados\\relatorios"). Ler o que o usuario pediu
    explicitamente nao e o agente 'esticando': pode ser aprovado sem perguntar. So entram caminhos que existem, sem cara de
    segredo e fora das pastas protegidas (dados da Forja, .git)."""
    from forja.seguranca.sensiveis import caminho_sensivel

    saida: list[Path] = []
    for m in _CITADO.finditer(texto or ""):
        bruto = m.group(0).rstrip(".:!")
        if len(bruto) < 3:
            continue
        try:
            p = Path(bruto).expanduser()
            if not p.is_absolute() or not p.exists():
                continue
            r = p.resolve()
        except (OSError, RuntimeError, ValueError):
            continue
        if protegido(r) or caminho_sensivel(r.as_posix()) or r == Path(r.anchor) or r == Path.home().resolve():
            continue  # disco ou pasta pessoal inteiros nao contam como "pasta citada"
        if r not in saida:
            saida.append(r)
        if len(saida) >= limite:
            break
    return saida


def dentro_de_citado(caminho: str, citados: list[Path]) -> bool:
    if not citados or not caminho:
        return False
    try:
        r = _real(Path(caminho))
    except (OSError, RuntimeError, ValueError):
        return False
    return any(_dentro(r, _real(c)) for c in citados) and not protegido(r)
