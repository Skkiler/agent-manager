"""Ferramentas N0 de dados do projeto (somente leitura, sem rede, sem shell; saida redigida pelo contrato):

- `deps.listar`: dependencias declaradas em requirements*.txt, pyproject.toml, package.json, Cargo.toml, go.mod e
  composer.json (nome, versao/restricao, grupo) sem instalar nada nem consultar a rede;
- `json.consultar`: valor de um caminho (`a.b[0].c`, `*` em listas) num JSON/JSONL, sem abrir o arquivo inteiro no prompt;
- `tabela.resumir`: perfil de um CSV/TSV (colunas, tipos inferidos, vazios, minimo/maximo/media, valores mais comuns);
- `links.verificar`: links e imagens relativos quebrados em arquivos Markdown (arquivo:linha), sem acessar URLs externas.
"""

from __future__ import annotations

import csv
import io
import json
import re
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any

from forja.dominio.erros import ValidacaoDominio
from forja.ferramentas.caminhos import resolver_dentro
from forja.ferramentas.contrato import ResultadoFerramenta, montar
from forja.memoria.indexador import IGNORAR_DIRS
from forja.seguranca.sensiveis import caminho_sensivel

MAX_LER = 5 * 1024 * 1024
MAX_ARQUIVOS = 2000


def _ler(raiz: Path, caminho: str, limite: int = MAX_LER) -> tuple[Path, str]:
    real = resolver_dentro(raiz, caminho)
    if real.stat().st_size > limite:
        raise ValidacaoDominio(f"arquivo acima de {limite // 1_000_000} MB")
    dados = real.read_bytes()
    if b"\x00" in dados[:4096]:
        raise ValidacaoDominio("arquivo binario")
    return real, dados.decode("utf-8", errors="replace")


def _arquivos(base: Path, padroes: tuple[str, ...]) -> list[Path]:
    achados: list[Path] = []
    for padrao in padroes:
        for p in base.rglob(padrao):
            rel = p.relative_to(base)
            if any(parte in IGNORAR_DIRS or parte.startswith(".") and parte not in (".",) for parte in rel.parts[:-1]):
                continue
            if p.is_file() and not p.is_symlink() and not caminho_sensivel(rel.as_posix()):
                achados.append(p)
            if len(achados) >= MAX_ARQUIVOS:
                return achados
    return sorted(set(achados))


# ------------------------------------------------------------------ deps.listar
_REQ = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*(.*?)\s*(#.*)?$")


def _requirements(texto: str) -> list[dict[str, str]]:
    itens = []
    for linha in texto.splitlines():
        s = linha.strip()
        if not s or s.startswith(("#", "-r", "-c", "--", "-e", "git+", "http://", "https://")):
            continue
        m = _REQ.match(s.split(";")[0])
        if m:
            itens.append({"nome": m.group(1), "versao": (m.group(3) or "").strip() or "*"})
    return itens


def _pep508(spec: str) -> dict[str, str]:
    m = _REQ.match(spec.split(";")[0])
    return {"nome": m.group(1), "versao": (m.group(3) or "").strip() or "*"} if m else {"nome": spec, "versao": "*"}


def _deps_de(arq: Path, texto: str) -> tuple[str, list[dict[str, str]]]:
    nome = arq.name.lower()
    if nome.startswith("requirements") and nome.endswith(".txt"):
        grupo = "dev" if "dev" in nome or "test" in nome else "principal"
        return "pip", [{**d, "grupo": grupo} for d in _requirements(texto)]
    if nome == "pyproject.toml":
        t = tomllib.loads(texto)
        proj = t.get("project") or {}
        itens = [{**_pep508(d), "grupo": "principal"} for d in proj.get("dependencies") or []]
        for g, lista in (proj.get("optional-dependencies") or {}).items():
            itens += [{**_pep508(d), "grupo": g} for d in lista]
        for g, lista in (t.get("dependency-groups") or {}).items():
            itens += [{**_pep508(d), "grupo": g} for d in lista if isinstance(d, str)]
        poetry = ((t.get("tool") or {}).get("poetry") or {})
        for chave, grupo in (("dependencies", "principal"), ("dev-dependencies", "dev")):
            for n, v in (poetry.get(chave) or {}).items():
                if n.lower() != "python":
                    itens.append({"nome": n, "versao": v if isinstance(v, str) else str(v.get("version", "*")), "grupo": grupo})
        return "python", itens
    if nome == "package.json":
        t = json.loads(texto)
        itens = []
        for chave, grupo in (("dependencies", "principal"), ("devDependencies", "dev"), ("peerDependencies", "peer"), ("optionalDependencies", "opcional")):
            itens += [{"nome": n, "versao": str(v), "grupo": grupo} for n, v in (t.get(chave) or {}).items()]
        return "npm", itens
    if nome == "cargo.toml":
        t = tomllib.loads(texto)
        itens = []
        for chave, grupo in (("dependencies", "principal"), ("dev-dependencies", "dev"), ("build-dependencies", "build")):
            for n, v in (t.get(chave) or {}).items():
                itens.append({"nome": n, "versao": v if isinstance(v, str) else str((v or {}).get("version", "*")), "grupo": grupo})
        return "cargo", itens
    if nome == "go.mod":
        itens = []
        bloco = False
        for linha in texto.splitlines():
            s = linha.split("//")[0].strip()
            if s.startswith("require ("):
                bloco = True
                continue
            if bloco and s == ")":
                bloco = False
                continue
            partes = s.removeprefix("require ").split()
            if (bloco or s.startswith("require ")) and len(partes) >= 2:
                itens.append({"nome": partes[0], "versao": partes[1], "grupo": "principal"})
        return "go", itens
    if nome == "composer.json":
        t = json.loads(texto)
        itens = [{"nome": n, "versao": str(v), "grupo": "principal"} for n, v in (t.get("require") or {}).items()]
        itens += [{"nome": n, "versao": str(v), "grupo": "dev"} for n, v in (t.get("require-dev") or {}).items()]
        return "composer", itens
    return "", []


def listar_dependencias(raiz: Path, caminho: str = ".") -> ResultadoFerramenta:
    base = resolver_dentro(raiz, caminho, diretorio=True)
    manifestos = _arquivos(base, ("requirements*.txt", "pyproject.toml", "package.json", "Cargo.toml", "go.mod", "composer.json"))
    saida, avisos, linhas, bruto = [], [], [], 0
    for arq in manifestos[:60]:
        rel = arq.relative_to(base).as_posix()
        try:
            texto = arq.read_text(encoding="utf-8", errors="replace")
            bruto += len(texto)
            eco, itens = _deps_de(arq, texto)
        except (ValueError, tomllib.TOMLDecodeError, OSError) as e:
            avisos.append(f"{rel}: nao deu para ler ({type(e).__name__})")
            continue
        if not eco:
            continue
        sem_versao = [d["nome"] for d in itens if d["versao"] in ("*", "", "latest")]
        saida.append({"arquivo": rel, "ecossistema": eco, "dependencias": itens[:500], "sem_versao_fixa": sem_versao[:50]})
        linhas.append(f"{rel} ({eco}): {len(itens)} dependencia(s)" + (f"; sem versao fixa: {', '.join(sem_versao[:8])}" if sem_versao else ""))
        linhas += [f"  {d['grupo']}: {d['nome']} {d['versao']}" for d in itens[:40]]
    if not saida:
        linhas.append("nenhum manifesto de dependencias encontrado")
    return montar("deps.listar", "x" * bruto, "\n".join(linhas), {"manifestos": saida}, len(manifestos) > 60, avisos, bruto // 4)


# ------------------------------------------------------------------ json.consultar
_PASSO = re.compile(r"\.?([^.\[\]]+)|\[(\d+|\*)\]")


def _navegar(valor: Any, caminho: str) -> list[Any]:
    atuais = [valor]
    pos = 0
    caminho = caminho.strip().removeprefix("$")
    while pos < len(caminho):
        m = _PASSO.match(caminho, pos)
        if not m:
            raise ValidacaoDominio(f"caminho invalido perto de '{caminho[pos:pos + 20]}' (use a.b[0].c ou a[*].b)")
        pos = m.end()
        chave, indice = m.group(1), m.group(2)
        proximos: list[Any] = []
        for v in atuais:
            if chave is not None:
                if chave == "*" and isinstance(v, (list, dict)):
                    proximos += list(v.values()) if isinstance(v, dict) else list(v)
                elif isinstance(v, dict) and chave in v:
                    proximos.append(v[chave])
            elif indice == "*" and isinstance(v, list):
                proximos += v
            elif isinstance(v, list) and indice is not None and int(indice) < len(v):
                proximos.append(v[int(indice)])
        atuais = proximos
    return atuais


def _forma(v: Any, nivel: int = 0) -> Any:
    """Esqueleto do valor (chaves e tipos), para o agente entender a estrutura sem ler tudo."""
    if isinstance(v, dict):
        return {k: _forma(x, nivel + 1) for k, x in list(v.items())[:30]} if nivel < 3 else f"objeto({len(v)} chaves)"
    if isinstance(v, list):
        return [_forma(v[0], nivel + 1), f"... {len(v)} itens"] if v and nivel < 3 else f"lista({len(v)})"
    return type(v).__name__


def consultar_json(raiz: Path, caminho: str, consulta: str = "", limite: int = 20) -> ResultadoFerramenta:
    _real, texto = _ler(raiz, caminho)
    try:
        if caminho.lower().endswith((".jsonl", ".ndjson")):
            dado: Any = [json.loads(ln) for ln in texto.splitlines() if ln.strip()][:10000]
        else:
            dado = json.loads(texto)
    except json.JSONDecodeError as e:
        raise ValidacaoDominio(f"JSON invalido na linha {e.lineno}, coluna {e.colno}: {e.msg}") from e
    if not consulta.strip():
        forma = _forma(dado)
        resumo = json.dumps(forma, ensure_ascii=False, indent=1)[:4000]
        return montar("json.consultar", texto, f"estrutura de {caminho}:\n{resumo}", {"estrutura": forma}, len(resumo) >= 4000)
    achados = _navegar(dado, consulta)
    mostrar = achados[:max(1, min(limite, 200))]
    resumo = "\n".join(json.dumps(v, ensure_ascii=False)[:600] for v in mostrar) or "(nada nesse caminho)"
    return montar("json.consultar", texto, f"{consulta}: {len(achados)} valor(es)\n{resumo}", {"consulta": consulta, "total": len(achados), "valores": mostrar},
                  len(achados) > len(mostrar))


# ------------------------------------------------------------------ tabela.resumir
def _numero(s: str) -> float | None:
    t = s.strip().replace(" ", "")
    if not t:
        return None
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?|-?\d+,\d+", t):  # 1.234,56 (pt-BR)
        t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def resumir_tabela(raiz: Path, caminho: str, separador: str = "", max_linhas: int = 50000) -> ResultadoFerramenta:
    _real, texto = _ler(raiz, caminho)
    amostra = texto[:20000]
    if not separador:
        try:
            separador = csv.Sniffer().sniff(amostra, delimiters=",;\t|").delimiter
        except csv.Error:
            separador = "\t" if caminho.lower().endswith(".tsv") else ","
    leitor = csv.reader(io.StringIO(texto), delimiter=separador)
    try:
        cabecalho = next(leitor)
    except StopIteration as e:
        raise ValidacaoDominio("arquivo vazio") from e
    colunas = [{"nome": (c.strip() or f"coluna_{i + 1}")[:80], "vazios": 0, "numeros": [], "valores": Counter()} for i, c in enumerate(cabecalho)]
    linhas = 0
    irregulares = 0
    for linha in leitor:
        if linhas >= max_linhas:
            break
        linhas += 1
        if len(linha) != len(colunas):
            irregulares += 1
        for i, col in enumerate(colunas):
            v = linha[i] if i < len(linha) else ""
            if not v.strip():
                col["vazios"] += 1
                continue
            n = _numero(v)
            if n is not None:
                col["numeros"].append(n)
            if len(col["valores"]) < 5000 or v in col["valores"]:
                col["valores"][v[:60]] += 1
    perfil, resumo = [], [f"{caminho}: {linhas} linha(s), {len(colunas)} coluna(s), separador {separador!r}"
                         + (f", {irregulares} linha(s) com numero de colunas diferente" if irregulares else "")]
    for col in colunas:
        preenchidos = linhas - col["vazios"]
        nums = col["numeros"]
        tipo = "numero" if preenchidos and len(nums) >= 0.9 * preenchidos else "texto"
        p: dict[str, Any] = {"nome": col["nome"], "tipo": tipo, "vazios": col["vazios"], "distintos": len(col["valores"])}
        if tipo == "numero" and nums:
            p |= {"min": min(nums), "max": max(nums), "media": round(sum(nums) / len(nums), 4)}
        p["mais_comuns"] = col["valores"].most_common(5)
        perfil.append(p)
        extra = f" min {p['min']} max {p['max']} media {p['media']}" if "min" in p else f" comuns: {', '.join(str(v) for v, _ in p['mais_comuns'][:3])}"
        resumo.append(f"- {p['nome']} ({tipo}): {p['vazios']} vazio(s), {p['distintos']} distinto(s);{extra}")
    return montar("tabela.resumir", texto, "\n".join(resumo), {"linhas": linhas, "separador": separador, "colunas": perfil, "irregulares": irregulares},
                  linhas >= max_linhas)


# ------------------------------------------------------------------ links.verificar
_LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_ANCORA = re.compile(r"[^\w\- ]", re.UNICODE)


def _ancoras(texto: str) -> set[str]:
    return {_ANCORA.sub("", m.group(1).strip().lower()).replace(" ", "-") for m in re.finditer(r"(?m)^#{1,6}\s+(.+?)\s*#*\s*$", texto)}


def verificar_links(raiz: Path, caminho: str = ".") -> ResultadoFerramenta:
    base = resolver_dentro(raiz, caminho, diretorio=True)
    arquivos = _arquivos(base, ("*.md", "*.markdown"))
    quebrados, total, bruto = [], 0, 0
    cache: dict[Path, set[str]] = {}
    for arq in arquivos:
        try:
            texto = arq.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        bruto += len(texto)
        dentro_codigo = False
        for n, linha in enumerate(texto.splitlines(), start=1):
            if linha.lstrip().startswith("```"):
                dentro_codigo = not dentro_codigo
            if dentro_codigo:
                continue
            for m in _LINK.finditer(linha):
                alvo = m.group(1)
                if re.match(r"(?i)^(https?:|mailto:|tel:|data:|//)", alvo):
                    continue
                total += 1
                caminho_alvo, _, ancora = alvo.partition("#")
                destino = (arq.parent / caminho_alvo).resolve() if caminho_alvo else arq
                motivo = ""
                if caminho_alvo and not destino.exists():
                    motivo = "arquivo nao existe"
                elif ancora and destino.suffix.lower() in (".md", ".markdown") and destino.is_file():
                    if destino not in cache:
                        cache[destino] = _ancoras(destino.read_text(encoding="utf-8", errors="replace"))
                    if ancora.lower() not in cache[destino]:
                        motivo = f"ancora #{ancora} nao existe"
                if motivo:
                    quebrados.append({"arquivo": arq.relative_to(base).as_posix(), "linha": n, "link": alvo[:200], "motivo": motivo})
    resumo = [f"{len(arquivos)} arquivo(s) Markdown, {total} link(s) relativo(s), {len(quebrados)} quebrado(s)"]
    resumo += [f"{q['arquivo']}:{q['linha']}: {q['link']} ({q['motivo']})" for q in quebrados[:100]]
    return montar("links.verificar", "x" * bruto, "\n".join(resumo), {"quebrados": quebrados[:500], "links": total, "arquivos": len(arquivos)},
                  len(quebrados) > 100, [], bruto // 4)
