# ADR-020: Grafo de funções, hierarquia de modelos, roteamento por complexidade e segundo cérebro base

- Status: aceito

## Contexto

- Os agentes liam arquivos inteiros para entender o código. O índice estrutural do ADR-019 achava definições e referências, mas não respondia "o que esta função exige, de onde vem, quem chama".
- Todas as tarefas usavam o mesmo modelo e o mesmo fluxo. Uma pergunta simples custava como uma refatoração.
- O segundo cérebro começava vazio e não tinha organização por tópicos.

## Decisões

1. **Grafo de funções** (`codigo.estrutura`, operações `funcao` e `grafo`):
   - Nós: funções com assinatura (parâmetros, tipos, padrões), retorno, exceções levantadas, docstring e local (arquivo:linhas).
   - Arestas: chamadas que resolvem para funções do próprio projeto, com regras conservadoras:
     - `f()` aponta para a função do próprio arquivo ou para a importada;
     - `self.f()` aponta para a classe;
     - `obj.f()` aponta só para um método único, de nome não comum.
     - Nomes como `get`, `json` e `append` não viram relação.
   - Testes ficam fora do grafo e do ranking; código de produção aparece primeiro entre os chamadores.
   - **Padrão:** ao preparar qualquer tarefa com pasta de trabalho, a Forja gera o grafo (incremental, em cache) e põe no prompt um resumo das funções mais usadas: até ~400 tokens, ~150 em tarefas simples.
   - Medido no próprio repositório: 1.985 funções em ~1 s na 1ª vez. Detalhar uma função custa ~220 tokens, contra ler os arquivos.
2. **Hierarquia de modelos por função.** Fonte: catálogo real da conta via `kiro-cli chat --list-models`, cruzado com benchmarks públicos de nov/2026 [1][2][3]:

   | parte | papel | modelo padrão | esforço | custo relativo | reserva |
   |---|---|---|---|---|---|
   | rapida | operário rápido (leitura/tarefa simples) | claude-haiku-5.5 | medium | 0,06x | claude-haiku-4.5, auto |
   | execucao | executor (implementa e verifica) | claude-sonnet-5.5 | medium (high se complexa) | 1,30x | claude-sonnet-5, auto |
   | planejamento | planejador (mestre) | claude-opus-5.5 | high | 2,00x | claude-sonnet-5.5, auto |
   | revisao | revisor (mestre) | claude-opus-5.5 | high | 2,00x | claude-sonnet-5.5, auto |
   | estudo | pesquisador/resumidor | claude-haiku-5.5 | medium | 0,06x | claude-sonnet-5.5, auto |

   - Precedência: o que o usuário salvou > `APP_KIRO_MODEL` > padrão da Forja.
   - O esforço padrão só vale quando o modelo efetivo é o padrão da parte.
   - Modelos experimentais (`qwen3-coder-next`, `deepseek-3.2`) não são padrão por estabilidade, mesmo baratos. O usuário pode escolhê-los.
3. **Roteamento por complexidade** (`orquestracao/roteamento.py`, determinístico, custo zero). O usuário pode forçar o nível com `politicas.complexidade`.
   - **simples:** parte `rapida`, 1 turno, contexto ×0,5.
   - **normal:** parte `execucao`; rodada de correção se a tarefa altera código.
   - **complexa:** turno de **plano** com o modelo mestre (sem alterar nada; pesquisa se faltar conhecimento). Se o plano não pede decisão, a sessão troca para o executor (esforço mínimo `high`) e executa. Contexto ×1,5 e correção com testes.
   - Plano que pede decisão para **antes** de mexer em qualquer coisa.
   - Trabalho entregue com testes ou critérios falhando passa a ser `bloqueada`, nunca `concluida`.
4. **Segundo cérebro base** (`forja/conhecimento_base/`, namespace `publico/forja-base`):
   - 63 notas curtas em 10 áreas: engenharia (POO, SOLID, padrões, arquitetura, erros, concorrência), segurança (OWASP, segredos, auth, injeção, cripto, supply chain, ameaças, agentes), DevOps, banco, front-end, UI/UX (Nielsen, hierarquia, contraste, formulários, movimento), QA, RPA, Python e agentes.
   - Organização: uma nota-índice por área e subtópicos pequenos, ligados por `SUBTOPICO_DE` e `RELACIONADO_A` (novas arestas da ontologia).
   - **Somente leitura**, versionada e semeada na subida de forma idempotente (por hash).
   - É a **única** exceção epistemológica: entra `validado` por **curadoria** (arquivo versionado + testes de formato e de ligações), não por evidência de tarefa. Tudo o que o usuário ou o agente aprende nasce `candidato`.
   - Fica fora da vista do grafo por padrão (opção "mostrar a base da Forja"), mas participa da busca e do contexto.
5. **Recuperação econômica:** o contexto traz o resumo do tópico e o nome dos subtópicos (`subtopicos: A; B`). O agente aprofunda com `forja_navegar_memoria`, que devolve só pai, subtópicos e relacionados com resumos; o corpo vem só se pedido.
6. **Alimentação e estudo:**
   - `POST /api/v1/estudos` recebe uma pasta permitida ou um tópico.
   - A Forja prepara fatos determinísticos: mapa, arquivos centrais e grafo de funções da pasta, ou o que a base já sabe sobre o tópico.
   - Um agente de estudo (parte `estudo`, somente leitura) escreve notas por subtópico no formato `### Nota:`.
   - A Forja cria as notas como candidatas, redigidas e com fonte, e as liga ao tópico pai: dentro do estudo, na base ou na nota-raiz "Estudo: X".
7. **Registro auditável:** cada tarefa real concluída gera uma nota candidata `decisoria` (entendimento, plano, premissas, decisões do desenvolvedor, evidências, pendências) em `pessoal/projetos/<projeto>`, ligada ao tópico "Projeto: X".
   - Preferência `registrar_aprendizados`, ligada por padrão.
   - O agente também pode registrar um aprendizado com `forja_propor_nota` (candidato, em `pessoal/aprendizados`).
8. **Benchmark de tarefas** (item 0.6): 10 tarefas sintéticas com critério objetivo. O modo falso valida o arnês sem custo; o `--real` mede no Kiro.

## Verificação real (kiro-cli 3.1.0, conta empresarial, dados sintéticos)

| tarefa | nível roteado | modelos aplicados | chamadas | tempo | resultado |
|---|---|---|---|---|---|
| s1 explicar função | simples | haiku-5.5/medium | 1 | 16 s | ok |
| s2 listar funções | simples | haiku-5.5/medium | 1 | 13 s | ok |
| s3 explicar README | simples | haiku-5.5/medium | 1 | 15 s | ok |
| n1 média vazia | normal | sonnet-5.5/medium | 1 | 36 s | ok, testes da Forja passaram |
| n2 paginação | normal | sonnet-5.5/medium | 1 | 24 s | ok, testes da Forja passaram |
| c1 refatorar impostos | complexa | opus-5.5/high (plano) e depois sonnet-5.5/high (execução) | 2 | 82 s | ok, testes da Forja passaram |

## Fontes

1. [Start Debugging: Haiku vs Sonnet vs Opus 5.5 por papel em subagentes](https://startdebugging.net/2026/10/claude-haiku-5-5-vs-sonnet-5-5-vs-opus-5-5-for-coding-agent-subagents/).
2. [CodingFleet: SWE-bench Pro 2026](https://codingfleet.com/blog/swe-bench-pro-leaderboard-2026/) e [OpenRouter: Opus vs Sonnet vs Haiku](https://openrouter.ai/blog/insights/claude-opus-vs-sonnet-vs-haiku/).
3. [Família GPT-5.6 (Sol/Terra/Luna)](https://www.coderabbit.ai/blog/gpt-5-6-sol-and-terra-benchmark) e [Qwen3-Coder-Next](https://arxiv.org/pdf/2603.00729) (avaliados; não adotados como padrão).
4. Memória hierárquica e consolidação: [GAM (arXiv 2604.12285)](https://arxiv.org/pdf/2604.12285), [All-Mem (arXiv 2603.19595)](https://arxiv.org/abs/2603.19595). Base do item 9.12 (planejado).
5. Pixel Agents (referência da oficina): [Visual Studio Marketplace](https://marketplace.visualstudio.com/items?itemName=pablodelucca.pixel-agents). Base dos itens 9.15 a 9.19.

O conteúdo das fontes foi reescrito com palavras próprias para respeitar o licenciamento.
