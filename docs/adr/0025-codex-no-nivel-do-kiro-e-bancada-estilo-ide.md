# ADR-025: Codex no nível do Kiro (regras na própria sessão) e bancada estilo IDE com três visualizações

- Status: aceito
- Data: 2026-11-18
- Origem: pendências do `docs/RELATORIO_AVALIACAO_2026-11-18.md` (Codex, coordenação, ferramentas e V1-V9 da análise visual) e
  pedido do usuário na mesma data (liberar Codex e Kiro com segurança; tela com editor, chat e visualização agêntica).

## Contexto

Depois do ADR-024, o Codex ainda dependia só da vigia da Forja (cancelar o turno quando ele citava um caminho fora da pasta). O
usuário pediu que o próprio Codex se policie. No painel, os painéis cobriam o conteúdo (V3), não havia editor, terminal, Git nem
Docker (V8) e a hierarquia visual era fraca (V1, V2, V5-V7).

## Decisão

### Codex
- A sessão do Codex recebe `CODEX_CONFIG` com `developer_instructions` (o mesmo escopo do perfil do Kiro + regra de pastas +
  "não contorne; explique em Decisões para você") e `shell_environment_policy = {inherit: core, exclude: segredos, FORJA_*, APP_*}`.
  Testado com o Codex real: pedido para ler arquivo fora da pasta terminou em recusa do próprio agente, sem chamada de ferramenta.
- A vigia em tempo real continua como segunda camada.
- Rejeitados (testados no codex-acp 2.7.0 / Windows): `approval_policy` (removido pela OpenAI; "Internal error"), perfis
  `[permissions]` (sessão recusada), hooks `PreToolUse` do Codex (confiados por `_codex/hooks/trust`, mas nunca executados),
  regras `execpolicy` (só valem fora do sandbox) e `CODEX_HOME` separado (exigiria copiar `auth.json`).
- O MCP da Forja vale também para o Codex (mesma preferência `kiro_mcp_ativo`); títulos `mcp.forja.*`/`mcp__forja__*` são
  reconhecidos pelo classificador. Provado: o Codex chamou `forja_listar_ferramentas` pelo provedor e recebeu 17 ferramentas.
- Kiro: a sessão desliga `contentCollection` quando o agente oferece a opção (evento `kiro.privacidade`).

### Orquestração e ferramentas
- Coordenação: consulta por `json_extract` (sem varrer 5000 tarefas), trava única na consolidação do lote e tarefa
  `bloqueada` há mais de 24 h deixa de segurar o lote.
- Laço: duas chamadas se alternando (A/B) também interrompem o turno. Roteamento: pedidos amplos de leitura e mudanças mínimas
  (typo, renomear, comentário) podem ser "simples".
- Ferramentas: `texto.amostra` com `buscar`, outline de CSS, fim de funções JS por chaves e teto de 30 s por chamada.

### Bancada (painel)
- Três visualizações no mesmo shell: **Editor** (estilo VS Code/Kiro: barra de atividades, barra lateral, abas, trilha, painel
  inferior e barra do agente à direita), **Chat** (a barra do agente ocupa a tela, com a lista de conversas à esquerda, como no
  app do Codex) e **Agentes** (escritório em pixel art desenhado em canvas, inspirado no Pixel Agents, com arte própria).
- Painéis **empurram** o conteúdo e têm divisórias arrastáveis (mouse e teclado), com tamanho e estado no `localStorage`. Em
  tela estreita (≤ 760 px) voltam a ser gavetas sobrepostas.
- Editor próprio (textarea + camada de realce + calha), sem Monaco/CodeMirror: sem build, sem dependências externas e dentro da
  CSP `default-src 'self'`. Prévia de Markdown pelo renderizador DOM existente e de HTML em `iframe sandbox` sem scripts.
- API nova `/api/v1/area/*` (`AreaTrabalho`), sempre pelas pastas do projeto: segredos nunca abrem, salvam, aparecem em busca ou
  Git; pasta de consulta é somente leitura; salvar usa o sha lido (conflito 409, nada sobrescrito); terminal roda um comando
  por vez no sandbox da Forja, com ambiente limpo, 120 s e recusa de comando que lê segredo (mesmo classificador do mediador),
  e pode ser desligado (preferência `terminal_ativo`); Git só lê, prepara e faz commit (sem push); Docker só lista, mostra logs e
  inicia/para/reinicia (nunca `inspect`/`exec`).
- Logomarca vetorizada (`icone.svg`, `logo.svg`) a partir da imagem do usuário: bigorna branca em "F" sobre petróleo `#002838`.

## Consequências
- O inspetor do painel (`scripts/inspecionar_painel.py`) passa a verificar painéis que empurram, divisórias, editor, terminal,
  paleta e as três visualizações; continua rodando no CI com axe-core.
- O editor é leve: sem IntelliSense, multi-cursor ou LSP; arquivos acima de 200 KB abrem sem realce e acima de 2 MB não abrem.
- O Codex continua sem perfis de permissão nativos: a proteção é instrução da sessão + ambiente mínimo + vigia + varredura de
  segredos antes de rodar.
