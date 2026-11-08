# Estado da implementacao

**Atualizado:** 2026-11-07. **Fases 0 e 1 testadas. Fase 2 (Kiro ACP) validada com o Kiro real**, incluindo prompt autenticado,
permissao negada e permissao aprovada. Padrao de agente continua sendo o **mock SIMULADO**; o Kiro real so e usado com
`APP_KIRO_ACP_ENABLED=true`.

## Regra de publicacao (repositorio publico)
O repositorio publica apenas **logica, ferramentas, controle e orquestracao**. Nunca sobem: credenciais, tokens, dados internos
da empresa, conteudo do "segundo cerebro"/memoria privada, bancos, logs, respostas reais do Kiro. `data/`, `.env`, `*.sqlite3`,
`knowledge/{privado,pessoal,empresa,terceiros}/`, `memoria-local/`, `segundo-cerebro/` estao em `.gitignore` e `.kiroignore`.
O uso do Kiro empresarial para este projeto foi **informado pelo usuario como aprovado** para desenvolvimento.

## Ambiente verificado (esta maquina e o alvo)
- Python 3.13.5; Git 2.50.0; Kiro IDE 1.4.121; **Kiro CLI 3.1.0** (`%LOCALAPPDATA%\Kiro-Cli`, fora do PATH da sessao do agente; o adaptador o encontra).
- **Kiro CLI autenticado** (`autenticado=true`, login feito pelo usuario). Metodos anunciados: `aws-builder-id`, `aws-iam-identity-center`.
- Com login, o `initialize` muda: `loadSession=true`, `agentInfo` **ausente** (opcional no ACP), dezenas de extensoes `_kiro/*`.
- Aviso do CLI: o terminal desta sessao roda como **Administrador**; recomenda-se terminal sem privilegios elevados.
- Workflows: receita read-only em `.kiro/workflows/`; disponibilidade por conta ainda nao confirmada.

## Resultados reais de teste (2026-11-07)
- `python -m pytest` -> **98 passed** (~40 s), exit 0, **sem warnings**; cobertura **88%**.
  `filterwarnings` agora trata `ResourceWarning`/unraisable como **erro**: vazamento de conexao/pipe quebra o teste.
- `python -m ruff check forja tests scripts` -> All checks passed.
- Teste de mutacao: com a janela de agrupamento em 0, `test_grupo_uma_pergunta_*` **falha** (2 perguntas em vez de 1) — o teste nao e vazio.
- **Kiro real, prompt autenticado:** `end_turn` em 4,7 s, resposta em portugues.
- **Kiro real, permissao de escrita (sandbox vazio, via provedor + servico):**
  - negada -> `teste.txt` **nao** criado; tarefa passou por `aguardando_aprovacao`; 2 chamadas de modelo (prompt + acompanhamento com adendo);
  - aprovada -> `teste.txt` **criado**; mesma trilha de estados.
  - Com o prompt padrao (somente leitura) o Kiro **nao tentou escrever**, logo nao pediu permissao: o caminho de permissao foi exercitado
    com um prompt de teste que pede a escrita (apenas no script de verificacao, nao no codigo).

## Bugs reais achados e corrigidos nesta etapa
1. Teste de handshake real assumia `agentInfo` (ausente apos login) -> assert corrigido para o garantido pelo protocolo.
2. `permissoes_negadas` contava so cancelamentos, nao rejeicoes selecionadas -> contadores `aprovadas/negadas` corretos.
3. **Seguranca:** deteccao de segredo era ancorada no fim da string e nao pegava `type .env` -> passa a testar cada token do comando.
4. **Fase 1:** o painel nao recebia eventos de aprovacao (SSE enviava `event: <tipo>`, que `onmessage` ignora) -> eventos sem nome; teste de regressao.
5. Pergunta mostrava o alvo duplicado e como caminho absoluto (vazava o diretorio do usuario) -> dedup e caminho relativo ao workspace.
6. Vazamento de conexoes SQLite (engines nunca fechados) e de pipes do `kiro-cli` -> `Repositorio.fechar()` e fechamento de pipes/threads.

## Fases

| Fase | Estado | Evidencia | Proximo passo |
|---|---|---|---|
| 0 — Diagnostico/Git-safe | testado | baseline; ignore reforcado; scan limpo | scanner dedicado (gitleaks) pendente de aprovacao |
| 1 — Nucleo deterministico | testado | 35 testes + smoke | — |
| 2 — ACP/Kiro | testado (2.8 e 2.9 abertos) | 22 testes ACP + 38 de acao/aprovacao; validacao real | 2.8 agentes/skills/Workflow; 2.9 pool/`session/load` |
| 3 — Memoria/grafo | planejado | — | **proxima**: ontologia, ACL, FTS5, proveniencia (dados privados fora do Git) |
| 4 — Contexto/ferramentas | planejado | — | recuperacao hibrida; ferramentas N0 |
| 5 — Multiagentes | planejado | — | DAG, scheduler, worktrees, revisao; modos de escrita |
| 6 — Aprendizado | planejado | — | EWMA, roteamento, N1 opcional |
| 7 — UI/LAN | planejado | — | painel pixel art; tunel/HTTPS |
| 8 — Open source | planejado | — | licenca, CI, SBOM, release |

## Componentes novos (Fase 2b — aprovacao por acao)
- `forja/seguranca/acoes.py` — comando bruto -> pergunta ("Posso excluir forçadamente `build`?"), categoria, risco, segredo.
- `forja/adapters/kiro_acp/mediador.py` — agrupa pedidos simultaneos em UM pedido; lembrar na execucao; nega segredos sem perguntar.
- `forja/adapters/kiro_acp/cliente.py` — cache de `tool_call` (formato real), permissoes em thread propria, pipes fechados.
- `forja/orquestracao/servico.py` — `_solicitar_durante`, `decidir_aprovacao` (parcial/adendo/lembrar), `decidir_lote`, timeout, recuperacao de orfaos.
- Migracao `0002` (origem, itens, escopo, adendo) com dados preservados; painel com "Aprovacoes pendentes"; `POST /aprovacoes/decidir-lote`.
- `.kiro/steering/20-aprovacoes.md` e ADR-006.

## Limitacoes e pendencias (honestas)
- Classificacao de comandos e **heuristica** (regex): melhora a pergunta e o risco, **nao** e barreira. A barreira real e: sandbox vazio,
  somente leitura, negacao por padrao, segredos negados.
- Adendo dado **durante** a execucao so chega ao agente em **um turno de acompanhamento** (ACP nao injeta no meio do turno).
- `rawInput` real de `execute` (comandos) ainda nao observado no Kiro real; so `edit` foi visto. Parsers de comando sao baseados no spec/heuristica.
- Modos de escrita do provedor Kiro seguem fechados (analise/documentacao); a aprovacao existe, mas habilitar escrita real exige worktree (Fase 5).
- Resposta do Kiro e texto de LLM nao verificado deterministicamente; consumo de tokens indisponivel.
- Um processo `kiro-cli` por execucao (sem pool). Scanner dedicado (gitleaks) nao instalado; sem CI.
- Painel (JS) sem teste automatizado de navegador; verificado apenas por revisao e pelos testes de API/SSE.

## Retomada sem reprocessar
1. `pip install -r requirements-dev.txt`; `python -m pytest` -> 98 passed.
2. `python scripts/diagnostico_kiro.py` -> CLI/login/handshake.
3. Proxima tarefa liberada: **Fase 3** (memoria textual com namespaces/ACL/FTS5/proveniencia). Memoria real do usuario nunca entra no Git.
