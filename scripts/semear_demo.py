"""Popula um servidor LOCAL com dados 100% sinteticos para ver o painel (tarefas, quadro, grafo, configuracao).

Uso: python scripts/semear_demo.py [--porta 8787] [--token TOKEN]
Nunca aponte para um servidor com dados reais: este script so cria dados ficticios (agente simulado/mock).
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


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
    ap.add_argument("--token", default=os.environ.get("APP_API_TOKEN", ""), help="padrao: APP_API_TOKEN do ambiente (ex.: no conteiner)")
    ap.add_argument("--pasta-trabalho", default="", help="pasta sintetica do projeto de demonstracao (padrao: temporaria)")
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
    escrita = demo_desfazer(c, a.pasta_trabalho)

    # duplicata quase identica: a organizacao automatica do segundo cerebro vai sugerir unir (fila de revisao)
    for sufixo in ("", " Revisado."):
        c("POST", "/memorias", {"tipo": "procedimental", "titulo": "Checklist de deploy", "namespace": "pessoal", "tags": ["deploy", "operacao"],
                                "conteudo": "Rodar testes, migrar o banco, publicar a imagem e conferir a saude do servico." + sufixo})

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
    extra = ""
    if os.environ.get("FORJA_INT_DEMO_TRELLO_TOKEN"):  # so com variaveis FICTICIAS no ambiente do servidor demo (o inspetor usa o Jira desligado)
        trello = c("GET", "/integracoes/trello")
        c("PUT", "/integracoes/trello/configuracao", {"expected_version": trello["versao"], "configuracao": {
            "ativo": True, "variavel_usuario": "FORJA_INT_DEMO_TRELLO_KEY", "variavel_token": "FORJA_INT_DEMO_TRELLO_TOKEN",
            "itens_permitidos": ["5f2b1c3d4e5f60718293a4b5"], "permitir_escrita": True}})
        for nome in ("Revisar PR da migracao", "Atualizar documentacao do MCP"):
            c("POST", "/acoes-externas", {"integracao": "trello", "acao": "criar_cartao", "parametros": {"lista": "6a7b8c9d0e1f20314253a4b5", "nome": nome}})
        extra = ", 2 acoes externas pendentes (Trello ficticio)"
    print(f"semeado: {6 + escrita} tarefas, 10 notas, 5 mensagens no quadro e configuracao de modelos{extra}")
    return 0


def demo_desfazer(c, pasta: str) -> int:  # noqa: ANN001
    """Projeto com pasta de trabalho SINTETICA + tarefa do agente mock que cria 1 arquivo: o cartao ganha 'Desfazer alteracoes'.
    A pasta precisa existir no MESMO computador (ou conteiner) do servidor; se nao for aceita, o resto da demo segue."""
    alvo = Path(pasta) if pasta else Path(tempfile.mkdtemp(prefix="forja-demo-proj-"))
    alvo.mkdir(parents=True, exist_ok=True)
    (alvo / "README.md").write_text("# Projeto de demonstracao (sintetico)\n", encoding="utf-8")
    proj = c("POST", "/projetos", {"nome": f"demo-pasta-{int(time.time())}", "descricao": "pasta sintetica para desfazer"})
    try:
        c("PUT", f"/projetos/{proj['id']}/pastas", {"expected_version": proj.get("versao", 1), "pastas": [{"caminho": str(alvo), "papel": "trabalho"}]})
    except SystemExit as e:
        print(f"aviso: pasta de trabalho nao aceita pelo servidor ({str(e)[:120]}); demo de desfazer pulada")
        return 0
    o = c("POST", "/objetivos", {"projeto_id": proj["id"], "titulo": "Documentar o projeto"})
    t = c("POST", "/tarefas", {"objetivo_id": o["id"], "titulo": "Gerar arquivo de notas (mock)", "modo": "documentacao",
                               "criterios_aceite": ["arquivo criado"], "entrada": {"mock_cenario": "escrita", "mock_passos": 1}})
    k = c("POST", f"/tarefas/{t['id']}/transicao", {"para": "classificada", "expected_version": t["versao_estado"]})
    c("POST", f"/tarefas/{t['id']}/transicao", {"para": "preparada", "expected_version": k["versao_estado"]})
    ex = c("POST", f"/tarefas/{t['id']}/execucoes")
    c("POST", f"/execucoes/{ex['id']}/iniciar")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
