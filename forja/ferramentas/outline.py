"""codigo.outline: estrutura de um arquivo (simbolos e linhas) sem devolver o conteudo."""

from __future__ import annotations

import re
from pathlib import Path

from forja.dominio.erros import ValidacaoDominio
from forja.ferramentas.caminhos import resolver_dentro
from forja.ferramentas.contrato import ResultadoFerramenta, montar
from forja.memoria.indexador import MAX_BYTES, analisar

MAX_SIMBOLOS = 200


def outline_arquivo(raiz: Path, caminho: str) -> ResultadoFerramenta:
    """`caminho` e relativo a `raiz` e nunca pode sair dela, ser link simbolico ou arquivo sensivel."""
    real = resolver_dentro(raiz, caminho)
    if real.stat().st_size > MAX_BYTES:
        raise ValidacaoDominio("arquivo acima do limite de tamanho")
    arq = analisar(raiz.resolve(), real)
    if arq is None:
        raise ValidacaoDominio("arquivo binario ou minificado")

    itens = [s for s in arq.simbolos if s.tipo != "import"]
    if not itens and real.suffix.lower() in (".css", ".scss", ".less"):  # CSS: seletores, @media e @keyframes viram o 'outline'
        return _outline_css(arq.caminho, arq.texto, arq.sha256)
    importados = len(arq.simbolos) - len(itens)
    truncado = len(itens) > MAX_SIMBOLOS
    linhas = [f"{arq.caminho} ({arq.linguagem}, {arq.texto.count(chr(10)) + 1} linhas, sha256 {arq.sha256[:12]})"]
    for s in itens[:MAX_SIMBOLOS]:
        # Python guarda so os argumentos em `assinatura` ("(self)"); os demais extratores guardam o texto inteiro.
        rotulo = s.nome + s.assinatura if s.assinatura.startswith("(") else (s.assinatura or s.nome)
        linhas.append(f"L{s.linha} {s.tipo} {rotulo}")
    if importados:
        linhas.append(f"({importados} imports omitidos)")
    avisos = [f"parse parcial: {arq.erro_parse}"] if arq.erro_parse else []
    if truncado:
        avisos.append(f"{len(itens) - MAX_SIMBOLOS} simbolos omitidos")
    dados = {
        "caminho": arq.caminho,
        "sha256": arq.sha256,
        "linguagem": arq.linguagem,
        "extrator": "ast" if arq.linguagem == "python" else "regex",
        "simbolos": [{"nome": s.nome, "tipo": s.tipo, "linha": s.linha} for s in itens[:MAX_SIMBOLOS]],
    }
    return montar("codigo.outline", arq.texto, "\n".join(linhas), dados, truncado, avisos)


_CSS_BLOCO = re.compile(r"^\s*([^{}/;@][^{};]{0,200}?|@(?:media|keyframes|supports|layer|font-face|container)[^{]{0,200}?)\s*\{")


def _outline_css(caminho: str, texto: str, sha: str) -> ResultadoFerramenta:
    itens = []
    for n, linha in enumerate(texto.splitlines(), start=1):
        m = _CSS_BLOCO.match(linha)
        if m:
            sel = " ".join(m.group(1).split())
            itens.append({"nome": sel[:120], "tipo": "regra" if not sel.startswith("@") else sel.split()[0][1:], "linha": n})
    truncado = len(itens) > MAX_SIMBOLOS
    linhas = [f"{caminho} (css, {texto.count(chr(10)) + 1} linhas, sha256 {sha[:12]})"]
    linhas += [f"L{i['linha']} {i['tipo']} {i['nome']}" for i in itens[:MAX_SIMBOLOS]]
    dados = {"caminho": caminho, "sha256": sha, "linguagem": "css", "extrator": "regex", "simbolos": itens[:MAX_SIMBOLOS]}
    return montar("codigo.outline", texto, "\n".join(linhas), dados, truncado, [f"{len(itens) - MAX_SIMBOLOS} regras omitidas"] if truncado else [])
