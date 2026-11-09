"""Registro de integracoes: o que ja funciona (local, gratuito, sem credencial) e o que depende de aprovacao.

Regra do projeto: nada aqui abre rede nem guarda credencial. Conectores com rede/OAuth ficam `planejado` ate o operador
aprovar escopo, onde a credencial vive (variavel de ambiente/cofre, nunca Git) e quais dados podem sair da maquina.
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
    Conector("gmail_api", "Gmail (API, tempo real)", "email", "planejado", "gratuito na cota; exige projeto OAuth", True, True,
             (), "Prefira o .mbox acima enquanto isto nao for aprovado.",
             ("OAuth guarda refresh token em disco", "e-mail sai da maquina para o provedor de IA se for ao prompt"),
             "Escopo somente leitura (gmail.readonly), onde guardar o token, rotulos permitidos, retencao."),
    Conector("google_calendar", "Google Agenda (API)", "agenda", "planejado", "gratuito na cota", True, True, (),
             "Use o .ics enquanto isto nao for aprovado.", ("OAuth", "dados de terceiros nos convites"),
             "Escopo somente leitura e calendarios permitidos."),
    Conector("github", "GitHub (issues/PRs)", "codigo", "planejado", "gratuito (API publica, token opcional)", True, True, (),
             "Use `git.diff_analisar` com `git diff` local.", ("token com escopo minimo", "repositorios privados"),
             "Repositorios permitidos e escopo do token (somente leitura)."),
    Conector("notion_trello_jira", "Notion / Trello / Jira (quadros)", "organizacao", "planejado", "gratuito em planos basicos",
             True, True, (), "O quadro Kanban da Forja cobre o fluxo local; exporte CSV destes servicos e use `dados.converter`.",
             ("tokens de API", "dados de empresa"), "Qual servico, quais quadros e se dados de empresa podem ser lidos."),
    Conector("webhook_saida", "Avisos de saida (Slack/Teams/ntfy)", "notificacao", "planejado", "gratuito", True, True, (),
             "Hoje os avisos ficam no painel (SSE).", ("vazamento de conteudo em mensagens",),
             "Destino, conteudo permitido (somente ids/estados) e limite de frequencia."),
)


def listar(ferramentas_disponiveis: set[str]) -> list[dict]:
    """Registro serializavel; `disponivel` = todas as ferramentas do conector existem no catalogo carregado."""
    saida = []
    for c in REGISTRO:
        d = asdict(c)
        d["ferramentas"] = list(c.ferramentas)
        d["riscos"] = list(c.riscos)
        d["disponivel"] = c.estado == "implementado" and all(f in ferramentas_disponiveis for f in c.ferramentas)
        saida.append(d)
    return saida
