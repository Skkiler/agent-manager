# Tarefas — Forja Fundacao

Legenda: [x] concluida e testada | [~] parcial | [ ] pendente

## Fase 0 — Inventario e higiene
- [x] 0.1 Inventario de ambiente (Python 3.13, Kiro IDE 1.4.121, sem Kiro CLI, Workflows via `.kiro/workflows`). (REQ-001)
- [x] 0.2 `.gitignore`/`.kiroignore`/`.env.example` revisados; `.gitattributes` para EOL. (REQ-001)
- [x] 0.3 `git init` + baseline; scan de padroes de segredo em arquivos rastreados (limpo). (REQ-001)
- [x] 0.4 ADRs iniciais em `docs/adr/`. 
- [~] 0.5 Scanner dedicado (gitleaks/detect-secrets) em pre-commit/CI: config escrita; instalacao pendente de aprovacao.
- [ ] 0.6 Selecao de 8–15 tarefas sinteticas de benchmark (Fase 4+).

## Fase 1 — Nucleo deterministico
- [x] 1.1 Config por ambiente com invariantes de seguranca (`forja/config.py`). (REQ-002, REQ-013)
- [x] 1.2 Dominio: erros, estados, contratos Pydantic, tempo injetavel. (REQ-005)
- [x] 1.3 Persistencia SQLite WAL + Alembic + backup/restore. (REQ-004)
- [x] 1.4 Repositorio operacional (UoW, concorrencia otimista, locks, idempotencia, eventos). (REQ-006, REQ-009, REQ-010)
- [x] 1.5 Servico de orquestracao: criacao, maquina de estados, execucoes, aprovacoes, expiracao, recuperacao. (REQ-005..011)
- [x] 1.6 ProvedorAgente + AgenteMock (SIMULADO) com cenarios sucesso/falha/bloqueio e checkpoint. (REQ-007)
- [x] 1.7 API FastAPI `/api/v1` + middleware (auth, rate limit, CSRF/host, correlation id) + OpenAPI. (REQ-003, REQ-012)
- [x] 1.8 SSE com replay por `Last-Event-ID` e deduplicacao. (REQ-010)
- [x] 1.9 Logs JSON sanitizados; endpoint `/recursos` com perfil adaptativo (sem LLM local). (REQ-012, REQ-013)
- [x] 1.10 Painel tecnico estatico (HTML/JS acessivel) consumindo apenas a API. (REQ-003)
- [x] 1.11 Testes unitarios/integracao (35) + smoke HTTP ponta a ponta + Ruff limpo. (todos os REQ)
- [x] 1.12 Documentacao de execucao Windows (README) e STATUS atualizado.

## Gate Fase 1
Atingido: tarefa simulada percorre rascunho -> ... -> concluida com estado consistente, evidencia (simulada),
artefato integro, eventos via SSE e logs — verificado por testes e pelo smoke contra servidor real.

## Proxima fase (2 — Kiro ACP)
Pre-condicao: confirmar entitlement empresarial e disponibilidade de `kiro-cli acp`. Implementar cliente ACP V3
atras de `ProvedorAgente`, com mock JSON-RPC antes de integracao real. Nao usar login empresarial em CI.
