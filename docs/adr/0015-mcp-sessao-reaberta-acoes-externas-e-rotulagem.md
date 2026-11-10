# ADR-015 — MCP da Forja, sessão reaberta, ações externas com aprovação e rotulagem da busca

- Status: aceito
- Contexto: itens 4.7c, 2.9, 4.20b e 4.8. O agente Kiro não enxergava as ferramentas da Forja. Cada retomada abria sessão nova.
  A escrita em serviços e os conectores de produtividade estavam planejados, e a precisão da busca no corpus real nunca tinha sido medida.

## Decisões

1. **MCP stdio, nunca rede** (`forja/mcp/servidor.py`, `python -m forja.mcp`): quem inicia o processo é o Kiro, e o MCP só fala com a API
   da Forja em `http://127.0.0.1` (outros hosts são recusados na partida). São 5 ferramentas com descrições curtas: listar/executar ferramentas da Forja,
   buscar na memória, publicar/ler no quadro. A API continua sendo a autoridade (política de pastas, integrações, aprovações).
   A origem no quadro é fixa (`agente:kiro`) e `comando` é proibido. O token é lido do perfil pelo próprio MCP e nunca passa pelo Kiro.
   É anexado à sessão por `session/new.mcpServers` apenas com a preferência `kiro_mcp_ativo` (padrão **desligado**).
2. **Prontidão do MCP:** o kiro-cli 3.1.0 conecta o MCP *depois* de responder `session/new` (cerca de 2 a 4 s). Um prompt enviado antes chega ao agente
   sem as ferramentas (falha reproduzida no Kiro real). O provedor espera o sinal observado (o custo de ferramentas em `breakdown`
   aumenta), com teto de 15 s. Se o sinal não vier, segue e registra `kiro.mcp {pronto: false}`. Esse sinal não é documentado: se uma versão do Kiro
   mudar o comportamento, o pior caso volta a ser o anterior (agente sem as ferramentas), nunca um travamento.
3. **`session/load` na retomada (2.9):** só quando o agente anuncia `loadSession` e o checkpoint tem `session_id`. As notificações de replay do
   histórico são descartadas (não viram resposta nem eventos de ferramenta). Com a sessão reaberta, o prompt de retomada leva só a
   resposta nova. Se a sessão não existir mais, cai para sessão nova com o prompt completo. Preferência `kiro_reusar_sessao` (padrão ligado).
4. **Ações externas (escrita, 4.20b):** o agente só **propõe** (ferramentas `*.propor_*`). A proposta exige integração pronta e `permitir_escrita`
   ligado, é validada sem rede e vira uma frase ("Posso comentar na issue ABC-1 do Jira: «…»?") e um aviso no quadro. O operador aprova ou nega, com adendo registrado.
   A execução acontece uma única vez (transição atômica por versão) e revalida tudo. Conteúdo que parece credencial é barrado antes de sair.
   Propostas expiram em 24 h, e uma execução interrompida por reinício **não é repetida**. O caminho de leitura (`executar`) recusa ações de escrita.
5. **Conectores novos:** Trello (leitura e criar cartão), Notion (consulta de bases), Google Agenda e Gmail (OAuth com refresh token de escopo
   somente leitura, token de acesso só em memória; Gmail mascara remetentes e limita a 10 mensagens). Todos nascem desligados, com hosts fixos e
   itens permitidos explícitos. IMAP não foi implementado: a API do Gmail cobre o caso com escopo menor, e o `.mbox` continua para uso offline.
6. **Rotulagem da busca (4.8):** o usuário escreve perguntas reais e marca o que é relevante entre candidatos que juntam baseline e busca nova,
   em ordem embaralhada (sem viés). Os rótulos ficam no banco do perfil (fora do Git) e guardam só a pergunta e os IDs. Abaixo de 15 perguntas, a medição
   avisa que a amostra é pequena.

## Medido (Kiro real, kiro-cli 3.1.0, conta empresarial com MCP liberado)

- `session/load` funciona entre processos: uma sessão reaberta lembrou um código combinado na sessão anterior.
- MCP: custo fixo de cerca de 214 tokens na sessão. Pedindo explicitamente `repo.mapa`, a tarefa de mapear o repositório gastou 0,280 crédito, contra
  0,384 de média sem MCP (n = 1 contra 3, só indicativo). Espontaneamente, o agente **não** escolheu as ferramentas da Forja em nenhuma das execuções:
  por isso o MCP continua desligado por padrão.

## Rejeitado

- MCP via HTTP/porta, `trust-all` ou aprovação automática de ferramentas MCP. Cada chamada `@forja/...` continua passando pelo mediador, agora com uma descrição
  em linguagem natural.
- Escrita direta por ferramenta de agente. Reexecutar automaticamente uma escrita interrompida.
