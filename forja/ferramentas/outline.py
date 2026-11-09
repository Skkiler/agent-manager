"""codigo.outline: estrutura de um arquivo (simbolos e linhas) sem devolver o conteudo."""

from __future__ import annotations

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
