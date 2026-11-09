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
| 3 | Outline de arquivo | lista de simbolos e linhas | ler o arquivo inteiro | planejado (reusa o indexador) |
| 4 | Mapa do repositorio | arvore resumida + pontos de entrada | varredura manual | planejado |
| 5 | Resumo de saida de testes | so falhas e causa provavel | log completo do pytest | planejado |
| 6 | Triagem de logs | linhas de erro agrupadas por assinatura | log bruto | planejado |
| 7 | Resumo de diff | arquivos, hunks e risco | `git diff` completo | planejado |
| 8 | Inspetor de esquema | tabelas, colunas, indices | dump de SQL | planejado |
| 9 | Scanner de segredos | achados com arquivo/linha, sem o valor | revisao manual | planejado (gitleaks pendente de aprovacao) |
| 10 | Extrator de documentos (pdf/docx) | texto e secoes | anexar documento inteiro | planejado |
| 11 | Orcamentador de contexto | estimativa de tokens por item | tentativa e erro | parcial (estimativa ~4 car./token) |
| 12 | Verificador de citacoes | confere se `[M1]` aponta para item entregue | revisao manual | planejado |

## Como expor
Cada ferramenta e uma funcao pura com contrato tipado em `forja/ferramentas/`, atras do servico de orquestracao. Exposicao
via MCP **somente em loopback** e com a mesma ACL de namespace da memoria. Saida sempre rotulada como dado nao confiavel.

## Ordem sugerida
3 -> 5 -> 7 -> 4 (reusam indexador e `git`), depois 6, 8, 9; 10 e 12 conforme necessidade real.
