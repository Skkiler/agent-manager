"""Registro dos conectores de rede configuraveis. Modulo proprio: depende de todos os conectores, nenhum depende dele (sem ciclos)."""

from __future__ import annotations

from forja.integracoes.busca_web import BuscaWeb
from forja.integracoes.conectores import Conector, Github, IcsUrl, Jira
from forja.integracoes.produtividade import Gmail, GoogleAgenda, Notion, Trello

CONECTORES: dict[str, Conector] = {c.id: c for c in (Jira(), Github(), IcsUrl(), Trello(), Notion(), GoogleAgenda(), Gmail(), BuscaWeb())}
