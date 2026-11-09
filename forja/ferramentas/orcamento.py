"""tokens.orcar: decide, em ordem de prioridade, quais trechos cabem num orcamento de tokens (estimado)."""

from __future__ import annotations

from forja.dominio.erros import ValidacaoDominio
from forja.ferramentas.contrato import ResultadoFerramenta, montar
from forja.memoria.saneamento import estimar_tokens

MAX_ITENS = 200


def orcar_tokens(itens: list[dict[str, str]], orcamento: int, teto_item: int | None = None) -> ResultadoFerramenta:
    """`itens` = [{"id", "texto"}] na ORDEM de prioridade. Guloso: um item que nao cabe e pulado e os seguintes
    ainda podem caber. `teto_item` rejeita itens individualmente grandes (em vez de deixa-los consumir tudo)."""
    if not 1 <= orcamento <= 1_000_000:
        raise ValidacaoDominio("orcamento fora do intervalo 1..1000000")
    if len(itens) > MAX_ITENS:
        raise ValidacaoDominio(f"no maximo {MAX_ITENS} itens")
    usados, cabem, fora = 0, [], []
    for it in itens:
        n = estimar_tokens(it["texto"])
        if (teto_item is not None and n > teto_item) or usados + n > orcamento:
            fora.append({"id": it["id"], "tokens": n, "motivo": "acima do teto do item" if teto_item and n > teto_item
                         else "estoura o orcamento"})
            continue
        usados += n
        cabem.append({"id": it["id"], "tokens": n})
    total = sum(estimar_tokens(i["texto"]) for i in itens)
    linhas = [f"orcamento {orcamento}: usados {usados} (estimados) | cabem {len(cabem)} | fora {len(fora)}"]
    linhas += [f"- fora {f['id']} ({f['tokens']}): {f['motivo']}" for f in fora[:20]]
    dados = {"orcamento": orcamento, "usados": usados, "cabem": cabem, "fora": fora, "total_candidatos": total}
    return montar("tokens.orcar", "", "\n".join(linhas), dados, False, tokens_origem=total)
