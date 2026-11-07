# ADR-004 — Adaptador Kiro ACP V3: escopo seguro da Fase 2

- Status: aceito (Fase 2)
- Contexto: Kiro CLI 3.1.0 instalado; `kiro-cli acp --agent-engine=v3` fala JSON-RPC 2.0 por linhas em stdio.
  Handshake real verificado (protocolVersion 1). A conta pode estar sem login ou sob politica empresarial.
- Decisoes:
  1. Cliente proprio (`forja/adapters/kiro_acp/cliente.py`) atras de `ProvedorAgente`; stdout = protocolo, stderr separado e sanitizado.
  2. Capacidades de cliente minimas (sem `fs` nem `terminal`): pedidos `fs/*`/`terminal/*` recebem erro -32601; nenhuma requisicao fica pendente.
  3. Permissoes de ferramenta **negadas por padrao** (opcao `reject_*`, senao `cancelled`). Nunca `--trust-all-tools`/`--trust-tools`.
  4. Workspace entregue ao Kiro e um diretorio **vazio e isolado** (`data/kiro-workspace`), nao o repositorio.
  5. Somente `modo` = analise/documentacao. Modos de escrita ficam fechados ate haver sandbox/worktree e aprovacao (Fase 5).
  6. Autenticacao pertence ao `kiro-cli` (`auth-method cli`). Sem login: tarefa vai a `bloqueada` com `reautenticacao_necessaria`,
     retomavel. A plataforma nunca executa o login, nem le/grava token. `KIRO_API_KEY` nao e usado no MVP.
  7. ACP nao tem "pausa": pausa = `session/cancel` do turno + checkpoint; retomada reenvia o prompt.
  8. Consumo de tokens nao e exposto: `fonte=indisponivel`, nunca estimado.
- Consequencias: resposta do Kiro e texto de LLM nao verificado deterministicamente; vira evidencia `kiro_resposta`
  (simulada=false) mas exige revisao humana. Cada execucao abre um processo `kiro-cli` (sem pool ainda).
- Pendente: validacao com sessao autenticada real (acao do usuario); politica empresarial de uso pessoal/open source.
