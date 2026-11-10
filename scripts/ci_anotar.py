"""CI: transforma testes falhos de um relatorio JUnit em anotacoes do GitHub Actions (`::error`), legiveis sem login no repositorio publico.

Uso: python scripts/ci_anotar.py relatorio.xml   (so imprime; o codigo de saida do pytest continua decidindo o passo)
A mensagem e sanitizada e curta: nada de segredo (o CI so usa dados sinteticos) nem saida longa.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET  # noqa: S405 - relatorio gerado pelo proprio pytest no runner
from pathlib import Path


def anotacoes(caminho: Path, limite: int = 10) -> list[str]:
    raiz = ET.parse(caminho).getroot()  # noqa: S314
    saida = []
    for caso in raiz.iter("testcase"):
        for falha in [*caso.findall("failure"), *caso.findall("error")]:
            msg = " ".join((falha.get("message") or falha.text or "").split())[:300].replace("%", "%25").replace("\r", "").replace("\n", " ")
            arquivo = (caso.get("file") or caso.get("classname", "").replace(".", "/") + ".py")
            saida.append(f"::error file={arquivo},title={caso.get('name', '?')}::{msg}")
    return saida[:limite]


if __name__ == "__main__":
    for linha in anotacoes(Path(sys.argv[1])):
        print(linha)
