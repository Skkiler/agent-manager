"""Assistente de linha de comando do painel (estilo Excel): explica cada parte, aponta erros de tipo (ex.: opcao que espera
inteiro), classifica o risco (pede confirmacao no que e perigoso) e sugere como completar o comando.

O catalogo padrao (`catalogo.json`, versionado) e mesclado com o do usuario (`<dados>/comandos_usuario.json`, fora do Git), que
pode ser preenchido a mao ou por uma IA (revisado pelo usuario antes de valer). Tudo deterministico: nenhuma chamada de modelo.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from forja.dominio.erros import ValidacaoDominio

CATALOGO_PADRAO = Path(__file__).with_name("catalogo.json")
ORDEM_RISCO = {"baixo": 0, "medio": 1, "alto": 2}
Risco = Literal["baixo", "medio", "alto"]
TipoValor = Literal["texto", "inteiro", "porta", "portas", "escolha", "caminho", "url", "ramo", "remoto", "imagem", "container"]
Curto = Annotated[str, StringConstraints(max_length=300)]
Longo = Annotated[str, StringConstraints(max_length=2000)]


class _M(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Opcao(_M):
    nomes: list[Annotated[str, StringConstraints(min_length=1, max_length=40)]] = Field(min_length=1, max_length=6)
    descricao: Longo = ""
    valor: TipoValor | None = None
    opcoes: list[Curto] = Field(default_factory=list, max_length=60)
    risco: Risco | None = None
    motivo: Curto = ""
    interativo: bool = False
    reduz_risco: Risco | None = None


class Argumento(_M):
    nome: Annotated[str, StringConstraints(min_length=1, max_length=40)]
    tipo: TipoValor = "texto"
    descricao: Longo = ""
    obrigatorio: bool = False
    multiplos: bool = False


class Subcomando(_M):
    nome: Annotated[str, StringConstraints(min_length=1, max_length=40)]
    descricao: Longo = ""
    risco: Risco | None = None
    motivo: Curto = ""


class Exemplo(_M):
    linha: Longo
    explicacao: Longo = ""


class Comando(_M):
    id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")]
    programa: Annotated[str, StringConstraints(min_length=1, max_length=60)]
    aliases: list[Annotated[str, StringConstraints(max_length=40)]] = Field(default_factory=list, max_length=20)
    sub: list[Annotated[str, StringConstraints(max_length=40)]] = Field(default_factory=list, max_length=4)
    area: Annotated[str, StringConstraints(max_length=30)] = "terminal"
    resumo: Curto
    sintaxe: Longo = ""
    descricao: Longo = ""
    risco: Risco = "baixo"
    motivo: Curto = ""
    opcoes: list[Opcao] = Field(default_factory=list, max_length=120)
    argumentos: list[Argumento] = Field(default_factory=list, max_length=20)
    subcomandos: list[Subcomando] = Field(default_factory=list, max_length=60)
    exemplos: list[Exemplo] = Field(default_factory=list, max_length=20)
    origem: Literal["padrao", "usuario", "ia"] = "padrao"
    revisado: bool = True


class Variavel(_M):
    nome: Annotated[str, StringConstraints(pattern=r"^[a-z_][a-z0-9_]{0,39}$")]
    rotulo: Curto = ""
    tipo: TipoValor = "texto"
    padrao: Curto = ""


class Passo(_M):
    comando: Longo
    explicacao: Longo = ""


class Receita(_M):
    id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")]
    area: Annotated[str, StringConstraints(max_length=30)] = "terminal"
    titulo: Curto
    descricao: Longo = ""
    variaveis: list[Variavel] = Field(default_factory=list, max_length=20)
    passos: list[Passo] = Field(min_length=1, max_length=30)
    origem: Literal["padrao", "usuario", "ia"] = "padrao"


class Perigo(_M):
    padrao: Longo
    risco: Risco
    motivo: Curto


class Catalogo(_M):
    versao: int = 1
    comandos: list[Comando] = Field(default_factory=list)
    perigos: list[Perigo] = Field(default_factory=list)
    receitas: list[Receita] = Field(default_factory=list)


# ------------------------------------------------------------------ tokenizacao
_SEPARADORES = re.compile(r"(;|&&|\|\||\|)")


def tokenizar(linha: str) -> list[tuple[str, int, int]]:
    """Tokens (texto sem aspas, inicio, fim) respeitando aspas simples e duplas. Separadores (; && || |) viram tokens proprios."""
    tokens: list[tuple[str, int, int]] = []
    i, n = 0, len(linha)
    while i < n:
        if linha[i].isspace():
            i += 1
            continue
        m = _SEPARADORES.match(linha, i)
        if m:
            tokens.append((m.group(1), i, m.end()))
            i = m.end()
            continue
        ini, partes = i, []
        while i < n and not linha[i].isspace() and not _SEPARADORES.match(linha, i):
            if linha[i] in "\"'":
                q = linha[i]
                fim = linha.find(q, i + 1)
                fim = n if fim < 0 else fim
                partes.append(linha[i + 1:fim])
                i = min(n, fim + 1)
            else:
                partes.append(linha[i])
                i += 1
        tokens.append(("".join(partes), ini, i))
    return tokens


def _segmentos(tokens: list[tuple[str, int, int]]) -> list[list[tuple[str, int, int]]]:
    seg: list[list[tuple[str, int, int]]] = [[]]
    for t in tokens:
        if t[0] in (";", "&&", "||", "|"):
            seg.append([])
        else:
            seg[-1].append(t)
    return [s for s in seg if s]


def _maior(a: str, b: str | None) -> str:
    return a if b is None or ORDEM_RISCO[a] >= ORDEM_RISCO[b] else b


def _valido(tipo: str, valor: str, opcoes: list[str]) -> str | None:
    """Mensagem de erro se `valor` nao serve para `tipo` (None = ok)."""
    if not valor:
        return "valor vazio"
    if tipo == "inteiro" and not re.fullmatch(r"-?\d+", valor):
        return f"espera um número inteiro (recebeu '{valor[:30]}')"
    if tipo == "porta" and (not valor.isdigit() or not 1 <= int(valor) <= 65535):
        return f"espera uma porta entre 1 e 65535 (recebeu '{valor[:30]}')"
    if tipo == "portas":
        partes = valor.split(":")
        if len(partes) not in (2, 3) or not all(p.split("/")[0].isdigit() and 1 <= int(p.split("/")[0]) <= 65535 for p in partes[-2:]):
            return f"espera portas no formato host:container, cada uma entre 1 e 65535 (recebeu '{valor[:30]}')"
    if tipo == "escolha" and opcoes and valor.lower() not in {o.lower() for o in opcoes}:
        return f"valor '{valor[:30]}' fora das opções: {', '.join(opcoes[:12])}"
    if tipo == "url" and not re.match(r"(?i)^([a-z][a-z0-9+.-]*://|git@|[\w.-]+\.[a-z]{2,}(/|:|$)|\{)", valor):
        return f"não parece um endereço (URL): '{valor[:40]}'"
    return None


class Assistente:
    """Analise e sugestoes sobre o catalogo mesclado. Recarrega o arquivo do usuario quando ele muda (mtime)."""

    def __init__(self, dir_dados: Path | None = None) -> None:
        self.arq_usuario = (dir_dados / "comandos_usuario.json") if dir_dados else None
        self._mu = threading.Lock()
        self._mtime: float | None = -1.0
        self._padrao = Catalogo.model_validate(json.loads(CATALOGO_PADRAO.read_text(encoding="utf-8")))
        self._perigos = [(re.compile(p.padrao), p) for p in self._padrao.perigos]
        self.catalogo = self._padrao

    # -------------------------------------------------------------- catalogo
    def _usuario(self) -> Catalogo:
        if not self.arq_usuario or not self.arq_usuario.exists():
            return Catalogo()
        try:
            return Catalogo.model_validate(json.loads(self.arq_usuario.read_text(encoding="utf-8")))
        except (ValueError, ValidationError):
            return Catalogo()

    def atual(self) -> Catalogo:
        with self._mu:
            m = self.arq_usuario.stat().st_mtime if self.arq_usuario and self.arq_usuario.exists() else None
            if m != self._mtime:
                u = self._usuario()
                ids_c, ids_r = {c.id for c in u.comandos}, {r.id for r in u.receitas}
                self.catalogo = Catalogo(versao=self._padrao.versao, perigos=self._padrao.perigos,
                                         comandos=[c for c in self._padrao.comandos if c.id not in ids_c] + u.comandos,
                                         receitas=[r for r in self._padrao.receitas if r.id not in ids_r] + u.receitas)
                self._mtime = m
            return self.catalogo

    def salvar_usuario(self, comandos: list[Comando] | None = None, receitas: list[Receita] | None = None, remover: str | None = None) -> Catalogo:
        if not self.arq_usuario:
            raise ValidacaoDominio("sem pasta de dados para guardar comandos do usuario")
        with self._mu:
            u = self._usuario()
            for c in comandos or []:
                u.comandos = [x for x in u.comandos if x.id != c.id] + [c]
            for r in receitas or []:
                u.receitas = [x for x in u.receitas if x.id != r.id] + [r]
            if remover:
                u.comandos = [x for x in u.comandos if x.id != remover]
                u.receitas = [x for x in u.receitas if x.id != remover]
            if len(u.comandos) > 500 or len(u.receitas) > 200:
                raise ValidacaoDominio("limite de comandos do usuario atingido (500 comandos, 200 receitas)")
            self.arq_usuario.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.arq_usuario.with_suffix(".tmp")
            tmp.write_text(u.model_dump_json(indent=1, exclude_defaults=False), encoding="utf-8")
            tmp.replace(self.arq_usuario)
        return self.atual()

    # -------------------------------------------------------------- identificacao
    def _entradas(self, programa: str) -> list[Comando]:
        p = programa.lower().removesuffix(".exe")
        return [c for c in self.atual().comandos if c.programa.lower() == p or p in (a.lower().removesuffix(".exe") for a in c.aliases)]

    def _achar(self, palavras: list[str]) -> tuple[Comando | None, int]:
        """Entrada do catalogo que casa com o inicio do segmento (o `sub` mais longo vence). Devolve (comando, tokens consumidos)."""
        if not palavras:
            return None, 0
        melhor, consumidos = None, 0
        for c in self._entradas(palavras[0]):
            k = len(c.sub)
            if [w.lower() for w in palavras[1:1 + k]] == [s.lower() for s in c.sub] and (melhor is None or k > len(melhor.sub)):
                melhor, consumidos = c, 1 + k
        return melhor, consumidos

    # -------------------------------------------------------------- analise
    def analisar(self, linha: str) -> dict[str, Any]:
        linha = (linha or "")[:4000]
        segs = []
        risco_total = "baixo"
        motivos: list[str] = []
        for seg in _segmentos(tokenizar(linha)):
            r = self._analisar_segmento(seg)
            segs.append(r)
            risco_total = _maior(r["risco"], risco_total)
            motivos += r["motivos"]
        for rx, p in self._perigos:
            if rx.search(linha):
                risco_total = _maior(p.risco, risco_total)
                motivos.append(p.motivo)
        motivos = list(dict.fromkeys(m for m in motivos if m))
        return {"linha": linha, "segmentos": segs, "risco": risco_total, "motivos": motivos[:10],
                "erros": [e for s in segs for e in s["erros"]], "avisos": [a for s in segs for a in s["avisos"]],
                "precisa_confirmar": risco_total == "alto"}

    def _analisar_segmento(self, seg: list[tuple[str, int, int]]) -> dict[str, Any]:
        palavras = [t[0] for t in seg]
        cmd, usados = self._achar(palavras)
        partes: list[dict[str, Any]] = []
        erros: list[str] = []
        avisos: list[str] = []
        motivos: list[str] = []
        if cmd is None:
            partes.append({"texto": palavras[0], "ini": seg[0][1], "fim": seg[0][2], "tipo": "programa",
                           "explicacao": "Comando fora do catálogo da Forja (adicione em Comandos > Novo, ou peça à IA para documentar)."})
            return {"comando": None, "partes": partes, "erros": [], "avisos": [], "risco": "baixo", "motivos": [], "texto": " ".join(palavras)}
        risco = cmd.risco
        if cmd.risco != "baixo" and cmd.motivo:
            motivos.append(cmd.motivo)
        for i in range(usados):
            partes.append({"texto": seg[i][0], "ini": seg[i][1], "fim": seg[i][2], "tipo": "programa" if i == 0 else "sub",
                           "explicacao": cmd.resumo if i == usados - 1 else ""})
        restante = seg[usados:]
        if cmd.subcomandos and restante and not restante[0][0].startswith("-"):
            sub = next((s for s in cmd.subcomandos if s.nome.lower() == restante[0][0].lower()), None)
            if sub:
                partes.append({"texto": restante[0][0], "ini": restante[0][1], "fim": restante[0][2], "tipo": "sub", "explicacao": sub.descricao})
                if sub.risco:
                    risco = sub.risco if ORDEM_RISCO[sub.risco] > ORDEM_RISCO[risco] or sub.risco == "baixo" else risco
                    if sub.risco == "baixo":
                        motivos = []  # subcomando so de leitura (ex.: pip list): o motivo do programa nao vale
                    if sub.motivo:
                        motivos.append(sub.motivo)
                restante = restante[1:]
        reduzir: str | None = None
        args_pos: list[tuple[str, int, int]] = []
        i = 0
        so_argumentos = False
        while i < len(restante):
            texto, ini, fim = restante[i]
            if so_argumentos or not texto.startswith("-") or texto == "-" or re.fullmatch(r"-\d+", texto):
                args_pos.append(restante[i])
                i += 1
                continue
            nome, _, inline = texto.partition("=")
            op = next((o for o in cmd.opcoes if nome in o.nomes or nome.lower() in (n.lower() for n in o.nomes if n.startswith("-") and n[1:2].isupper())), None)
            if op is None and re.fullmatch(r"-[A-Za-z]{2,}", nome):  # -sb = -s -b
                letras = [next((o for o in cmd.opcoes if f"-{ch}" in o.nomes), None) for ch in nome[1:]]
                if all(letras) and not any(o.valor for o in letras):  # type: ignore[union-attr]
                    for o in letras:
                        risco, reduzir = self._aplicar(o, risco, reduzir, motivos, avisos)  # type: ignore[arg-type]
                    partes.append({"texto": texto, "ini": ini, "fim": fim, "tipo": "opcao",
                                   "explicacao": " + ".join(o.descricao for o in letras if o)})  # type: ignore[union-attr]
                    i += 1
                    continue
            if nome == "--" and not op:
                so_argumentos = True
                partes.append({"texto": texto, "ini": ini, "fim": fim, "tipo": "opcao", "explicacao": "Daqui em diante são caminhos/argumentos."})
                i += 1
                continue
            if op is None:
                partes.append({"texto": texto, "ini": ini, "fim": fim, "tipo": "desconhecido", "explicacao": "Opção fora do catálogo."})
                avisos.append(f"opção {nome} não está no catálogo de {cmd.programa} (confira com {cmd.programa} {' '.join(cmd.sub)} --help)".replace("  ", " "))
                i += 1
                continue
            risco, reduzir = self._aplicar(op, risco, reduzir, motivos, avisos)
            partes.append({"texto": texto, "ini": ini, "fim": fim, "tipo": "opcao", "explicacao": op.descricao})
            if op.valor:
                valor = inline
                if not inline:
                    if i + 1 < len(restante) and not (restante[i + 1][0].startswith("-") and op.valor != "inteiro"):
                        i += 1
                        valor = restante[i][0]
                        partes.append({"texto": valor, "ini": restante[i][1], "fim": restante[i][2], "tipo": "valor",
                                       "explicacao": f"valor de {nome} ({op.valor})"})
                    else:
                        erros.append(f"{nome} espera um valor ({_ROTULO_TIPO.get(op.valor, op.valor)})")
                if valor:
                    erro = _valido(op.valor, valor, op.opcoes)
                    if erro:
                        erros.append(f"{nome}: {erro}")
            i += 1
        defs = cmd.argumentos
        k = 0
        for texto, ini, fim in args_pos:
            if k >= len(defs):
                partes.append({"texto": texto, "ini": ini, "fim": fim, "tipo": "argumento", "explicacao": "argumento"})
                continue
            a = defs[k]
            partes.append({"texto": texto, "ini": ini, "fim": fim, "tipo": "argumento", "explicacao": f"{a.nome}: {a.descricao}"})
            erro = _valido(a.tipo, texto, [])
            if erro and a.tipo in ("inteiro", "porta", "url"):
                erros.append(f"{a.nome}: {erro}")
            if not a.multiplos:
                k += 1
        faltando = [a.nome for j, a in enumerate(defs) if a.obrigatorio and j >= len(args_pos)]
        if faltando:
            erros.append(f"falta {', '.join(faltando)}")
        if reduzir is not None:
            risco = reduzir if ORDEM_RISCO[reduzir] < ORDEM_RISCO[risco] else risco
            if risco == "baixo":
                motivos = []
        partes.sort(key=lambda p: p["ini"])
        return {"comando": {"id": cmd.id, "resumo": cmd.resumo, "sintaxe": cmd.sintaxe, "descricao": cmd.descricao, "origem": cmd.origem,
                            "revisado": cmd.revisado},
                "partes": partes, "erros": erros, "avisos": avisos, "risco": risco, "motivos": motivos, "texto": " ".join(palavras)}

    @staticmethod
    def _aplicar(op: Opcao, risco: str, reduzir: str | None, motivos: list[str], avisos: list[str]) -> tuple[str, str | None]:
        if op.risco:
            risco = _maior(op.risco, risco)
            if op.motivo:
                motivos.append(op.motivo)
        if op.reduz_risco:
            reduzir = op.reduz_risco
        if op.interativo:
            avisos.append(f"{op.nomes[0]} é interativo: não funciona no terminal do painel (use o terminal do seu computador)")
        return risco, reduzir

    # -------------------------------------------------------------- sugestoes
    def sugerir(self, linha: str, contexto: dict[str, list[str]] | None = None, limite: int = 12) -> dict[str, Any]:
        """Sugestoes para completar o ULTIMO token (ou o proximo, se a linha termina em espaco) + a assinatura do comando atual."""
        contexto = contexto or {}
        linha = (linha or "")[:4000]
        tokens = tokenizar(linha)
        segs = _segmentos(tokens)
        if not segs or (tokens and tokens[-1][0] in (";", "&&", "||", "|")):
            seg: list[tuple[str, int, int]] = []
        else:
            seg = segs[-1]
        novo = linha.endswith(" ") or not seg
        prefixo = "" if novo else seg[-1][0]
        anteriores = [t[0] for t in (seg if novo else seg[:-1])]
        itens: list[dict[str, str]] = []
        if not anteriores:  # nome do programa
            vistos: set[str] = set()
            por_programa: dict[str, list[Comando]] = {}
            for c in self.atual().comandos:
                por_programa.setdefault(c.programa.lower(), []).append(c)
            for c in self.atual().comandos:
                irmaos = por_programa[c.programa.lower()]
                geral = (c.resumo if len(irmaos) == 1 and not c.sub
                         else f"{len(irmaos)} comando(s) no catálogo: " + ", ".join(" ".join(x.sub) or x.programa for x in irmaos[:6]))
                for nome in [c.programa, *c.aliases]:
                    if nome.lower().startswith(prefixo.lower()) and nome.lower() not in vistos:
                        vistos.add(nome.lower())
                        itens.append({"texto": nome, "rotulo": nome, "descricao": geral if nome == c.programa else f"apelido de {c.programa}", "tipo": "programa"})
            return {"itens": sorted(itens, key=lambda x: (len(x["texto"]), x["texto"].lower()))[:limite], "assinatura": None, "prefixo": prefixo}
        cmd, usados = self._achar(anteriores)
        programa = anteriores[0]
        if cmd is None or (usados == 1 and len(anteriores) == 1):
            # subcomandos possiveis do programa
            vistos = set()
            for c in self._entradas(programa):
                if c.sub and len(anteriores) == 1:
                    s = c.sub[0]
                    if s.lower().startswith(prefixo.lower()) and s.lower() not in vistos:
                        vistos.add(s.lower())
                        itens.append({"texto": s, "rotulo": s, "descricao": c.resumo, "tipo": "sub"})
            if itens:
                return {"itens": sorted(itens, key=lambda x: x["texto"])[:limite], "assinatura": None, "prefixo": prefixo}
        if cmd is None:
            return {"itens": [], "assinatura": None, "prefixo": prefixo}
        assinatura = {"sintaxe": cmd.sintaxe, "resumo": cmd.resumo, "id": cmd.id}
        resto = anteriores[usados:]
        if cmd.subcomandos and not resto and not prefixo.startswith("-"):
            itens += [{"texto": s.nome, "rotulo": s.nome, "descricao": s.descricao, "tipo": "sub", "risco": s.risco or ""}
                      for s in cmd.subcomandos if s.nome.lower().startswith(prefixo.lower())]
        # valor esperado pela opcao anterior?
        if resto:
            ult = resto[-1].partition("=")[0]
            op = next((o for o in cmd.opcoes if ult in o.nomes), None)
            if op and op.valor and "=" not in resto[-1]:
                valores = op.opcoes or contexto.get({"ramo": "ramos", "remoto": "remotos", "container": "containers", "imagem": "imagens"}.get(op.valor, ""), [])
                assinatura["parametro"] = f"{ult}: {op.descricao} ({_ROTULO_TIPO.get(op.valor, op.valor)})"
                return {"itens": [{"texto": v, "rotulo": v, "descricao": "", "tipo": "valor"} for v in valores if v.lower().startswith(prefixo.lower())][:limite],
                        "assinatura": assinatura, "prefixo": prefixo}
        usadas = {n for t in resto for o in cmd.opcoes if t.partition("=")[0] in o.nomes for n in o.nomes}
        if prefixo.startswith("-") or (not prefixo and not cmd.argumentos):
            for o in cmd.opcoes:
                if any(n in usadas for n in o.nomes):
                    continue
                nome = next((n for n in o.nomes if n.lower().startswith(prefixo.lower())), None)
                if nome:
                    itens.append({"texto": nome, "rotulo": ", ".join(o.nomes) + (f" <{_ROTULO_TIPO.get(o.valor, o.valor)}>" if o.valor else ""),
                                  "descricao": o.descricao, "tipo": "opcao", "risco": o.risco or ""})
        else:
            posicionais = [t for t in resto if not t.startswith("-")]
            a = cmd.argumentos[min(len(posicionais), len(cmd.argumentos) - 1)] if cmd.argumentos else None
            if a:
                assinatura["parametro"] = f"{a.nome}: {a.descricao}" + (" (obrigatório)" if a.obrigatorio else "")
                chave = {"ramo": "ramos", "remoto": "remotos", "container": "containers", "imagem": "imagens", "caminho": "arquivos"}.get(a.tipo, "")
                itens += [{"texto": v, "rotulo": v, "descricao": a.nome, "tipo": "valor"} for v in contexto.get(chave, []) if v.lower().startswith(prefixo.lower())]
            if not prefixo:
                itens += [{"texto": o.nomes[0], "rotulo": ", ".join(o.nomes), "descricao": o.descricao, "tipo": "opcao", "risco": o.risco or ""}
                          for o in cmd.opcoes if not any(n in usadas for n in o.nomes)][:6]
        return {"itens": itens[:limite], "assinatura": assinatura, "prefixo": prefixo}


_ROTULO_TIPO = {"inteiro": "número inteiro", "porta": "porta 1-65535", "escolha": "uma das opções", "caminho": "caminho", "url": "URL",
                "ramo": "branch", "remoto": "remoto", "imagem": "imagem", "container": "container", "texto": "texto"}


def montar_linha(programa: str, args: list[str]) -> str:
    """Linha legivel (para analise) a partir de argumentos ja separados."""
    return " ".join([programa, *[(f'"{a}"' if (not a or any(c.isspace() for c in a)) else a) for a in args]])
