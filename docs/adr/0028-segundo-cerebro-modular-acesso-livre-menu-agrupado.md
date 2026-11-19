# ADR-028: Segundo cérebro modular, acesso livre dos agentes à memória e menu agrupado

- Status: aceito
- Data: 2026-11-19
- Origem: pedido do usuário depois do ADR-027: os agentes devem ter acesso livre ao segundo cérebro, às notas e ao grafo;
  criar um serviço "organizar e deduplicar" com IA (notas modulares, nota da entidade, conexões, menos repetição); conferir
  quão modulares estão as notas reais e calibrar os agentes; juntar as telas de conhecimento e ferramentas numa área com abas;
  agrupar o menu lateral em 6 a 7 itens.

## Contexto

Antes desta rodada o acesso dos agentes à memória era limitado:

- O MCP `forja_buscar_memoria` chamava `/memorias/buscar` sem namespaces. A rota assume `["publico"]` nesse caso, então o
  agente nunca via as notas pessoais nem as dos projetos.
- O MCP vinha desligado por padrão (`kiro_mcp_ativo = False`). Sem ele, o agente só recebia o contexto montado no início.
- O contexto automático usava só `APP_CONTEXT_NAMESPACES` (padrão `publico`) e, desde o ADR-027, o namespace do projeto.

Auditoria do banco real do usuário (somente leitura, só agregados): 63 notas curadas da base (`publico/forja-base`), nenhuma
nota pessoal ainda. Média de 69 palavras, mediana 65, máximo 129; nenhuma repetição, nenhuma órfã; pontuação 100.

## Decisão

### Acesso livre à memória
- `/memorias/buscar?todos=true` busca em todos os namespaces que o principal pode ler (`p.namespaces`). O MCP usa esse modo.
  A ACL continua valendo: "livre" é tudo o que o usuário permite, não além.
- `kiro_mcp_ativo` passa a ser ligado por padrão, para Kiro e Codex.
- Preferência nova `contexto_memoria_ampla` (padrão ligada): o construtor de contexto também procura em todos os namespaces
  permitidos (`cfg.memoria_namespaces`, padrão `publico,pessoal`).
- Mantido: o piso de relevância. Nota candidata só entra no contexto automático com casamento forte; o resto o agente busca
  pelo MCP quando precisar. Assim o acesso é amplo sem encher o prompt.

### Organizar e deduplicar (`orquestracao/modularidade.py`, `Modularidade`)
- Parte determinística, sem custo de IA:
  - `saude()`: pontuação 0–100, tamanho das notas, longas/curtas, sem tags, órfãs, links fantasmas e % de texto repetido.
  - `repeticoes()`: frases com ≥ 6 termos que aparecem em 2+ notas (Jaccard ≥ 0,8), agrupadas pelo mesmo conjunto de notas,
    com palpite da entidade (tag em comum ou nome próprio repetido). Mais economia primeiro.
- Parte com IA: `pedir_ia()` cria uma tarefa de análise preparada no projeto `forja-conhecimento`. O pedido leva só os
  aglomerados repetidos (até 25) e uma lista compacta das notas (até 200), não o texto inteiro do grafo. O agente devolve um
  plano JSON com `modulos`, `ligacoes`, `fundir`, `dividir` e `tags`.
- `importar_plano()` transforma o plano em sugestões pendentes (`modularizar`, `ligacao`, `duplicata`, `dividir`, `tags`),
  idempotente pela chave. Ao concluir a tarefa, a importação acontece sozinha (`ao_finalizar`).
- Nada é aplicado sem o usuário aceitar na fila de revisão. Ao aceitar:
  - `modularizar` cria a nota do módulo (tag `modulo`) e a nota da entidade (tag `entidade`, ligação `SUBTOPICO_DE`), tira
    das notas de origem as frases repetidas (`remover_trecho`, preservando o Markdown e retirando títulos que ficaram vazios)
    e acrescenta `Ver [[Título]].` Exemplo do pedido: a regra "o sistema Função exige automação por HTTP" sai das 15 notas de
    automação e fica uma vez na nota do Sistema Função, ligada aos projetos.
  - Nota já validada não é editada; só ganha a ligação `BASEADO_EM` para o módulo.
  - `dividir` cria as partes (`SUBTOPICO_DE`) e transforma a original num índice.
  - `tags` só acrescenta tags.
- Rejeitado: aplicar as edições automaticamente. Um plano errado apagaria texto de muitas notas de uma vez.

### Calibração das notas (`REGRAS_NOTA`, `avaliar_nota`)
- Regras: um assunto por nota; título específico; 60–350 palavras (longa > 600; curta < 25 sem links); tags de entidade, tipo
  e projeto; fatos da entidade ficam na nota da entidade e as outras só ligam; buscar antes de criar.
- A primeira faixa foi 80–400. A base real tem média de 69 palavras e está bem modular, então a faixa caiu para 60–350 para não
  acusar as notas boas.
- O mesmo texto vai para `DICA_MCP` e `PROTOCOLO_ESTUDO` (provedor Kiro), para a descrição do `forja_propor_nota` (< 200
  caracteres), para o pedido de organização e para `POST /memorias/avaliar`. `forja_propor_nota` devolve `qualidade` com os
  avisos da nota proposta.

### Menu agrupado (`js/main.js` `GRUPOS`)
- Seis grupos mais Conta e Configurações:
  - Arquivos (painel): explorador, busca.
  - Código (painel): Git, Docker.
  - Dev (vista): HTTP, comandos.
  - Agentes (vista): master, tarefas, quadro.
  - Saber (vista): grafo e notas, buscar e aprender, organizar, revisão, ferramentas.
  - Conexões (vista): integrações, custos.
- Membros de grupo de vista dividem uma aba do editor (`vista:<grupo>`) com abas ARIA no topo. Grupos de painel mostram as
  abas no topo da barra lateral.
- O último membro usado de cada grupo fica em `localStorage` (`forja_grupos`). As rotas `#/<membro>` continuam funcionando e
  as abas salvas no formato antigo migram.
- Rejeitado: uma aba do editor por membro (abas demais, contra o pedido).

## Consequências
- Os agentes leem tudo o que o usuário pode ler, inclusive `pessoal`. Quem não quiser isso desliga `contexto_memoria_ampla`
  ou o MCP nas Configurações.
- A organização por IA custa uma tarefa de análise por pedido; o diagnóstico (`saude`, `repeticoes`) é gratuito.
- A base real ainda é pequena e já modular, então a deduplicação só foi exercitada com dados fictícios nos testes.
- Pendentes: sondagem com Kiro/Codex reais do acesso pelo MCP nesta rodada (validado por testes de unidade e API), C# com
  servidor real e teste com NVDA.
