"""Registro de integracoes: o que funciona hoje e o que depende de aprovacao.

Locais (gratuitos, sem rede nem credencial) funcionam assim que a ferramenta e usada. Conectores de REDE (Jira, GitHub, agenda
por URL) estao implementados, mas NASCEM DESLIGADOS: o operador os configura na tela, o segredo fica so no ambiente (.env) e a
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
    Conector("gmail_api", "Gmail (API/IMAP, tempo real)", "email", "planejado", "gratuito na cota; exige OAuth ou senha de app",
             True, True, (), "Prefira o .mbox acima enquanto isto nao for aprovado.",
             ("OAuth guarda refresh token", "e-mail sai da maquina para o provedor de IA se for ao prompt"),
             "Escopo somente leitura, onde guardar o token, rotulos permitidos, retencao."),
    Conector("google_calendar", "Google Agenda (API)", "agenda", "planejado", "gratuito na cota", True, True, (),
             "Use o endereco .ics secreto (acima) enquanto isto nao for aprovado.", ("OAuth", "dados de terceiros nos convites"),
             "Escopo somente leitura e calendarios permitidos."),
    Conector("notion_trello", "Notion / Trello (quadros)", "organizacao", "planejado", "gratuito em planos basicos", True, True, (),
             "Use o Kanban da Forja, ou exporte CSV e use `dados.converter`.", ("tokens de API", "dados de empresa"),
             "Qual servico, quais quadros e se dados de empresa podem ser lidos."),
    Conector("webhook_saida", "Avisos de saida (Slack/Teams/ntfy)", "notificacao", "planejado", "gratuito", True, True, (),
             "Hoje os avisos ficam no painel (SSE).", ("vazamento de conteudo em mensagens",),
             "Destino, conteudo permitido (somente ids/estados) e limite de frequencia."),
    Conector("escrita_em_servicos", "Escrita em servicos externos (comentar, criar, transicionar)", "organizacao", "planejado",
             "depende do servico", True, True, (), "Hoje todas as integracoes de rede sao SOMENTE LEITURA.",
             ("alteracoes irreversiveis em sistemas de terceiros", "vazamento de dados para fora"),
             "Cada acao de escrita passaria pelas aprovacoes por acao (uma pergunta em linguagem natural por acao)."),
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
