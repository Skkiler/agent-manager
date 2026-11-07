# ADR-001 — Stack Python/FastAPI + painel TypeScript/HTML

- Status: aceito (Fase 1)
- Contexto: nucleo local-first de engenharia, i7-14700T / 16 GB, sem LLM local no inicio.
- Decisao: servico em Python 3.12+ com FastAPI, Pydantic v2, SQLAlchemy/Alembic; painel inicial em HTML/JS
  estatico servido pelo proprio backend (Phaser/Vite ficam para a Fase 7).
- Consequencias: ecossistema maduro de engenharia; baixo custo de memoria; painel acessivel sem build.
- Alternativas: Node/Express (menos bibliotecas de engenharia/parsing); front SPA desde ja (peso desnecessario na Fase 1).
