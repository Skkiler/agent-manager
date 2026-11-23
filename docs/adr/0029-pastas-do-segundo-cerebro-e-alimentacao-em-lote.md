# ADR-029: Pastas do segundo cérebro, alimentação em lote de uma pasta de projetos e notas por escopo

- Status: aceito
- Data: 2026-11-19
- Origem: pedido do usuário depois do ADR-028: alimentar o segundo cérebro com todos os projetos de uma pasta de códigos (projetos
  da empresa e pessoais), testando de ponta a ponta alimentação, organização, catálogo, pesquisa e conexões. Decisões do usuário:
  - tudo vai para `pessoal`; `publico` é o framework inicial; pesquisa e atualização do segundo cérebro são em `pessoal` por padrão;
  - não separar empresa e pessoal em raízes diferentes; usar pastas como `pessoal/empresa/<id>/projetos` e
    `pessoal/interno/<id>/projetos`;
  - o próprio robô deve diferenciar automações empresariais de técnicas genéricas;
  - o usuário (e o agente, com autorização do usuário) pode criar pastas, separar, migrar, mover, editar e conectar notas;
  - ler só o necessário: nada de `.env`, logs, dados e afins;
  - créditos sem teto rígido, limite de referência de 300 créditos do Kiro.

## Contexto

O estudo existente (`EstudoServico`) trabalhava uma pasta por vez, sempre num namespace fixo, e cada projeto recriava as
mesmas notas de sistemas compartilhados. Não havia como mover notas entre pastas nem renomear uma pasta. A busca da API e o
grafo do painel começavam em `publico`.

A primeira rodada real (47 projetos) achou falhas que travavam o lote; todas foram corrigidas com teste:

- No nível `restrito` (padrão), cada chamada do agente às ferramentas do MCP da Forja (buscar no segundo cérebro, caderno)
  pedia aprovação: o "acesso livre" do ADR-028 parava na primeira busca.
- O detector de laço via 6 cargas de ferramentas MCP diferentes ("Tool Load") como a mesma chamada, porque a assinatura não
  incluía os argumentos. Dois estudos foram interrompidos por isso.
- O agente de estudo também gravava cada nota com `forja_propor_nota` (cópias em `pessoal/aprendizados`).
- Um estudo terminou pedindo 3 decisões ao usuário e ficou bloqueado, segurando a vaga do lote.
- A descoberta tratava `src/`, `tests/` e `config/` como projetos separados.
- Pastas numeradas do usuário (`.0. Historico`) eram tratadas como ocultas.

## Decisão

### Pastas (`orquestracao/pastas_memoria.py`, `PastasMemoria`)
- Pasta = namespace. O limite de subníveis passou de 4 para 6 (`pessoal/empresa/<id>/projetos/<grupo>/<projeto>`).
- Usuário: `GET /memorias/pastas` (árvore com notas, total da subárvore e arquivos de código), `GET /memorias/pastas/notas`,
  `POST /memorias/pastas` (pasta vazia fica registrada em `configuracao.memoria_pastas`), `DELETE` (só vazia),
  `POST /memorias/pastas/mover` e `POST /memorias/pastas/renomear`.
- Mover guarda uma versão (motivo e ator), reindexa a busca, atualiza a sensibilidade e recalcula o escopo das ligações.
  Renomear migra notas, subpastas, pastas declaradas e o índice de código (`arquivo_indexado` e `codigo_fts`).
- A base da Forja (`publico/forja-base`) continua somente leitura; as raízes não podem ser renomeadas.
- Agente: só propõe (`forja_pasta_propor` no MCP → `POST /memorias/pastas/propor`). A proposta vira sugestão `pasta` na fila de
  Revisão; o usuário aceita ou rejeita.
- Painel: aba **Pastas** no grupo Saber; "Mover para outra pasta" na nota; filtro de pasta no grafo; a nova nota escolhe a pasta.

### Padrão em `pessoal`
- `GET /memorias/buscar` sem `namespace` busca em todos os namespaces permitidos (antes: só `publico`). `todos=true` continua
  aceito.
- O grafo do painel abre em `pessoal`; "mostrar a base da Forja" acrescenta `publico/forja-base` mesmo nesse filtro.
- A demonstração (`semear_demo.py`) cria as notas em `pessoal`.

### Acesso livre de verdade (`seguranca/acoes.py`, `mediador.py`)
- `FORJA_LIVRES`: as ferramentas do MCP que passam pela API da Forja (buscar, navegar, caderno, quadro, propor nota, propor pasta)
  são aprovadas sozinhas em qualquer nível. Regra do usuário ainda vence.
- `forja_executar_ferramenta` (lê arquivos) segue o nível, exceto em tarefas de estudo.
- Estudo: ler dentro da pasta estudada (`so_consulta`, calculado antes de relativizar o caminho) dispensa pergunta. Segredos
  continuam negados, e varredura em pasta com segredo continua perguntando.
- Pastas ignoradas por tarefa (`entrada.estudo.ignorar`: logs, dados, entrada, saida, dist, build...): leitura negada sem
  perguntar. O indexador também passou a ignorar `dados`, `entrada`, `saida`, `output`, `downloads`, `uploads` e `.obsidian`.

### Laço e estudo em lote (`kiro_acp/provedor.py`)
- A assinatura de cada chamada inclui os argumentos (`rawInput`). Cargas de esquema ("Tool Load", "Tool Search") nunca contam
  como laço; continuam contando no orçamento de ferramentas.
- No estudo em lote, "Decisões para você" não bloqueia: as notas valem e a dúvida fica na conversa. O protocolo do estudo pede
  as notas na resposta e proíbe `forja_propor_nota`. O MCP marca a nota com `tarefa:<id>`; se o agente gravar mesmo assim, a
  cópia que repete uma nota do estudo vira `substituido`, e a que traz algo novo fica ligada ao projeto.

### Notas por escopo (`EstudoServico.criar_notas`)
- Cada nota do estudo traz `Escopo: projeto | entidade | generico` e, para entidade, `Entidade: <nome>`.
  - projeto: na pasta do projeto, `SUBTOPICO_DE` o hub do projeto;
  - entidade (sistema, órgão, API interna, regra de negócio compartilhada): em `.../entidades`, sob o hub da entidade, com
    `DEPENDE_DE` do projeto para a entidade;
  - genérico (técnica ou biblioteca reutilizável): em `pessoal/geral`, com `REUTILIZAVEL_EM` para o projeto.
- Nota de entidade ou genérica que outro projeto já criou (mesmo título): ganha só o que é novo numa seção "Visto em
  <projeto>". Se diz o mesmo, só é ligada. Nota validada nunca é editada.
- A visão geral do projeto traz a linha "Classificação: automação empresarial | automação genérica | projeto pessoal".

### Alimentação em lote (`orquestracao/alimentacao.py`, `AlimentacaoLote`)
- `POST /estudos/lote/descobrir` (prévia, sem gravar), `POST /estudos/lote` (segundo plano), `GET /estudos/lote` e
  `POST /estudos/lote/cancelar`.
- A raiz precisa estar nas pastas permitidas. A própria Forja fica de fora.
- Descoberta:
  - projeto = pasta com marcadores ou código;
  - partes internas (`src`, `tests`, `config`...) nunca viram projeto;
  - pasta com 2+ projetos completos vira grupo quando o nome indica um sistema (prefixo "Cod -" ou termo em comum); senão é
    uma pasta de categoria.
- Escopo por caminho (`interno_contem`); o resto usa `escopo_padrao` (empresa). O agente confirma na visão geral.
- Por projeto, sem IA:
  - índice de código (só extensões de código e docs, PII redigida);
  - hub "Projeto: <nome>" com linguagens, estrutura, pontos de entrada e dependências (só nomes de pacote: linhas com `-`,
    `://` ou `@` são puladas, porque um índice privado pode ter credencial);
  - hubs "Projetos: empresa <id>" e "Grupo: <nome>".
- Com IA: N estudos por vez (padrão 2), até o teto de créditos medidos. Estudo bloqueado libera a vaga; um parado há mais de
  45 min também. Projeto já estudado (tag `estudado` no hub) é pulado, salvo `reestudar`.
- Painel: cartão "Alimentar com uma pasta de projetos" em Saber > Buscar e aprender, com prévia, início e andamento.

### Achados da organização e do uso real (corrigidos com teste)
- **Busca do agente:** com 2836 arquivos indexados, `forja_buscar_memoria` só devolvia trechos de código. Um estudo do Kiro
  concluiu que "nenhuma nota apareceu". Agora a busca traz as notas primeiro e completa com código (`codigo=false`: só
  notas). Depois disso, a mesma pergunta foi respondida citando 8 notas.
- **Organizar com IA:** com 611 notas o pedido passava de 4000 caracteres e a tarefa nem era criada. O pedido agora cabe no
  limite: primeiro os maiores trechos repetidos e as notas deles, depois o resto, até caber; o agente busca o que faltar.
- **Módulo entre projetos:** o plano juntava notas de projetos diferentes e a importação filtrava para uma pasta só, sobrando
  1 nota. O módulo agora vai para a pasta `entidades` ao lado de `projetos` (`pasta_do_modulo`).
- **Sugestões de ligação:** 700 sugestões de "ligar" notas do mesmo projeto só porque tinham as tags do estudo.
  - Agora só contam tags de assunto: as de estrutura e de tipo (`estudo`, `entidade`, `escopo-*`, `tecnica`...) ficam de fora.
  - Notas irmãs sob o mesmo tópico não são sugeridas.
  - Tópico não é sugerido para tag que já tem nota-hub.
  - 600 sugestões antigas viraram `obsoleta`.
- **Grafia:**
  - Tags escritas por agentes passam por `normalizar_tag`: `técnica`, `tipo:tecnica` e `tipo/tecnica` viram `tecnica`.
  - Hubs de entidade são achados pelo nome normalizado (`CadAlfa` = `Cadalfa`).
  - O texto padrão dos hubs não conta como duplicata nem como repetição.
  - `[[links]]` resolvem sem acento e sem caixa.
  - Backlinks procuram em todas as pastas permitidas.
- **Ruído:**
  - Tarefas internas da Forja (organizar, estudar, comandos) não geram mais nota "Registro".
  - Campos do estudo em negrito ou depois do corpo não vazam para o texto.
  - Linhas de metadado ("Fontes:", "Topico pai:") não contam como repetição.
- **Tela:** `append(null)` escrevia "null" na aba Pastas e no cartão do lote; a árvore de pastas cortava os nomes à esquerda.

## Alternativas rejeitadas
- Raízes `empresa/<id>` separadas de `pessoal`: o usuário pediu tudo em `pessoal`, separado por pastas.
- Agente movendo notas direto: mudança de organização é decisão do usuário; o agente só propõe.
- Um estudo para a pasta inteira: o contexto não comporta 47 projetos e as notas sairiam rasas.
- Aprovar toda leitura em estudo, inclusive varreduras: um `grep -r` numa pasta com `.env` leria o segredo.

## Consequências
- Notas da empresa ficam no banco local do usuário (`pessoal/empresa/...`), fora do Git; o contexto automático as inclui
  quando relevantes (ADR-028).
- O lote real consome em média 0,2 crédito por projeto (medido: 47 projetos, cerca de 13 créditos com as tentativas
  interrompidas). Organizar com IA custa perto de 9 créditos por pedido (medido) e é o item caro.
- O escopo empresa/próprio é uma heurística por caminho; o usuário corrige movendo ou renomeando a pasta.
