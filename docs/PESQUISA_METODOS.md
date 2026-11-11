# Pesquisa: métodos da Forja vs. o mercado (nov/2026)

Varredura de cada recurso atual: o método de hoje, se é a melhor opção, a melhoria proposta, a influência esperada e as ligações com outras etapas.

Para cada fonte, os trechos foram resumidos com palavras próprias (conteúdo reescrito para respeitar o licenciamento). As fontes estão no fim.

Legenda de status:
- ✅ manter
- 🔧 melhorar (barato)
- 🧪 medir antes de decidir
- ⛔ não adotar

## 1. Como os grandes fazem busca de forma econômica

- **Busca agêntica sobre código** (glob, grep e leitura sob demanda) virou padrão.
  - O Claude Code começou com RAG e banco vetorial local, mas trocou por busca agêntica. Segundo Boris Cherny, ela teve desempenho muito superior e é mais simples: sem índice para manter atualizado, sem cópia do código e sem problema de privacidade [1].
  - Um estudo controlado (arXiv 2605.15184) achou grep em geral mais preciso que recuperação vetorial. O *harness*, ou seja, como as ferramentas devolvem resultados, pesou tanto quanto a estratégia de busca [2].
- **Índice estrutural** (mapa de símbolos e dependências, sem embeddings) melhora a localização em mudanças com vários arquivos, sem aumentar o custo por tarefa resolvida [3].
- **Busca delegada a subagente** que devolve só um resumo condensado preserva o contexto principal [4].
  - Esse padrão é caro em tokens: agentes gastam cerca de 4× os tokens de um chat, e sistemas multiagente cerca de 15× [5]. Só vale para tarefas de alto valor.
- **Engenharia de contexto:**
  - recuperação *just-in-time* (guardar referências e carregar sob demanda);
  - compactação do histórico;
  - limpeza de resultados de ferramenta antigos;
  - notas persistentes fora da janela [6].
- **Cache de prompt:** prefixo estático primeiro e conteúdo variável no fim. O cache só reaproveita o prefixo idêntico [7].
- **Padrões de orquestração** recomendados: encadeamento, roteamento, paralelização, orquestrador-trabalhadores e avaliador-otimizador. A regra é começar pelo mais simples e só subir de complexidade quando houver ganho medido [8].

**Conclusão para a Forja:** a direção atual está alinhada com o mercado: lexical e determinística, MCP sob demanda e sem embeddings por padrão. O híbrido com embeddings não é o próximo passo de melhor custo-benefício. Um **índice estrutural leve** (símbolos, imports e chamadas, via `ast` e tree-sitter) é mais promissor e segue a regra de não misturar o grafo de código com os outros grafos.

## 2. Recurso por recurso

| # | Recurso | Hoje | Melhor opção? | Melhoria proposta | Influência esperada | Ligações |
|---|---|---|---|---|---|---|
| 1 | Busca na memória (FTS5, namespaces, ACL) | Lexical com cobertura e gatilhos de linguagem | ✅ para memória textual curta | Manter. Híbrido só opcional (ADR-017, aguarda decisão) | Recall +0,06 com custo de indexação alto | Construtor de contexto, citações [M1] |
| 2 | Busca de código | Lexical (benchmark CodeSearchNet: 0,163) | 🔧 | **Índice estrutural incremental** (símbolos, imports e chamadas por hash de arquivo) como ferramenta MCP `forja_simbolos` | Localização multiarquivo melhor sem modelo de embeddings [3]; custo de CPU baixo | Grafo de código (separado); explorador; @menção |
| 3 | Fallback híbrido | Medido; não ligado | 🧪 | Só depois do item 2: comparar índice estrutural vs. híbrido no mesmo benchmark | Evita baixar ~220 MB e 6 a 7 min de CPU sem necessidade | ADR-017 |
| 4 | Construtor de contexto | Injeta trechos citáveis só quando há acerto relevante | ✅ | Trocar trechos longos por **referências** (caminho + linha) quando o MCP está ligado, como recuperação *just-in-time* [6] | Menos tokens de entrada por execução | MCP, cache de prompt |
| 5 | Ordem do prompt | PROTOCOLO primeiro, tarefa e contexto depois | ✅ (amigável ao cache) | Mover `perfil_texto` (varia por usuário) para depois da tarefa, deixando o prefixo 100% fixo | Maior chance de acerto de cache no provedor [7] | Provedor ACP |
| 6 | Retomada | `session/load` + prompt curto; sem load, retomada resumida | ✅ | Nada | — | Conversa, checkpoints |
| 7 | Protocolo de conversa (briefing) | Seções fixas e decisões consolidadas com recomendação | ✅ | Pedir no protocolo uma seção "Evidências" (comandos e arquivos), conferida pelo item 13 | Respostas verificáveis; menos alegação solta | Alegações, aceite |
| 8 | Mediador de permissões | Agrupa pedidos por janela, decide por nível, sempre pergunta o destrutivo | ✅ | Nada. Agora reforçado pelo perfil `deny` nativo (item 9) | — | Níveis, aprovações agrupadas |
| 9 | **Perfil de segurança do Kiro** (novo) | Modo `forja` + presets; falha fechada | ✅ (verificado no Kiro real) | Revisar o sinal "MCP pronto" após a troca de modo | Fecha o vazamento de `.env`; pode economizar até 15 s por execução | MCP, níveis |
| 10 | `.env` sem leitura (novo) | `env.verificar` booleano; consumidores do env liberados | ✅ | Opcional: `env.verificar` também aceitar `docker compose` com `--env-file` para checar chaves que o compose referencia | Validar ambiente antes de subir containers | Mediador, catálogo |
| 11 | Níveis de autonomia, tags e observações | restrito, liberado e total + tags curtas | ✅ | Nada | — | Mediador, presets |
| 12 | Modelo e esforço por parte | Configurado; falha fechada se indisponível | ✅ (seguro) | **Fallback opcional ordenado** por parte (ex.: `opus → sonnet → auto`), desligado por padrão, registrado em evento | Menos bloqueios por modelo fora da conta, sem trocar em silêncio | Configurações |
| 13 | **Conferência de alegações** (novo) | Determinística: testes, comandos, arquivos | ✅ | Próximo passo: o **avaliador-otimizador** [8]. Em `alteracao_codigo`, a Forja roda o comando de teste do projeto (aprovado) e devolve **um** turno com a falha, se houver | Ninguém precisa confiar no "testes passaram" | Aceite, orçamento |
| 14 | Validação de aceite | Do orquestrador; resposta de LLM é "não verificada" | ✅ | Critérios de aceite marcados como **verificáveis** (comando ou arquivo) vs. **manuais** | Aceite automático só quando há prova | Itens 7 e 13 |
| 15 | Consumo de tokens | Estimado (~4 caracteres por token) e rotulado | ✅ (honesto) | Usar o `breakdown` do `session_info_update` do Kiro (já lido para o MCP) como medida de contexto | Números mais próximos do real | Painel |
| 16 | Catálogo de ferramentas determinísticas | Antes do LLM | ✅ | Nada | — | MCP |
| 17 | MCP da Forja | stdio, opt-in, dica curta no prompt | ✅ | Devolver resultados **resumidos com referências** e paginação: o harness pesa tanto quanto o buscador [2] | Menos tokens por chamada | Itens 2 e 4 |
| 18 | Multiagente e subagentes | Só quando melhora a tarefa | ✅ | Subagente de busca só para perguntas amplas (≥ N pastas) [4][5] | Evita o custo de ~15× | Orquestração |
| 19 | Integrações (Trello, Notion, Google, Gmail) | Escrita externa só aprovada | ✅ | Nada | — | Aprovações |
| 20 | Busca web (Brave, SearXNG) | Opt-in | ✅ | Citações obrigatórias no protocolo quando houver resultado web | Menos afirmação sem fonte | Item 7 |
| 21 | Redação de segredos e logs | Regex + sanitização | ✅ | Nada | — | Tudo |
| 22 | Rede (loopback, túnel, HTTPS autenticado) | Padrão loopback | ✅ | Nada | — | — |
| 23 | Perfis de recursos | Sem LLM local; benchmark antes do pesado | ✅ | Nada | — | Itens 2 e 3 |

## 3. Melhorias adicionais (salvaguardas e prompting guiado)

1. **Seção "Evidências" + conferência** (itens 7 e 13): o agente lista o que rodou e alterou, e a Forja confere de forma determinística. Custo de tokens quase zero.
2. **Avaliador-otimizador com teto:** no máximo **um** turno de correção por execução, contado no orçamento. Evita laço caro.
3. **Prompting guiado por modelo de tarefa:** ao criar uma tarefa, o painel sugere critérios de aceite verificáveis por modo (análise, alteração, documentação). Melhora a entrada sem gastar LLM.
4. **Fallbacks inteligentes, sempre explícitos:** modelo (item 12), MCP (sem MCP, cai para o contexto injetado e já existe) e busca (estrutural → lexical). Nenhum fallback troca silenciosamente uma garantia de segurança.

## 4. Ordem sugerida

1. Índice estrutural de código (item 2) + benchmark contra o híbrido (item 3).
2. Seção "Evidências" + avaliador-otimizador de um turno (itens 7, 13 e 14).
3. Prefixo de prompt 100% fixo (item 5) e consumo real via `breakdown` (item 15).
4. Fallback de modelo opcional (item 12).

## Fontes

1. Boris Cherny sobre RAG vs. busca agêntica no Claude Code: relatos em [officechai.com](https://officechai.com/ai/claude-researcher-explains-how-agentic-search-performed-better-than-rag-for-code-generation/) e [dev.to (podcast Latent Space)](https://dev.to/chen115y/the-representation-problem-why-rag-vs-agentic-search-is-the-wrong-debate-4j8f).
2. [Is Grep All You Need? How Agent Harnesses Reshape Agentic Search (arXiv 2605.15184)](https://arxiv.org/abs/2605.15184).
3. [Code Isn't Memory: A Structural Codebase Index Inside a Coding Agent (arXiv 2606.22417)](https://arxiv.org/pdf/2606.22417).
4. [Deep Agentic Search for Repository-Level Code Question Answering (arXiv 2608.01507)](https://arxiv.org/pdf/2608.01507).
5. [Anthropic: How we built our multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system).
6. [Anthropic: Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents).
7. [Anthropic: Prompt caching](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching).
8. [Anthropic: Building effective agents](https://www.anthropic.com/engineering/building-effective-agents).
9. Kiro: [permissões](https://kiro.dev/docs/permissions/) e [referência de agentes](https://kiro.dev/docs/custom-agents/configuration-reference/).
