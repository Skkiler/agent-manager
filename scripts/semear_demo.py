"""Popula um servidor LOCAL com dados 100% sinteticos para ver o painel (tarefas, quadro, grafo, configuracao).

Uso: python scripts/semear_demo.py [--porta 8787] [--token TOKEN]
Nunca aponte para um servidor com dados reais: este script so cria dados ficticios (agente simulado/mock).
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request


def chamar(base: str, token: str, metodo: str, caminho: str, corpo: dict | None = None) -> dict | list:
    req = urllib.request.Request(  # noqa: S310 - base sempre http://127.0.0.1
        f"{base}/api/v1{caminho}", method=metodo, data=None if corpo is None else json.dumps(corpo).encode(),
                                 headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 - base e loopback informada pelo operador
            return json.loads(r.read() or "null")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{metodo} {caminho} -> HTTP {e.code}: {e.read().decode()[:300]}") from e


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--porta", type=int, default=8787, help="porta do servidor em loopback")
    ap.add_argument("--token", default="")
    a = ap.parse_args()
    base = f"http://127.0.0.1:{a.porta}"  # sempre loopback: o script nunca semeia servidores remotos
    c = lambda m, p, b=None: chamar(base, a.token, m, p, b)  # noqa: E731

    proj = c("POST", "/projetos", {"nome": f"demo-{int(time.time())}", "descricao": "dados sinteticos"})

    def tarefa(titulo: str, prio: int, cenario: str | None, preparar: bool = True, executar: bool = False) -> dict:
        o = c("POST", "/objetivos", {"projeto_id": proj["id"], "titulo": titulo, "prioridade": prio})
        entrada = {"mock_cenario": cenario, "mock_passos": 2} if cenario else {}
        t = c("POST", "/tarefas", {"objetivo_id": o["id"], "titulo": titulo, "criterios_aceite": ["entregar resumo verificavel"], "entrada": entrada})
        if preparar:
            k = c("POST", f"/tarefas/{t['id']}/transicao", {"para": "classificada", "expected_version": t["versao_estado"]})
            c("POST", f"/tarefas/{t['id']}/transicao", {"para": "preparada", "expected_version": k["versao_estado"]})
        if executar:
            ex = c("POST", f"/tarefas/{t['id']}/execucoes")
            c("POST", f"/execucoes/{ex['id']}/iniciar")
        return t

    tarefa("Definir autenticacao da API", 1, "conversa", executar=True)  # fica bloqueada aguardando decisoes
    tarefa("Escrever guia de uso", 2, "sucesso", executar=True)
    tarefa("Planejar migracao do banco", 2, None)
    tarefa("Revisar politica de logs", 3, None, preparar=False)
    tarefa("Mapear integracoes externas", 4, "falha", executar=True)
    tarefa("Preparar demonstracao", 3, "sucesso")

    def nota(titulo: str, conteudo: str, ns: str = "publico", tags: list[str] | None = None) -> dict:
        return c("POST", "/memorias", {"tipo": "procedimental", "titulo": titulo, "conteudo": conteudo, "namespace": ns, "tags": tags or []})

    nota("Autenticacao Bearer", "# Autenticacao\nUsar **Bearer** com [[Tokens JWT]]. Ver [[Rotacao de chaves]] e [[Politica de sessao]].", tags=["seguranca"])
    nota("Tokens JWT", "Assinar com chave rotativa. Relacionado a [[Autenticacao Bearer]] e [[Rotacao de chaves]].", tags=["seguranca"])
    nota("Rotacao de chaves", "- Rotacionar a cada 90 dias\n- Registrar em [[Politica de logs]]")
    nota("Politica de logs", "Logs sem PII. Ver [[Autenticacao Bearer]].", tags=["operacao"])
    nota("Guia de migracao", "Passos para migrar o banco com [[Alembic]] e testar o downgrade.", tags=["banco"])
    nota("Alembic", "Ferramenta de migracoes. Usada no [[Guia de migracao]].", tags=["banco"])
    nota("Nota isolada", "Sem ligacoes.")
    nota("Ideias pessoais", "Rascunho com [[Guia de migracao]]", ns="pessoal")

    msgs = [
        ("agente:analista", "master", "resultado", 3, "Analise de autenticacao concluida", "Recomendo Bearer; detalhes no artefato.", ["tarefa:T-demo"]),
        ("agente:revisor", "master", "pergunta", 1, "Posso apagar o diretorio build?", "Preciso de decisao antes de continuar.", []),
        ("master", "agente:analista", "comando", 2, "Priorizar a migracao do banco", "Foco nesta semana.", []),
        ("sistema", "todos", "evento", 4, "Manutencao programada do indice", "", []),
        ("operador", "master", "apontamento", 2, "Revisar custo dos modelos", "Comparar execucao x revisao.", []),
    ]
    for o, d, tp, pr, assunto, texto, refs in msgs:
        c("POST", "/quadro", {"origem": o, "destino": d, "tipo": tp, "prioridade": pr, "assunto": assunto, "payload": {"texto": texto} if texto else {}, "referencias": refs})

    cfg = c("GET", "/configuracao")
    c("PUT", "/configuracao", {"expected_version": cfg["versao"], "configuracao": {"partes": {"execucao": {"modelo": "modelo-economico"}, "revisao": {"modelo": "modelo-profundo"}}}})
    print("semeado: 6 tarefas, 8 notas, 5 mensagens no quadro e configuracao de modelos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
