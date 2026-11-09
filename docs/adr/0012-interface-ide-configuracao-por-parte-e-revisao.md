# ADR-012 — Interface estilo IDE, configuração por parte do sistema e revisão do esquema

- Status: aceito (Fase 4)
- Contexto: o painel era uma página única. O operador precisa ver tarefas como num quadro Jira, o quadro de comunicação, o
  segundo cérebro como grafo/notas (estilo Obsidian), configurar modelo de IA por parte do sistema, usar ferramentas e serviços
  gratuitos e pedir uma revisão periódica do esquema, com mais ou menos detalhe.
- Decisões:
  1. **Shell estilo VS Code/Kiro** (barra de atividades, lateral, área principal, conversa/decisões à direita, painel inferior
     com eventos/controle/oficina, barra de status). JS em módulos ES sem framework e sem build. Atalhos Ctrl+B, Ctrl+Shift+B, Ctrl+J.
     Nível **Simples/Avançado** (`data-nivel`) esconde campos técnicos sem mudar a funcionalidade.
  2. **Segurança do front**: CSP por `<meta>` (`default-src 'self'`, sem inline script, sem `unsafe-eval`), nenhum
     `innerHTML`/`eval` (teste estático), conteúdo do backend só por `textContent`, token só em `api.js`/sessionStorage. A Oficina
     pixel art só projeta estado real e pode ser desligada. Respeita `prefers-reduced-motion`.
  3. **Kanban** com colunas e ações vindas do servidor (a UI não inventa transições). Arrastar só vale para ações já permitidas
     (preparar, cancelar); o resto é recusado com aviso. Há botões como alternativa ao arrastar.
  4. **Grafo**: wikilinks `[[...]]`, `refs`, arestas tipadas e links não resolvidos (nós fantasma); ACL de namespace antes de montar
     qualquer nó; backlinks por nota; leitura e edição pelas rotas de memória (editar memória validada a devolve a candidata).
  5. **Configuração por parte** (`execucao`, `revisao`; `contexto` e `ferramentas` são determinísticas e recusam modelo): modelo e
     esforço, com concorrência otimista. A lista de modelos vem da conta (`kiro-cli chat --list-models`, com custo em créditos).
  6. **Revisão do esquema** (`POST /revisoes`): fatos medidos + critérios que exigem fontes; cria e prepara a tarefa e só executa
     com pedido explícito (consome créditos).
- **Descobertas com o Kiro real (3.1.0, engine v3)** que mudaram a implementação:
  - `--model` e `--effort` são **recusados** no engine v3 (o processo sai com código 2). O modelo é definido **por sessão** com
    `session/set_config_option` (`model`, depois `effortLevel`); as opções de esforço dependem do modelo.
  - O agente **aceita um modelo inexistente em silêncio**. Por isso o modelo é validado contra a lista da própria sessão e, se
    ausente, a execução é **bloqueada** (falha fechada, 0 chamadas ao modelo) em vez de rodar num modelo diferente do escolhido.
- Limites: a UI foi verificada num navegador real (Edge via Playwright: 6 vistas e 18 interações), mas não há teste de regressão visual
  automático nem de leitor de tela; `origem` do quadro é declarada (token único); grafo com mais de ~500 nós é truncado.
- Integrações: ver ADR-011 e `docs/arquitetura/ferramentas-planejadas.md`. Nada com rede/OAuth foi implementado; ficam planejadas
  até o operador aprovar escopo e onde guardar credenciais.
