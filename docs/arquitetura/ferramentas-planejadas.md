# Ferramentas externas planejadas para os agentes

Objetivo: trocar leitura bruta por respostas pequenas e deterministicas, gastando menos tokens sem perder eficacia.
Principio (AGENTS.md): ferramenta deterministica antes de LLM. **Nenhuma economia abaixo foi medida ainda**; cada item so
vira "pronto" depois de medir tokens antes/depois numa tarefa real com o mesmo criterio de aceite.

## Metodo de medicao (vale para todas)
1. Escolher 5 a 10 tarefas sinteticas representativas. 2. Rodar sem a ferramenta e com ela. 3. Registrar tokens estimados
(rotulo `estimado`), numero de chamadas e se o criterio de aceite foi cumprido. 4. So adotar se o criterio nao piorar.

## Lista priorizada
| # | Ferramenta | O que devolve | Substitui | Estado |
|---|---|---|---|---|
| 1 | Busca de simbolos (`definicao de X`) | arquivo, linha, tipo | leitura de varios arquivos | **existe** (ranker de simbolos); falta expor como MCP |
| 2 | Busca de memoria/contexto | itens uteis dentro de orcamento | colar documentos | **existe** (`ConstrutorContexto`) |
| 3 | Outline de arquivo (`codigo.outline`) | lista de simbolos e linhas | ler o arquivo inteiro | **existe** (`forja/ferramentas/outline.py`); falta expor via API/MCP |
| 4 | Mapa do repositorio (`repo.mapa`) | linguagens, pastas, entradas, config, testes | varredura manual | **existe** |
| 5 | Resumo de saida de testes (`testes.resumir_saida`) | veredito, contagens, falhas e causa | log completo do pytest | **existe** (`forja/ferramentas/testes.py`); so pytest |
| 6 | Triagem de logs (`logs.agrupar_falhas`) | erros agrupados por assinatura | log bruto | **existe** |
| 7 | Resumo de diff (`git.diff_analisar`) | arquivos, areas tocadas, riscos, segredo sem o valor | `git diff` completo | **existe** (`forja/ferramentas/diff.py`) |
| 8 | Inspetor de esquema (`sql.inspecionar`) | tabelas, colunas, indices (SQLite, somente leitura) | dump de SQL | **existe** (so SQLite) |
| 9 | Scanner de segredos (`segredos.varrer`) | achados com arquivo/linha, sem o valor | revisao manual | **existe** (heuristico; gitleaks segue pendente de aprovacao) |
| 10 | Extrator de documentos (pdf/docx) | texto e secoes | anexar documento inteiro | planejado |
| 11 | Orcamentador (`tokens.orcar`) | quais trechos cabem no orcamento | tentativa e erro | **existe** (estimativa ~4 car./token) |
| 12 | Verificador de citacoes | confere se `[M1]` aponta para item entregue | revisao manual | planejado |

## Como expor
Cada ferramenta e uma funcao pura com contrato tipado em `forja/ferramentas/`, atras do servico de orquestracao. Exposicao
via MCP **somente em loopback** e com a mesma ACL de namespace da memoria. Saida sempre rotulada como dado nao confiavel.

## Ferramentas adicionais ja existentes (alem da lista acima)
| Id | Funcao |
|---|---|
| `texto.amostra` | trecho numerado de arquivo; e o **fallback** automatico do `codigo.outline` quando nao ha simbolos |
| `dados.converter` | json/jsonl/csv/tabela markdown, conversao exata; neutraliza formulas (`=`, `+`, `-`, `@`) no CSV |
| `vault.indexar` | cofre de notas Markdown (Obsidian): links, backlinks, tags, orfas e links quebrados |
| `agenda.ler_ics` | eventos de um `.ics` local por periodo (Google Agenda/Outlook/Apple exportam `.ics`); recorrencia nao expandida |
| `email.ler_mbox` | mensagens de uma exportacao `.mbox` local (Gmail via Google Takeout); enderecos mascarados, corpo opt-in |

Conectores com rede/OAuth (Gmail API, Google Agenda, GitHub, Notion/Trello/Jira, avisos de saida) estao **planejados** no registro
`GET /api/v1/integracoes`, cada um com o que o operador precisa aprovar antes de ativar.

## Como o agente as usa hoje
`GET /api/v1/ferramentas` lista o catalogo (contrato, risco, fallback, disponibilidade); `POST /api/v1/ferramentas/{id}/executar`
roda uma ferramenta; `GET /api/v1/ferramentas/estatisticas` mostra o custo observado (chamadas, erros, fallbacks, tokens bruto x resumo,
latencia). Ferramentas de arquivo so enxergam as raizes de `APP_TOOLS_ROOTS` (vazio = desligadas). **Nao** ha texto de catalogo
injetado no prompt do Kiro: o custo em tokens do prompt nao mudou. Exposicao via MCP segue pendente.
## Ordem sugerida
3 -> 5 -> 7 -> 4 (reusam indexador e `git`), depois 6, 8, 9; 10 e 12 conforme necessidade real.
