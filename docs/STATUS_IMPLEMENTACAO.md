# Estado da implementacao

**Atualizado:** 2026-11-06. **Fases 0 e 1 implementadas e testadas** com o nucleo deterministico local-first.
O agente de execucao e um **mock SIMULADO**: evidencias que ele gera nao comprovam funcionalidade real.
Integracao Kiro (ACP), memoria/grafos, multiagentes e painel pixel art permanecem nao iniciados (Fases 2+).

## Ambiente verificado
- Python 3.13.5; Git 2.50.0 (repo iniciado nesta sessao).
- Kiro IDE 1.4.121 instalado. **Kiro CLI nao instalado** (`kiro-cli`/`kiro` ausentes no PATH) — nucleo nao depende dele.
- Workflows: receita read-only presente em `.kiro/workflows/investigar.workflow.yaml`; disponibilidade por conta nao confirmada.
- Hardware desta maquina nao e o desktop alvo (i7-14700T/16 GB); perfil adaptativo detecta em runtime via `/recursos`.

## Resultados reais de teste (nesta sessao)
- `python -m pytest` -> **35 passed** (~11,6 s). Cobertura total **87%** (`--cov=forja`).
- `python -m ruff check forja tests` -> **All checks passed**.
- Smoke HTTP ponta a ponta (`scripts/smoke.py`) contra servidor real em `127.0.0.1:8787`:
  execucao=concluida, tarefa=concluida, 1 evidencia (SIMULADA), 1 artefato integro. **sucesso**.
- Seguranca verificada: requisicao sem token -> HTTP 401; bind apenas em loopback; logs JSON sanitizados.
- Git-safe: scan de padroes de segredo em arquivos rastreados -> **limpo**; `data/`, `.env`, `*.sqlite3`, chaves nao rastreados.

## Fases

| Fase | Estado | Evidencia | Proximo passo |
|---|---|---|---|
| 0 — Diagnostico/Git-safe | testado | inventario de ambiente; `.gitignore`/`.kiroignore`/`.gitattributes`; scan limpo; ADRs | instalar scanner dedicado (aprovacao) |
| 1 — Nucleo deterministico | testado | 35 testes + smoke HTTP + Ruff; API `/api/v1`; SSE; SQLite/Alembic; mock | iniciar Fase 2 (Kiro ACP) |
| 2 — ACP/Kiro | nao iniciada | — | confirmar CLI/entitlement; cliente ACP V3 atras de `ProvedorAgente`, com mock JSON-RPC primeiro |
| 3 — Memoria/grafo | nao iniciada | — | ontologia, ACL, FTS5, proveniencia |
| 4 — Contexto/ferramentas | nao iniciada | — | recuperacao hibrida; ferramentas N0 |
| 5 — Multiagentes | nao iniciada | — | DAG, scheduler, worktrees, revisao |
| 6 — Aprendizado | nao iniciada | — | EWMA, roteamento, N1 opcional |
| 7 — UI/LAN | nao iniciada | — | painel pixel art; tunel/HTTPS |
| 8 — Open source | nao iniciada | — | licenca, CI, SBOM, release |

## Componentes entregues (Fase 1)
- `forja/config.py` — configuracao com invariantes (loopback, auth, sem LLM local, ACP desligado).
- `forja/dominio/` — erros, maquina de estados (secao 6.2), contratos Pydantic v2, relogio injetavel.
- `forja/adapters/sqlite/` — tabelas, engines WAL (escrita serializada), migracoes Alembic, backup/restore, repositorio (UoW, versao otimista, locks, idempotencia, eventos).
- `forja/agentes/` + `forja/adapters/agentes_mock/` — `ProvedorAgente` e `AgenteMock` (cenarios sucesso/falha/bloqueio, checkpoint, cancelamento cooperativo).
- `forja/orquestracao/servico.py` — casos de uso: criacao, transicoes, execucoes, aprovacoes, orcamento, expiracao, recuperacao pos-crash, shutdown gracioso.
- `forja/servidor/` — FastAPI `/api/v1`, middleware (auth Bearer, rate limit, CSRF/Host, correlation id), SSE com replay, OpenAPI em `/api/docs`.
- `forja/painel/estatico/` — painel tecnico HTML/JS acessivel, consome apenas a API.
- `forja/observabilidade/` — logs JSON sanitizados, deteccao de hardware e perfil adaptativo.
- Specs em `.kiro/specs/forja-fundacao/`, ADRs 001/002/003/005 em `docs/adr/`.

## Limitacoes e pendencias (honestas)
- **Mock nao e funcionalidade real.** Nenhuma tarefa executa trabalho de engenharia de fato nesta fase.
- Scanner de segredos dedicado (gitleaks/detect-secrets) **nao instalado**: `.pre-commit-config.yaml` escrito, instalacao pendente de aprovacao (instala software). Fallback usado: scan de padroes via `git grep` (limpo).
- Sem CI configurada ainda (Fase 8). Sem commit criado nesta sessao (aguardando confirmacao do usuario).
- `ThreadPoolExecutor` em processo unico: suficiente para o MVP local; escalonamento multiagente/worktrees e Fase 5.
- `autentica por token em query` apenas na rota de stream SSE (EventSource nao envia cabecalho); mutacoes exigem Bearer.

## Retomada sem reprocessar
1. `pip install -r requirements-dev.txt`; `python -m pytest -q` deve dar 35 passed.
2. Fase 2: implementar `forja/adapters/kiro_acp/` como novo `ProvedorAgente`, injetado em `criar_servico`
   quando `APP_KIRO_ACP_ENABLED=true` (hoje a config bloqueia ate a implementacao existir). Comecar por mock JSON-RPC.
3. Nao reimplementar o nucleo: estados, repositorio, API, SSE e recuperacao ja estao cobertos por teste.
