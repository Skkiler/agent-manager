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

## Fase 2 — Adaptador Kiro ACP
- [x] 2.1 Verificar Kiro CLI real (3.1.0) e handshake ACP; mapear erro de auth. (REQ-014)
- [x] 2.2 `ClienteAcp` (JSON-RPC stdio, permissoes negadas, capacidades minimas, erros tipados). (REQ-014, REQ-015)
- [x] 2.3 `ProvedorKiroAcp` (analise/documentacao, cancelamento, timeout, redacao, workspace isolado). (REQ-016)
- [x] 2.4 Diagnostico (`/api/v1/kiro/status`, `scripts/diagnostico_kiro.py`) sem consumir creditos. (REQ-015)
- [x] 2.5 Fiacao em `criar_servico` por `APP_KIRO_ACP_ENABLED`; config e `.env.example`; ADR-004.
- [x] 2.6 Testes com agente ACP falso (subprocesso real) + handshake real + execucao real sem login (bloqueio correto).
- [x] 2.7 Prompt real autenticado: end_turn em 4,7 s; escrita negada de fato; escrita aprovada de fato (sandbox vazio).
- [x] 2.10 Aprovacao por acao: descritor, mediador/agrupamento, adendo, parcial, lembrar, lote, timeout/cancel/reinicio, painel, migracao 0002, ADR-006. (REQ-017..019)
- [ ] 2.8 Agentes/skills/Specs-templates Kiro e primeiro Workflow de producao (Workflows nao confirmado na conta).
- [x] 2.9 `session/load` na retomada quando o agente anuncia `loadSession` (kiro-cli 3.1.0 anuncia; validado no Kiro real), replay descartado, queda segura para sessao nova. Pool de processos NAO feito: um processo por execucao continua (sem ganho medido que justifique).

## Fase 3 — Memoria textual e grafos
- [x] 3.1 Dominio da memoria: namespaces/ACL, estados epistemologicos, ontologia (REQ-020, REQ-021).
- [x] 3.2 Saneamento: PII (Luhn p/ cartao), segredos, deteccao de prompt injection, consulta FTS5 segura (REQ-023).
- [x] 3.3 Persistencia: migracao 0003 (memoria, versoes, evidencias, grafo, arquivo/simbolo) + FTS5 (memoria_fts, codigo_fts).
- [x] 3.4 ServicoMemoria: CRUD versionado, promocao com evidencia real, contradicao, retencao/remocao (REQ-021, REQ-024).
- [x] 3.5 Indexador e ingestao incremental por SHA-256, simbolos via AST Python, invalidacao por origem (REQ-022).
- [x] 3.6 Busca hibrida: FTS5 + ranker de simbolos + RRF; hipoteses rotuladas; conflitos devolvidos (REQ-025).
- [x] 3.7 Grafo de conhecimento tipado com escopo/ACL e vizinhos (1-2 saltos).
- [x] 3.8 API /api/v1/memorias* e /conhecimento*; painel de busca com fonte e avisos; ingestao so em raizes autorizadas.
- [x] 3.9 Testes de mutacao nas defesas de ACL/evidencia/injection/raiz; 	ests/test_git_safe.py; ADR-007.
- [x] 3.10 Propostas automaticas de procedimento a partir de tarefas concluidas (so como candidato) — ver 4.12.
- [x] 3.11 Recuperacao ligada ao prompt do Kiro (ConstrutorContexto, orcamento, so namespaces autorizados) — ver 4.2.
- [ ] 3.12 Embeddings opcionais / sqlite-vec apos benchmark contra o baseline textual — Fase 4.

## Fase 4 — Contexto economico, conversa e busca
- [x] 4.1 Busca: radicais PT/EN, sinonimos, cobertura ponderada por idf, ranker de grafo; benchmark recall@k/MRR/nDCG. ADR-010.
- [x] 4.2 `ConstrutorContexto` com portoes e orcamento; persistencia e marcacao de itens uteis. ADR-008.
- [x] 4.3 Protocolo de conversa (briefing, decisoes agrupadas, retomada compacta), API e painel. ADR-009.
- [x] 4.4 Desempenho de busca em codigo (migracao 0005) e ingestao local por script (`scripts/memoria_ingerir.py`).
- [x] 4.5 Base publica `knowledge/procedimentos` + sinonimos, com teste de busca.
- [x] 4.6 Plano de ferramentas para agentes (documento removido na limpeza; o catalogo real esta em ADR-011; economia medida em 4.7).
- [x] 4.7 Ferramentas N0 3, 5 e 7 (`forja/ferramentas/`) com contrato comum, 17 testes, mutacao 7/7 e `scripts/medir_ferramentas.py`.
- [x] 4.7b Catalogo de ferramentas (contrato, fallback, custo observado) e rota `/api/v1/ferramentas/*`; 6 ferramentas novas (logs, segredos, mapa, esquema, conversor, orcamento, amostra). ADR-011.
- [x] 4.7c MCP stdio da Forja (5 ferramentas, so fala com a API em loopback), opt-in, espera de prontidao; medido no Kiro real (ADR-015): economia quando usado, mas o agente nao o escolhe sozinho.
- [x] 4.10 Quadro de comunicacao (blackboard) com prioridade, dedup por origem, validade e entrega unica; migracao 0006.
- [x] 4.11 Painel de controle do master (`/controle/painel`): urgentes, bloqueadas, aprovacoes, execucoes paradas.
- [x] 4.12 Propostas de memoria candidata a partir de tarefa concluida (fecha 3.10).
- [x] 4.13 Refator: `Servico` dividido em mixins (1133 -> 764 linhas) sem mudar a API.
- [x] 4.14 Orquestrador publica no quadro, sozinho e de forma idempotente: bloqueio -> apontamento ao operador (prio 2), conclusao -> evento ao master, falha/expiracao -> apontamento ao master. Melhor esforco; origem `sistema` so emite evento/apontamento (invariante do dominio). Agentes reais ainda nao publicam respostas proprias (precisa MCP, 4.7c).
- [x] 4.23 Dados do usuario fora do Git (perfil), migracao nao destrutiva, registro de preferencias, menu de configuracoes (geral/avancado), politica de pastas permitidas/proibidas e limite de requisicoes configuravel. ADR-014.
- [x] 4.15 Configuracao por parte do sistema (modelo e esforco), lista de modelos da conta, aplicada por sessao ACP v3 com falha fechada. ADR-012.
- [x] 4.16 Revisao do esquema sob demanda (`POST /revisoes`) com fatos medidos.
- [x] 4.17 Painel estilo IDE: Kanban, quadro de comunicacao, grafo/notas (Obsidian), ferramentas, integracoes e configuracao; CSP e a11y basica; verificado no navegador.
- [x] 4.18 Ferramentas de servicos locais: `vault.indexar`, `agenda.ler_ics`, `email.ler_mbox`; registro de integracoes (`/integracoes`).
- [x] 4.19 Refator de `Servico` em mixins; testes de migracoes (ciclo completo, sem deriva) e do painel estatico.
- [x] 4.20 Integracoes de rede configuraveis pela tela, desligadas por padrao, segredo so no ambiente: Jira, GitHub e agenda por URL .ics (somente leitura). ADR-013.
- [x] 4.20b Aprovado pelo usuario. Trello, Notion, Google Agenda e Gmail (API, OAuth somente leitura) + escrita como ACAO EXTERNA (Jira comentar/transicionar, GitHub comentar, Trello criar cartao) com aprovacao por acao e adendo. IMAP nao feito (API cobre o caso). Nenhum servico real validado ainda (exige credenciais).
- [x] 4.21 CI (GitHub Actions): lint, testes, painel em navegador real com interacoes, layout estreito e axe-core WCAG 2.1 AA (0 violacoes nas 6 vistas). Teste com leitor de tela de verdade continua manual.
- [x] 4.22 Ligacoes tipadas pela tela (secao na nota e Shift+arrastar no grafo), ontologia e ACL; migracao 0009.
- [x] 4.8 Medido no corpus real do usuario sem rotulagem manual (metodo CodeSearchNet, 300 perguntas, ~2.300 arquivos): busca atual 0,137 recall@5 contra 0,067 do baseline. A rotulagem manual (Memoria > Avaliar a busca) segue disponivel para perguntas reais.
- [~] 4.9 Medido: embeddings sozinhos perdem (0,106); hibrido RRF ganha (0,177, +29%). Adocao como recurso opcional pesado aguarda aprovacao (modelo ~220 MB, ~230 s de indexacao por 2.300 arquivos).
- [x] 4.24 Perfil de trabalho dos agentes: nivel de autonomia (restrito/liberado/total), metodos como tags combinaveis e observacoes guia. ADR-016.
- [x] 4.25 Busca web (Brave/SearXNG) e leitura de pagina restrita a resultados recentes ou dominios liberados.
- [x] 4.26 Hospedagem: app web local instalavel (PWA) e `python -m forja --abrir`; tema estilo IDE, responsivo e com movimento reduzido.
## Gate Fase 1
Atingido: tarefa simulada percorre rascunho -> ... -> concluida com estado consistente, evidencia (simulada),
artefato integro, eventos via SSE e logs — verificado por testes e pelo smoke contra servidor real.

## Proxima fase (2 — Kiro ACP)
Pre-condicao: confirmar entitlement empresarial e disponibilidade de `kiro-cli acp`. Implementar cliente ACP V3
atras de `ProvedorAgente`, com mock JSON-RPC antes de integracao real. Nao usar login empresarial em CI.
