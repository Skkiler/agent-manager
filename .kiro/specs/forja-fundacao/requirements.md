# Requisitos — Forja Fundacao (Fases 0 e 1)

Fonte normativa: `ORIENTACAO_MESTRA_ECOSSISTEMA_KIRO.md` (secoes 6, 15, 17, 18, 19).
Escopo desta spec: higiene do repositorio (Fase 0) e nucleo local deterministico (Fase 1).
Fora de escopo: adaptador Kiro ACP, memoria/grafos, multiagentes, UI pixel art (Fases 2+).

## Requisitos (EARS) e criterios de aceite

### REQ-001 — Configuracao Git-safe
- Quando o repositorio for versionado, o sistema deve manter `.gitignore`, `.kiroignore` e `.env.example`
  sem valores reais de segredo.
- Aceite: `git ls-files` nao contem `.env`, chaves, `*.sqlite3`, `data/`, `logs/`, tokens. (Testado — ver STATUS.)

### REQ-002 — Bind loopback por padrao
- O servidor deve escutar em `127.0.0.1` por padrao; bind fora de loopback exige `APP_ALLOW_LAN_BIND=true`
  e `APP_REQUIRE_AUTH=true`.
- Aceite: `Configuracoes` rejeita host nao-loopback sem aprovacao explicita (teste de config).

### REQ-003 — Autenticacao obrigatoria
- Enquanto `APP_REQUIRE_AUTH=true`, toda rota de dados deve exigir token Bearer valido.
- Aceite: requisicao sem token recebe 401; com token valido, 2xx. (Testado: `test_exige_autenticacao`, smoke.)

### REQ-004 — Modelo de dominio e persistencia
- O sistema deve persistir projeto, objetivo, tarefa, execucao, evento, artefato, evidencia, aprovacao,
  lock e idempotencia, com migracoes versionadas (Alembic) e SQLite WAL.
- Aceite: migracao cria o schema; downgrade remove; backup/restore preserva dados. (Testado: `test_banco`.)

### REQ-005 — Maquina de estados da tarefa
- Transicoes devem seguir a secao 6.2; transicoes impossiveis sao rejeitadas; estados terminais nao saem.
- Transicoes reservadas ao orquestrador nao sao aceitas via comando manual.
- Aceite: `test_estados`, `test_transicao_reservada_rejeitada`, `test_conflito_versao`.

### REQ-006 — Concorrencia otimista e idempotencia
- Comandos de criacao aceitam `Idempotency-Key`; transicoes usam `expected_version`.
- Aceite: chave repetida retorna a mesma resposta; corpo divergente conflita; versao obsoleta e rejeitada.
  (Testado: `test_idempotencia_*`, `test_conflito_versao`.)

### REQ-007 — Execucao por agente mock e verificacao real
- O nucleo executa tarefas via `ProvedorAgente`; na Fase 1 apenas o mock (SIMULADO).
- Conclusao exige ao menos uma evidencia e integridade (hash) dos artefatos gravados.
- Evidencia de mock e sempre marcada `simulada=true` e nao conta como funcionalidade real.
- Aceite: `test_fluxo_ponta_a_ponta_sucesso`, `test_cenario_falha`, `test_cenario_bloqueio_e_retomada`.

### REQ-008 — Orcamento e politicas
- O sistema deve respeitar `max_tentativas`, `max_duracao_segundos`, `max_chamadas_modelo` e politica de aprovacao.
- Aceite: `test_orcamento_max_tentativas`, `test_expiracao_por_deadline`, `test_aprovacao_*`.

### REQ-009 — Locks de recurso
- Execucoes concorrentes com padroes de escrita sobrepostos devem ser bloqueadas; locks expiram por lease.
- Aceite: `test_lock_de_recurso_bloqueia_sobreposicao`, `test_duas_execucoes_concorrentes_rejeitadas`.

### REQ-010 — Eventos e SSE com replay
- O sistema deve emitir eventos sequenciais sanitizados e transmitir por SSE com `Last-Event-ID`/replay.
- Eventos duplicados sao deduplicados por `dedup_key`.
- Aceite: `test_sse_replay_e_last_event_id`, `test_stream_exige_token`.

### REQ-011 — Recuperacao pos-crash e shutdown gracioso
- Apos reinicio, execucoes `executando` sem worker viram `pausada`/tarefa `bloqueada` (retomaveis).
- Aceite: `test_recuperacao_pos_crash`.

### REQ-012 — Logs sanitizados e CSRF/host
- Logs em JSON com `correlation_id`; segredos redigidos; validacao de Host e protecao CSRF por Origin.
- Aceite: `test_host_invalido_rejeitado`, `test_origin_cross_site_rejeitada`.

### REQ-013 — Perfis de recurso adaptativos, sem LLM local
- O sistema detecta hardware e decide perfil; `APP_ENABLE_LOCAL_LLM=false` e invariante na Fase 1.
- Aceite: `GET /recursos` retorna metricas + perfil com `local_llm_enabled=false`.

## Rastreabilidade
Cada REQ aponta para teste automatizado real. O estado verificado fica em `docs/STATUS_IMPLEMENTACAO.md`.
