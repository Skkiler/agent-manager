# ADR-026: Bancada do usuário sem bloqueios, assistente de comandos e perfil de permissão nativo do Codex

- Status: aceito
- Data: 2026-11-18
- Origem: pedido do usuário na mesma data. O usuário final e a Forja podem ler `.env`; só os agentes externos (Kiro e Codex)
  não podem recebê-lo, e nada pode ir para log. Git, Docker e terminal devem ser completos, com avisos em vez de bloqueios.
  Também pediu um assistente de comandos, receitas com variáveis, documentação de comandos por IA, cliente HTTP e as pendências
  do ADR-025.

## Contexto

O ADR-025 aplicou à bancada do usuário as mesmas proteções dos agentes: segredos não abriam, o terminal recusava `cat .env`,
o Git não fazia push e o Docker não fazia `inspect`/`exec`. Isso protegia o usuário dele mesmo e deixava a ferramenta
incompleta. As proteções existem por causa dos agentes de IA externos, não do dono da máquina.

## Decisão

### Política: quem é bloqueado e quem é avisado
- **Usuário (painel, `AreaTrabalho`)**: lê, edita, lista e busca segredos. A resposta marca `segredo: true` e o editor mostra uma
  faixa de aviso. Comandos de Git, Docker e terminal que o assistente classifica como arriscados (risco alto no catálogo, como
  `git push`, `git restore` e `git clean`, ou um dos padrões de perigo) levantam `ConfirmacaoNecessaria` (HTTP 428 com
  `dados.motivos` e `risco`). O painel pergunta e reenvia com `confirmado: true`.
- **Busca do usuário**: pula segredos por padrão e aceita `segredos=true`. Uma busca ampla não deve espalhar senhas pela tela.
- **Agentes**: nada muda. `ProjetosServico.listar`/`buscar-arquivos`, o catálogo de ferramentas e `buscar_texto`
  (`pular_segredos=True`) continuam escondendo segredos. A cópia sem segredos e as regras DENY do Kiro continuam valendo.
- **Ambiente**: terminal, Git e Docker do usuário rodam com `ambiente_usuario()` (`os.environ` menos `APP_*`/`FORJA_*`, que são
  internos do servidor). Os tokens do próprio usuário (por exemplo, para `git push`) chegam ao comando. A saída não é mais
  redigida, porque só o usuário a vê. Os logs guardam só metadados (subcomando e código de saída).
- **Docker**: `-it` e `attach` são recusados por limite técnico (não há TTY), não por segurança. `inspect` e `exec` são permitidos,
  com aviso.
- Rejeitado: manter o bloqueio para o usuário (comportamento do ADR-025) e usar `ambiente_limpo` no terminal do usuário (tirava
  os tokens dele).

### Assistente de comandos (determinístico)
- `forja/assistente/catalogo.json`: 70 comandos (git, docker, python, node, PowerShell, curl, winget), 14 padrões de perigo e 14
  receitas, entre elas `git.vincular_remoto` (add, commit, remote add, branch main, push) com variáveis configuráveis.
- `forja/assistente/comandos.py` tokeniza a linha e devolve explicação por parte, erros de tipo (inteiro, porta, lista de portas,
  escolha, caminho), riscos e sugestões de completar. O painel chama `POST /api/v1/area/comandos/analisar` com espera de 110 ms;
  setas escolhem a sugestão e Tab completa, como no Excel.
- Comandos do usuário e da IA ficam em `<dados_dir>/comandos_usuario.json`, fora do Git. Entradas da IA chegam com
  `origem="ia"` e `revisado=false`. Se o id colidir com um comando padrão, recebe o sufixo `.ia`.
- **Documentação por IA**: o painel cria uma tarefa de análise preparada no projeto `forja-comandos` (mesmo padrão da revisão).
  Quando a tarefa termina, o usuário importa o bloco `json` do artefato. Nada entra no catálogo sem a importação do usuário.
- Rejeitado: LLM a cada tecla (custo e latência) e o catálogo dentro do código Python (o usuário não conseguiria estender).

### Bancada
- Painel Git completo (branches, remotos, stash, à frente/atrás, stage/unstage, commit, descartar, qualquer subcomando com aviso)
  com dicas para erros comuns e atalho para as receitas. Painel Docker com containers, imagens, volumes, redes e compose.
- Cliente HTTP (estilo Postman) pelo servidor (`httpx`), com método, cabeçalhos, corpo e histórico.
- Diff lado a lado: algoritmo de Myers em JS (`diff.js`), conferido contra 3000 casos aleatórios no Node.
- IntelliSense leve: palavras do arquivo, palavras-chave da linguagem e trechos, mais F12/Ctrl+clique para a definição pelo
  `estrutura_codigo`. Rejeitado: LSP real (processo pesado por linguagem e instalação fora do controle da Forja).
- Atalhos (Ctrl+/), símbolos do arquivo na paleta (`@`, Ctrl+Shift+O) e "Dica" na tela de boas-vindas.
- Dados de demonstração (`semear_demo.py`, agente simulado) agora com acentos.

### Orquestração e ferramentas
- Teto diário de créditos: preferência `limite_creditos_dia` (0 = desligado). `iniciar_execucao` confere
  `CustosServico.teto_atingido()` e levanta `OrcamentoExcedido` antes de chamar o agente.
- Ferramentas novas para agentes (37 no total): `deps.listar`, `json.consultar`, `tabela.resumir`, `links.verificar`.

### Codex: perfil de permissão nativo
- `CODEX_CONFIG` passa a levar `default_permissions = "forja"` e um perfil que estende `:workspace` com `deny` para todos os
  globs de segredo de `forja.seguranca.sensiveis.GLOBS` e para `~/.ssh`, `~/.aws`, `~/.gnupg`, `~/.kube` e `~/.docker`.
- Sondado no codex-acp 2.7.0 / Windows: a sessão aceita o perfil e o sandbox aplica de verdade (um arquivo inocente listado como
  `deny` deixou de ser lido). Rejeitados: `:root` deny (sessão recusada com "Internal error") e `~` deny (o `session/new` não
  respondeu). No modo de escrita, arquivos fora da pasta continuam legíveis; a vigia da Forja cobre esse caso.
- A recusa do Codex em pastas com segredos continua (falha fechada), porque o perfil não cobre caminhos fora da pasta como as
  regras do Kiro cobrem.

### Acessibilidade
- O NVDA não está instalado na máquina de desenvolvimento. A auditoria usou a árvore de acessibilidade do Chromium
  (`aria_snapshot`) e uma volta completa de Tab em 9 vistas, além do axe-core. Isso não substitui um teste com leitor de tela real.

## Consequências
- O usuário consegue fazer tudo pelo painel. O custo é que um clique confirmado executa a ação; o aviso precisa ser claro.
- O agente continua sem ver segredos, e a política fica explícita em um lugar: bloqueio é para agentes; usuário recebe aviso.
- O catálogo de comandos precisa de manutenção. A documentação por IA ajuda, mas só entra com revisão do usuário.
- Pendentes: teste com NVDA real, LSP opcional e leitura fora da pasta pelo Codex no modo de escrita (coberta só pela vigia).
