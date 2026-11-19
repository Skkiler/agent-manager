# ADR-027: Reciclagem de sessões, conhecimento integrado, autocompletar de código, LSP e agentes fora da pasta

- Status: aceito
- Data: 2026-11-19
- Origem: pedido do usuário depois do ADR-026: reciclar sessões antigas guardando o relato no segundo cérebro; validar se grafo,
  segundo cérebro e caderno conversam sem retrabalho; autocompletar de código (Python, C#, JavaScript, HTML/CSS) configurável e
  extensível por IA; LSP; polimento visual; e deixar o Kiro e o Codex lerem fora da pasta quando o usuário pedir.

## Contexto

A validação pedida encontrou estas lacunas (todas com teste em `tests/test_rodada5_conhecimento_editor.py`):

- O caderno ficava preso à tarefa: nada dele chegava ao segundo cérebro, e a consulta do caderno não via o que outras sessões
  do projeto já tinham aprendido.
- O registro ao concluir (`EstudoServico.registrar`) criava uma nota por tarefa real concluída, mesmo sem conteúdo útil.
- `GrafoServico.links` ignorava as ligações tipadas (`SUBTOPICO_DE`, `RELACIONADO_A`). O tópico do projeto não aparecia
  como vizinho das notas.
- O contexto inicial usava só os namespaces configurados (`publico`). As notas do próprio projeto, em
  `pessoal/projetos/<projeto>`, nunca entravam.
- `forja_propor_nota` criava nota mesmo quando já existia outra igual.

## Decisão

### Reciclagem de sessões antigas (`orquestracao/reciclagem.py`, tabela `reciclagem`, migração 0015)
- Sessão antiga: tarefa terminal ou sub-master encerrado, parada há mais de `reciclagem_dias` (padrão 30; 0 desliga). Roda
  em segundo plano a cada 6 h e também pela tela (prévia e "Reciclar agora").
- O relato é determinístico: estado final, resultado, decisões do desenvolvedor, caderno por tipo, pendências e
  arquivos alterados.
- Uma nota só é criada quando há valor (pontos ≥ 3). Abaixo disso a sessão só é arquivada (`sem_valor`).
- Sem retrabalho:
  - a nota da própria tarefa é **enriquecida** com o que falta;
  - uma nota parecida do mesmo projeto (Jaccard ≥ 0,5) ganha uma seção "Também";
  - uma nota parecida já validada deixa a sessão como **coberta**;
  - só sem nada parecido se cria nota nova.
- Grafo: a nota nova fica pendurada no tópico "Projeto: X" (`SUBTOPICO_DE`) e ligada à nota mais próxima (`RELACIONADO_A`).
- `reciclagem_compactar` controla o que sai do banco depois da cópia:
  - `nada` (padrão);
  - `caderno`;
  - `detalhes`: caderno e eventos `kiro.ferramenta`, `agente.passo` e `kiro.prompt_montado`.
- Pedido, respostas, decisões e artefatos nunca são apagados.

### Ponte caderno ↔ segundo cérebro ↔ grafo
- `GET /tarefas/{id}/caderno?amplo=true&q=` (`ConhecimentoTarefa`) devolve:
  - o caderno da tarefa;
  - as notas do namespace do projeto;
  - um salto no grafo a partir delas.
- O MCP `forja_caderno_consultar` usa o modo amplo quando há `q`.
- O registro ao concluir passa a incluir o caderno (uma vez) e é pulado quando não há conteúdo além de evidências.
- `links()` inclui as ligações tipadas.
- `POST /memorias?evitar_duplicata=true` devolve a nota parecida em vez de criar outra. `forja_propor_nota` usa esse modo.
- Contexto: `contexto_memoria_projeto` (padrão ligado) acrescenta só o namespace do projeto da tarefa. Outros projetos ficam
  de fora.

### Autocompletar de código (`assistente/codigo.py`, `assistente/codigo/*.json`)
- O catálogo é organizado em ramos por linguagem: 30 ramos e 969 itens, entre Python, C#, JS/TS, HTML e CSS.
  - Cada item tem assinatura, explicação em português e trecho a inserir.
  - Ramos de biblioteca só ligam quando o arquivo importa a biblioteca (`detectar`).
- O cliente (`js/completar.js`) entende o contexto da posição:
  - membro depois de `obj.`, com apelidos como `import pandas as pd`;
  - tag depois de `<` e atributo dentro da tag;
  - propriedade, valor e regra `@` no CSS.
- O cliente filtra localmente e mostra a explicação do item marcado ao lado. Abrir parênteses mostra a assinatura.
- Usuário e IA estendem o catálogo em `<dados>/codigo_usuario.json`. A IA cria um ramo novo ou atualiza um ramo existente por
  uma tarefa de análise preparada no projeto `forja-codigo`. O resultado só entra quando o usuário importa, e chega marcado
  como não revisado.
- Configurações > Editor:
  - ligar/desligar;
  - sugerir enquanto digita;
  - fontes (LSP, catálogo, trechos, palavras);
  - ramos desligados;
  - atraso e tamanho da lista;
  - assistente do terminal ligável (`terminal_assistente`).

### LSP (`adapters/lsp/`)
- Cliente JSON-RPC por stdio, sem dependência nova. Recursos: completar, explicar (hover + assinatura), definição e diagnósticos.
- Servidores:
  - Pyright;
  - typescript-language-server com `typescript@5`, porque o TypeScript 7 não traz `tsserver.js` (medido);
  - servidores HTML/CSS do VS Code;
  - csharp-ls (exige .NET SDK).
- Instalação pela tela, com confirmação, em `<dados>/lsp`, sem mexer no Node/.NET do sistema. As instalações rodam uma de
  cada vez: duas ao mesmo tempo corromperam o `package.json` (medido). Um servidor que já esteja no PATH também é usado.
- Os servidores sobem sob demanda: no máximo `lsp_max_servidores` (padrão 2) e fecham após 10 min sem uso.
- Rodam só para o usuário, com raiz na pasta do projeto e o ambiente do usuário sem `APP_*`/`FORJA_*`.
- URIs normalizados: o Pyright publica `file:///c%3A/...` para `file:///C:/...`. Sem isso, os diagnósticos se perdiam
  (medido).
- Rejeitado: Monaco/CodeMirror com LSP no navegador (build e dependências externas, contra a CSP `default-src 'self'`).

### Agentes fora das pastas do projeto (`acesso_fora_pasta`)
- `perguntar` (padrão):
  - Kiro: lê sem perguntar o caminho que o usuário citou no pedido (`seguranca.pastas.caminhos_citados`); o resto pergunta.
  - Codex: não consegue pedir antes, então pode ler; cada acesso fica no evento `codex.fora_da_pasta`, com a indicação de
    se o caminho foi citado.
- `bloquear` mantém o comportamento antigo. `livre_leitura` aprova leitura fora; escrever fora continua perguntando.
- Os dois agentes recebem a mesma orientação forte (`perfil_kiro.regra_fora`): fiquem nas pastas, leiam fora só o que foi
  citado e proponham em "Decisões para você" antes de olhar outra pasta vista no grafo.
- `codex_pastas_com_segredo` (`bloquear` padrão | `perfil_nativo`) deixa o Codex trabalhar em pasta com `.env`, confiando no
  deny do sandbox (ADR-026) e na vigia, que cancela o turno se uma chamada citar um segredo.
- Invariantes que não mudam: segredos sempre bloqueados para agentes, dados da Forja e `.git` protegidos, pasta de
  consulta somente leitura.

### Visual
- `movimento.css` e `js/movimento.js`:
  - dicas próprias (popover na top layer, atraso com aquecimento, teclado, Esc) para `title`, `data-dica` e botões só com
    ícone;
  - entrada animada de telas e painéis (só na troca de conteúdo, não no redesenho em tempo real);
  - troca de visualização e de tema com cores cruzando;
  - avisos que entram e saem;
  - indicador animado na barra de atividades;
  - resposta ao clique;
  - hierarquia de títulos;
  - toque grosso (36 px) e telas ≤ 600 px.
- Tudo desliga com "reduzir movimento". A camada `--z-dica` fica acima de tudo.

## Consequências
- O segundo cérebro cresce menos e com mais valor. A reciclagem pode apagar caderno e eventos detalhados se o usuário quiser;
  o replay da oficina dessas tarefas fica sem os passos.
- O Codex lê fora da pasta por padrão (pedido do usuário); a proteção passa a ser orientação + registro, não bloqueio.
- O LSP consome ~100-300 MB por servidor aberto. O teto e o fechamento por inatividade limitam isso.
- Pendentes: C# não foi testado com servidor real (o .NET SDK não está instalado nesta máquina) e falta o teste com leitor de
  tela real (NVDA).
