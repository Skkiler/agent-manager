---
titulo: Python
pai: Base de conhecimento da Forja
tags: python, linguagem
tipo: estrutural
---
Python legível, tipado e testado.
Subtópicos: [[Tipagem e contratos em Python]], [[Estrutura de projeto Python]], [[Desempenho em Python]].
Ferramentas base: Ruff (lint/format), pytest, Pydantic nas fronteiras, `logging` estruturado.
+++
---
titulo: Tipagem e contratos em Python
pai: Python
tags: tipagem, pydantic, mypy, protocol
relacionados: Arquitetura em camadas e hexagonal; Validação de entrada e injeção
---
- Anote assinaturas públicas; `from __future__ import annotations` e tipos modernos (`list[str]`, `X | None`).
- Pydantic (v2) valida entrada externa com `extra="forbid"`; dataclasses frozen para valores internos.
- `typing.Protocol` para portas (interfaces) sem herança.
- `Literal`/`Enum` para estados finitos; nunca strings mágicas espalhadas.
- Erros de validação viram 422 na API, com mensagem clara e sem stack trace.
+++
---
titulo: Estrutura de projeto Python
pai: Python
tags: estrutura, pacotes, pyproject, venv
relacionados: Arquitetura em camadas e hexagonal; Cadeia de suprimentos de software
---
- `pyproject.toml` com configuração de ferramentas; dependências fixadas em requirements/lock.
- Ambiente virtual por projeto (`.venv`), nunca o Python global.
- Pacote por camada (dominio, adapters, servidor...), testes espelhando a estrutura.
- Configuração por variáveis de ambiente validadas (pydantic-settings), com padrões seguros.
- Ponto de entrada `python -m pacote`; nada de lógica no import do módulo.
+++
---
titulo: Desempenho em Python
pai: Python
tags: desempenho, profiling, cache
relacionados: Índices e desempenho de consultas; Concorrência e paralelismo
---
- Meça antes (cProfile, py-spy, `time.perf_counter`); otimize o gargalo, não o palpite.
- Estrutura certa: set/dict para busca, gerador para fluxo grande, `bisect`/heap quando cabe.
- Cache de resultado caro com invalidação clara (hash/mtime) e limite de tamanho.
- I/O em lote; evite consulta por item dentro de laço.
- CPU pesado: processos ou extensão nativa; I/O: threads/asyncio.
+++
---
titulo: Agentes de IA e orquestração
pai: Base de conhecimento da Forja
tags: agentes, llm, orquestracao, ia
tipo: estrutural
---
Agentes úteis são simples, verificáveis e baratos: o arnês (ferramentas, contexto, limites) pesa tanto quanto o modelo.
Subtópicos: [[Engenharia de contexto]], [[Prompts eficazes]], [[Avaliação de agentes]], [[Escolha de modelo e custo]].
Relacionado: [[Segurança de agentes de IA]].
Padrões: encadeamento, roteamento, paralelização, orquestrador-trabalhadores e avaliador-otimizador. Comece pelo mais simples.
+++
---
titulo: Engenharia de contexto
pai: Agentes de IA e orquestração
tags: contexto, tokens, rag, busca agentica
relacionados: Prompts eficazes; Escolha de modelo e custo
---
- O contexto é um orçamento: entregue só o que a tarefa precisa, com referência para buscar o resto sob demanda.
- Para código, busca agêntica (grep, índice estrutural, leitura pontual) costuma vencer RAG vetorial.
- Grafos e índices (símbolos, funções, dependências) deixam o agente localizar sem ler arquivos inteiros.
- Conhecimento em tópicos pequenos e ligados: o agente pega o resumo e navega para o subtópico se precisar.
- Resultados de ferramenta compactos e paginados; limpe ou resuma resultados antigos em tarefas longas.
- Relembre o objetivo e os critérios em turnos longos (a instrução original se perde no meio da janela).
+++
---
titulo: Prompts eficazes
pai: Agentes de IA e orquestração
tags: prompt, instrucoes, formato
relacionados: Engenharia de contexto; Avaliação de agentes
---
- Prefixo fixo (papel, regras, formato) e parte variável depois: ajuda o cache do provedor.
- Instrução clara do objetivo, critérios de aceite verificáveis e formato de saída por seções.
- Peça evidências (o que rodou, o que mudou) e proíba alegar sem ter feito.
- Dados externos marcados como dados, nunca como ordens.
- Exemplos curtos valem mais que regras longas; menos texto, mais específico.
- Tarefa complexa: primeiro plano, depois execução; tarefa simples: direto ao ponto.
+++
---
titulo: Avaliação de agentes
pai: Agentes de IA e orquestração
tags: avaliacao, benchmark, metricas, evals
relacionados: Observabilidade; Pirâmide de testes
---
- Avalie com conjunto fixo de tarefas sintéticas com critério objetivo (testes passam, arquivo existe, valor esperado).
- Métricas: taxa de sucesso, custo por tarefa resolvida, latência, número de chamadas, intervenções humanas.
- Compare mudanças (modelo, prompt, ferramenta) no mesmo conjunto, com repetição para reduzir ruído.
- Registre falhas por tipo (alucinação, laço, ferramenta errada, contexto insuficiente) para atacar a maior.
+++
---
titulo: Escolha de modelo e custo
pai: Agentes de IA e orquestração
tags: modelos, custo, roteamento, esforco
relacionados: Engenharia de contexto; Avaliação de agentes
---
- Roteie por papel: planejar e revisar no modelo mais forte; implementar no melhor custo-benefício; ler, resumir e triar no mais barato.
- Roteie por complexidade: tarefa simples em um turno com modelo rápido; complexa com plano, execução e verificação.
- Esforço de raciocínio maior só onde o erro custa caro (planejamento, revisão).
- Multiagente gasta muitas vezes mais tokens que um único agente: use quando a tarefa realmente se divide.
- Tenha reserva explícita (fallback) para modelo indisponível, sempre registrada, nunca silenciosa.
