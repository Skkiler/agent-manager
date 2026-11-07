# Estado da implementacao

**Atualizado:** 2026-11-06. **Fases 0 e 1 testadas; Fase 2 implementada e testada ate onde nao exige login.**
Padrao de agente: **mock SIMULADO** (evidencias simuladas nao comprovam trabalho real). O provedor Kiro real so e usado com
`APP_KIRO_ACP_ENABLED=true` e ainda **nao foi exercitado com sessao autenticada** (depende de `kiro-cli login` pelo usuario).

## Ambiente verificado (esta maquina e o alvo)
- Python 3.13.5; Git 2.50.0; Kiro IDE 1.4.121; **Kiro CLI 3.1.0** em `%LOCALAPPDATA%\Kiro-Cli` (nao esta no PATH da sessao do agente; o
  adaptador tambem procura nesse local).
- **Kiro CLI nao autenticado** (`autenticado=false`). O login empresarial e acao do usuario; o agente nao o executa.
- Aviso do CLI: o terminal desta sessao roda como **Administrador**. Recomenda-se usar terminal sem privilegios elevados.
- Workflows: receita read-only em `.kiro/workflows/`; disponibilidade por conta ainda nao confirmada.
- Remoto Git: `origin` -> repositorio publico `Skkiler/agent-manager` (configurado). **Nada foi enviado (sem push).**

## Resultados reais de teste (nesta sessao)
- `python -m pytest` -> **57 passed** (~18 s), exit 0. Cobertura total **85%** (`--cov=forja`).
  Menor cobertura: `diagnostico.py` 23% (exercitado por script real, nao por pytest), `sse.py` 62%, `auth.py` 73%.
- `python -m ruff check forja tests` -> All checks passed.
- **Handshake ACP real** com `kiro-cli acp --agent-engine=v3`: protocolVersion 1, agente "Kiro CLI Agent" 3.1.0, auth method `kiro-login`
  (`test_handshake_real_com_kiro_cli` passa; nao exige login nem consome creditos).
- **Execucao real ponta a ponta** (servidor com `APP_KIRO_ACP_ENABLED=true`, CLI real, sem login): `session/new` rejeitado com
  "Authentication required" -> tarefa `bloqueada` (retomavel), execucao `pausada`, pendencia `reautenticacao_necessaria`,
  eventos `kiro.conectado`/`tarefa.bloqueada`/`execucao.bloqueada`. Comportamento correto; **nenhum prompt foi enviado ao modelo**.
- Smoke da Fase 1 (mock) e testes da Fase 1 continuam passando (35 testes anteriores incluidos nos 57).
- Seguranca: 401 sem token; bind loopback; varredura de padroes de identidade/segredo nos arquivos rastreados: limpa.

## Fases

| Fase | Estado | Evidencia | Proximo passo |
|---|---|---|---|
| 0 — Diagnostico/Git-safe | testado | commit `chore: baseline Fase 0`; scan limpo | scanner dedicado (gitleaks) pendente de aprovacao |
| 1 — Nucleo deterministico | testado | commit `feat: nucleo ...`; 35 testes + smoke | — |
| 2 — ACP/Kiro | em andamento (testado exceto prompt autenticado) | 22 testes ACP; handshake real; bloqueio por auth real | usuario: `kiro-cli login`; entao 2.7 |
| 3 — Memoria/grafo | planejado | — | ontologia, ACL, FTS5, proveniencia |
| 4 — Contexto/ferramentas | planejado | — | recuperacao hibrida; ferramentas N0 |
| 5 — Multiagentes | planejado | — | DAG, scheduler, worktrees, revisao |
| 6 — Aprendizado | planejado | — | EWMA, roteamento, N1 opcional |
| 7 — UI/LAN | planejado | — | painel pixel art; tunel/HTTPS |
| 8 — Open source | planejado | — | licenca, CI, SBOM, release |

## Componentes da Fase 2
- `forja/adapters/kiro_acp/cliente.py` — JSON-RPC/stdio; permissoes negadas; capacidades minimas; erros tipados.
- `forja/adapters/kiro_acp/provedor.py` — `ProvedorKiroAcp`: analise/documentacao apenas; workspace isolado; cancelamento; timeout; redacao.
- `forja/adapters/kiro_acp/diagnostico.py`, `GET /api/v1/kiro/status`, `scripts/diagnostico_kiro.py` — sem consumir creditos.
- `tests/fakes/fake_acp_agent.py` + `tests/test_acp.py` — agente ACP falso (subprocesso real) com 11 cenarios.
- ADR-004; novas variaveis `APP_KIRO_*` em `.env.example`.

## Limitacoes e pendencias (honestas)
- **Prompt real nao validado**: formato exato de `session/update` do Kiro real (alem do spec ACP) e qualidade das respostas nao verificados.
- Politica empresarial: uso da conta empresarial para projeto pessoal/open source **nao confirmado**. Recomenda-se confirmar antes de ativar.
- Resposta do Kiro e texto de LLM nao verificado deterministicamente; conclusao exige revisao humana. Consumo de tokens indisponivel.
- Um processo `kiro-cli` por execucao (sem pool). Pausa = cancelar turno + reenviar (ACP nao tem pausa; `loadSession=false`).
- Modos de escrita bloqueados no provedor Kiro ate sandbox/worktree + aprovacao (Fase 5).
- Scanner dedicado (gitleaks/detect-secrets) nao instalado; sem CI. O autor dos commits usa a identidade do `git config` global do usuario
  (nome/e-mail ficarao visiveis no repo publico apos push).
- Token SSE por query string apenas em `/eventos/stream` (EventSource nao envia cabecalho).

## Retomada sem reprocessar
1. `pip install -r requirements-dev.txt`; `python -m pytest` -> 57 passed.
2. `python scripts/diagnostico_kiro.py` para ver CLI/login/handshake.
3. Apos `kiro-cli login` (acao do usuario): definir `APP_KIRO_ACP_ENABLED=true`, rodar uma tarefa de analise sintetica e registrar o
   resultado real aqui (tarefa 2.7). Nao usar login empresarial em CI publica.
4. Em seguida: 2.8 (agentes/skills/Workflow) e iniciar Fase 3 (memoria FTS5 com namespaces/ACL).
