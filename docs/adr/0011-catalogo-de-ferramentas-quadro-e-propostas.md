# ADR-011 — Catálogo de ferramentas N0, quadro de comunicação, painel de controle e propostas de memória

- Status: aceito (Fase 4)
- Contexto: agentes precisam de ferramentas baratas e seguras, de um canal tipado entre master, operador e agentes
  (orientação §7.4, §13) e de um jeito de alimentar o segundo cérebro sem validar nada às cegas.
- Decisões:
  1. **Catálogo** (`forja/ferramentas/catalogo.py`): cada ferramenta tem id, risco, schema de entrada (Pydantic, `extra=forbid`),
     fallback e custo observado. Somente leitura, sem shell, sem rede, sem escrita. Falha inesperada vira erro genérico (500) e o
     detalhe vai só ao log. `SemResultado` aciona o fallback; recusas de segurança **nunca** acionam fallback.
  2. **Guarda de caminho único** (`caminhos.resolver_dentro`): contenção léxica antes de tocar o disco (para não revelar se algo
     existe fora da raiz: 422 igual para existente e inexistente), depois recusa de links simbólicos, arquivos sensíveis e tipo errado.
     Ferramentas de arquivo só funcionam em `APP_TOOLS_ROOTS` (padrão vazio = desligadas).
  3. **Quadro** (`mensagem_quadro`, migração 0006): mensagem tipada (`comando|evento|apontamento|pergunta|resultado`), prioridade
     1 (mais urgente) a 5, `payload` ≤ 4000 car. (envie referências, não conteúdo), validade, `dedup_key` **por origem** (um agente não
     suprime mensagem de outro), entrega única por destinatário, difusão (`todos`) só para evento/apontamento. `comando` só de
     master/operador. Eventos SSE levam apenas ids e metadados.
  4. **Painel de controle** (`GET /controle/painel`): urgentes do quadro, tarefas bloqueadas aguardando decisão, aprovações
     pendentes e execuções vencidas/sem progresso, em uma resposta compacta com alertas.
  5. **Propostas de memória** (`POST /tarefas/{id}/propor-memoria`): memória **candidata** determinística (sem LLM), com fonte e
     referências, idempotente. Evidência simulada é rotulada e não é vinculada. Nunca valida: a promoção segue exigindo evidência real.
  6. **Scanner de segredos** próprio (alta confiança + literal atribuído a nome sensível), pois o redator de logs marcava qualquer
     `token = ...` (8 achados em `forja/`, 7 falsos; agora 1).
- Limites: a API tem um único token de operador, então `origem` no quadro é **declarada** pelo chamador; a regra "agente não comanda"
  protege o fluxo mediado pelo controlador, não impede um chamador autenticado de se declarar master. Heurísticas de segredo não
  provam ausência. Sem timeout por ferramenta (as entradas têm tetos de tamanho).
- Refator associado: `Servico` foi dividido em mixins (`aprovacoes.py`, `conversa_contexto.py`); 1133 → 764 linhas, API pública igual.
