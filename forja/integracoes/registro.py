"""Registro de integracoes: o que funciona hoje e o que depende de aprovacao.

Locais (gratuitos, sem rede nem credencial) funcionam assim que a ferramenta e usada. Conectores de REDE (Jira, GitHub, agenda
por URL, Trello, Notion, Google Agenda, Gmail) estao implementados, mas NASCEM DESLIGADOS: o operador os configura na tela, o segredo fica so no ambiente (.env) e a
tela guarda apenas o NOME da variavel. Os planejados exigem aprovacao de escopo antes de existirem.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Conector:
    id: str
    nome: str
    categoria: str
    estado: str  # implementado | planejado
    custo: str
    rede: bool
    credencial: bool
    ferramentas: tuple[str, ...] = ()
    como_usar: str = ""
    riscos: tuple[str, ...] = field(default_factory=tuple)
    aprovacao: str = ""  # o que o operador precisa aprovar antes de ativar (so planejados)
    modo: str = "local"  # local | rede
    configuravel: bool = False  # True = configurado pela tela (conectores de rede implementados)


REGISTRO: tuple[Conector, ...] = (
    Conector("vault_markdown", "Cofre de notas Markdown (Obsidian)", "notas", "implementado", "gratuito, local", False, False,
             ("vault.indexar", "texto.amostra", "codigo.outline"),
             "Aponte APP_TOOLS_ROOTS para o cofre; `vault.indexar` mostra links, backlinks, tags e notas orfas. "
             "Para entrar no segundo cerebro, ingira a pasta (scripts/memoria_ingerir.py)."),
    Conector("agenda_ics", "Agenda (arquivo .ics)", "agenda", "implementado", "gratuito, local", False, False,
             ("agenda.ler_ics",), "Exporte Google Agenda/Outlook/Apple para .ics e aponte para o arquivo.",
             ("fusos horarios ignorados", "recorrencias nao expandidas")),
    Conector("email_mbox", "E-mail (exportacao .mbox / Google Takeout)", "email", "implementado", "gratuito, local", False,
             False, ("email.ler_mbox",),
             "Exporte o Gmail pelo Google Takeout (.mbox) e aponte para o arquivo. Enderecos mascarados por padrao.",
             ("e-mail e dado pessoal e nao confiavel (prompt injection)", "somente leitura de um instantaneo")),
    Conector("planilhas", "Planilhas e tabelas (CSV/JSON/Markdown)", "dados", "implementado", "gratuito, local", False, False,
             ("dados.converter",), "Converte entre csv, json, jsonl e tabela markdown; neutraliza formulas no CSV."),
    Conector("sqlite_local", "Bancos SQLite", "dados", "implementado", "gratuito, local", False, False,
             ("sql.inspecionar",), "Mostra tabelas, colunas e indices sem ler linhas."),
    Conector("jira", "Jira (leitura de issues)", "organizacao", "implementado", "depende do seu plano do Jira", True, True,
             ("jira.buscar", "jira.obter_issue", "jira.listar_projetos"),
             "Desligada por padrao. Na tela, informe o endereco, os projetos permitidos e os NOMES das variaveis "
             "(ex.: FORJA_INT_JIRA_TOKEN); o token fica so no .env.",
             ("dados do Jira podem ir ao prompt do provedor de IA", "token com mais permissao do que o necessario"),
             modo="rede", configuravel=True),
    Conector("github", "GitHub (issues e pull requests, leitura)", "codigo", "implementado", "gratuito (limite da API)", True, True,
             ("github.listar_issues", "github.obter_issue"),
             "Desligada por padrao. Informe os repositorios permitidos e, se precisar, o NOME da variavel do token "
             "(token fino, somente leitura).",
             ("repositorios privados exigem token", "dados podem ir ao prompt do provedor de IA"),
             modo="rede", configuravel=True),
    Conector("agenda_ics_url", "Agenda por endereco .ics secreto", "agenda", "implementado", "gratuito", True, True,
             ("agenda.ler_ics_url",),
             "Desligada por padrao. Guarde o endereco secreto no .env e informe so o NOME da variavel e o servidor "
             "permitido (ex.: calendar.google.com).",
             ("quem tem o endereco le a agenda inteira", "fusos horarios ignorados"), modo="rede", configuravel=True),
    Conector("trello", "Trello (quadros e cartoes)", "organizacao", "implementado", "gratuito em planos basicos", True, True,
             ("trello.listar_cartoes", "trello.propor_cartao"),
             "Desligada por padrao. Informe os quadros permitidos e os NOMES das variaveis da chave e do token. Criar cartao e uma "
             "acao externa: so acontece depois da sua aprovacao, uma a uma.",
             ("token do Trello da acesso a todos os seus quadros: a lista de quadros e a barreira", "dados podem ir ao prompt do provedor de IA"),
             modo="rede", configuravel=True),
    Conector("notion", "Notion (bases de dados, leitura)", "organizacao", "implementado", "gratuito em planos basicos", True, True,
             ("notion.consultar_base",),
             "Crie uma integracao interna no Notion (so leitura), compartilhe com ela apenas as bases desejadas e informe os IDs aqui.",
             ("dados de empresa", "dados podem ir ao prompt do provedor de IA"), modo="rede", configuravel=True),
    Conector("google_agenda", "Google Agenda (API, leitura)", "agenda", "implementado", "gratuito na cota", True, True,
             ("google_agenda.eventos",),
             "OAuth com escopo calendar.readonly: client ID, client secret e refresh token ficam no .env. So titulo e horario dos "
             "calendarios permitidos; convidados e descricoes ficam de fora.",
             ("refresh token da acesso continuo ate ser revogado", "dados de terceiros nos convites"), modo="rede", configuravel=True),
    Conector("gmail", "Gmail (API, leitura)", "email", "implementado", "gratuito na cota", True, True, ("gmail.listar",),
             "OAuth com escopo gmail.readonly. So cabecalhos e trecho dos rotulos permitidos, remetentes mascarados, no maximo 10 por consulta. "
             "Para um instantaneo offline, o .mbox continua disponivel.",
             ("e-mail e dado pessoal e nao confiavel (prompt injection)", "refresh token da acesso continuo ate ser revogado"),
             modo="rede", configuravel=True),
    Conector("busca_web", "Busca web (referencias, boas praticas, bugs conhecidos)", "pesquisa", "implementado",
             "Brave: plano da API; SearXNG: gratuito (instancia propria)", True, True, ("web.buscar", "web.ler_pagina"),
             "Desligada por padrao. Escolha o provedor e informe o NOME da variavel da chave (Brave). O agente busca quando achar util "
             "(ex.: tag Pesquisador) e so le paginas que vieram dessa busca ou de dominios que voce liberar.",
             ("a consulta sai da sua maquina para o provedor de busca", "paginas da web podem conter instrucoes maliciosas (tratadas como dado)"),
             modo="rede", configuravel=True),
    Conector("webhook_saida", "Avisos de saida (Slack/Teams/ntfy)", "notificacao", "planejado", "gratuito", True, True, (),
             "Hoje os avisos ficam no painel (SSE).", ("vazamento de conteudo em mensagens",),
             "Destino, conteudo permitido (somente ids/estados) e limite de frequencia."),
)


def listar(ferramentas_disponiveis: set[str], prontas: set[str] | None = None) -> list[dict]:
    """Registro serializavel. `disponivel` = ferramentas no catalogo e, nos de rede, a integracao esta PRONTA."""
    saida = []
    for c in REGISTRO:
        d = asdict(c)
        d["ferramentas"] = list(c.ferramentas)
        d["riscos"] = list(c.riscos)
        d["disponivel"] = (c.estado == "implementado" and all(f in ferramentas_disponiveis for f in c.ferramentas)
                           and (c.modo == "local" or c.id in (prontas or set())))
        saida.append(d)
    return saida
