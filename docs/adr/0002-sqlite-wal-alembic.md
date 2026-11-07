# ADR-002 — SQLite WAL + Alembic no MVP

- Status: aceito (Fase 1)
- Contexto: persistencia local-first, baixa concorrencia, necessidade de migracoes e integridade.
- Decisao: SQLite em modo WAL com dois engines (escrita serializada via `BEGIN IMMEDIATE`, leitura concorrente),
  migracoes Alembic com engine injetado (sem `alembic.ini`), backup via API nativa + `integrity_check`.
  `sqlite-vec` e Postgres ficam para fases posteriores atras de interfaces de repositorio.
- Consequencias: zero servidor de banco; transacoes previsiveis; caminho de upgrade preservado.
- Alternativas: Postgres desde ja (peso operacional desnecessario no MVP local).
