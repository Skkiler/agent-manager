# ADR-006 — Aprovação por ação, agrupada, com adendo

- Status: aceito (Fase 2)
- Contexto: o Kiro pede permissão por chamada de ferramenta (`session/request_permission`). Pedir ao operador por comando
  gera fadiga e decisões sem contexto. Requisito do usuário: perguntar por **ação** ("Posso excluir forçadamente as pastas X?"),
  agrupar itens relacionados em um só pedido e permitir adendos.
- Fato observado no Kiro CLI 3.1.0 real: o pedido de permissão traz apenas `title/status/toolCallId`; `kind`, `rawInput`
  e `locations` chegam antes, no `tool_call`. O cliente memoriza os `tool_call` por `toolCallId` e enriquece o pedido.
  Opções reais: `accept/always-accept/reject/always-reject` (kinds `allow_once/allow_always/reject_once/reject_always`).
- Decisões:
  1. `descrever_acao` (puro, testado) classifica a chamada (excluir_forcado, publicar, modificar_arquivos, ...) e gera a pergunta e o risco.
  2. `MediadorPermissoes` agrupa pedidos simultâneos (janela curta) em UM pedido de aprovação com N itens; o operador aprova
     todos, alguns (`itens_aprovados`) ou nenhum, com `adendo` e `lembrar_na_execucao`.
  3. Ações que tocam segredos/credenciais são **negadas automaticamente**, sem perguntar e sem aparecer como aprovável.
  4. Nunca se usa `allow_always` do Kiro: a memória de decisões é da Forja, limitada à execução, auditável (eventos/DB).
  5. Timeout, cancelamento, expiração e reinício **negam** (nunca aprovam por omissão); nada fica pendente sem worker.
  6. Negar um grupo não cancela a tarefa: o agente decide como prosseguir sem a ação. (Aprovação *pré-execução* negada cancela.)
  7. Adendo pré-execução entra no prompt; adendo dado durante a execução é entregue em UM turno de acompanhamento
     (ACP não permite injetar no meio do turno), contado em `chamadas_modelo`.
  8. Decisão em lote (`/aprovacoes/decidir-lote`) para vários pedidos de uma vez.
- Consequências: menos interrupções e mais contexto por decisão; custo de 1 chamada extra quando há adendo durante a execução.
- Limite: a classificação de comandos é heurística (regex). É uma ajuda de comunicação e de risco, não uma barreira de
  segurança: a barreira real é o sandbox isolado, o modo somente leitura e a negação por padrão.
