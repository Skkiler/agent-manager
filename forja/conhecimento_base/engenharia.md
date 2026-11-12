---
titulo: Engenharia de software
pai: Base de conhecimento da Forja
tags: engenharia, design
tipo: estrutural
---
Princípios para código que muda com segurança: coesão alta, acoplamento baixo, contratos explícitos e testes que provam o comportamento.
Subtópicos: [[Programação orientada a objetos]], [[SOLID]], [[Padrões de projeto]], [[Código limpo]],
[[Arquitetura em camadas e hexagonal]], [[Tratamento de erros]], [[Concorrência e paralelismo]].
Ordem prática: entender o domínio, definir contratos (tipos, esquemas), escrever o teste, implementar o mínimo, refatorar.
+++
---
titulo: Programação orientada a objetos
pai: Engenharia de software
tags: poo, classes, encapsulamento
relacionados: SOLID; Padrões de projeto
---
Objetos juntam estado e comportamento; o valor está no encapsulamento, não na herança.
- Encapsulamento: o estado interno só muda por métodos que preservam invariantes (ex.: saldo nunca negativo).
- Prefira composição a herança: herde só quando "é um" for verdade em todos os usos (substituição de Liskov).
- Polimorfismo por interface/protocolo (em Python, `typing.Protocol`) evita `if tipo == ...` espalhado.
- Objetos de valor imutáveis (dataclass frozen) para dinheiro, datas, IDs: comparáveis e seguros entre threads.
- Evite "classes de serviço deus" com dezenas de métodos: divida por responsabilidade.
- Herança profunda (> 2 níveis) costuma esconder acoplamento; troque por composição ou estratégia.
+++
---
titulo: SOLID
pai: Engenharia de software
tags: solid, poo, design
relacionados: Programação orientada a objetos; Arquitetura em camadas e hexagonal
---
Cinco princípios para módulos fáceis de mudar.
- S, responsabilidade única: um módulo tem um motivo para mudar. Sinal de violação: nome com "e" (ValidaESalva).
- O, aberto/fechado: estenda por novos tipos/estratégias, sem editar o núcleo testado.
- L, substituição de Liskov: subtipo não pode exigir mais nem entregar menos que o tipo base (mesmas pré/pós-condições).
- I, segregação de interfaces: interfaces pequenas por cliente; ninguém implementa método que não usa.
- D, inversão de dependência: o domínio depende de abstrações (portas); detalhes (banco, HTTP, CLI) implementam essas portas.
Aplicar com bom senso: abstração sem segundo uso real é custo (YAGNI).
+++
---
titulo: Padrões de projeto
pai: Engenharia de software
tags: padroes, design patterns
relacionados: SOLID; Programação orientada a objetos
---
Padrões são vocabulário para problemas recorrentes; use quando o problema aparece, não por antecipação.
- Estratégia: trocar algoritmo em tempo de execução (ex.: provedores de agente, formatos de exportação).
- Adaptador: isolar uma API externa atrás de uma interface do domínio (ex.: cliente ACP, integrações).
- Fábrica: centralizar a criação quando ela depende de configuração.
- Observador/eventos: desacoplar quem produz de quem reage (ex.: SSE, quadro de mensagens).
- Repositório: esconder a persistência atrás de operações do domínio.
- Comando: representar ações como dados (filas, desfazer, auditoria).
- Máquina de estados: transições explícitas e testáveis para ciclos de vida (tarefa, pedido, memória).
Antipadrões comuns: singleton global mutável, herança para reuso de código, "god object".
+++
---
titulo: Código limpo
pai: Engenharia de software
tags: clean code, legibilidade, refatoracao
relacionados: Tratamento de erros; SOLID
---
Código é lido muito mais vezes do que escrito.
- Nomes revelam intenção e unidade (`timeout_s`, `preco_centavos`); evite abreviações obscuras.
- Funções pequenas, um nível de abstração cada; mais de 3-4 parâmetros pede um objeto de entrada.
- Sem efeitos colaterais escondidos: função que "consulta" não grava.
- Comentário explica o porquê; o quê deve estar claro no código.
- Elimine duplicação de conhecimento (DRY), não de texto parecido por acaso.
- Refatore com rede de testes, em passos pequenos e reversíveis; não misture refatoração com mudança de comportamento no mesmo commit.
- Remova código morto: o Git guarda o histórico.
+++
---
titulo: Arquitetura em camadas e hexagonal
pai: Engenharia de software
tags: arquitetura, camadas, portas e adaptadores, ddd
relacionados: SOLID; Padrões de projeto
---
Separe o que muda por motivos diferentes.
- Camadas típicas: interface (HTTP/CLI/UI) → aplicação (casos de uso) → domínio (regras puras) → infraestrutura (banco, rede).
- Dependências apontam para dentro: o domínio não importa framework, banco nem HTTP.
- Hexagonal (portas e adaptadores): o domínio define portas; adaptadores implementam (SQLite, API externa, fake de teste).
- Contratos tipados nas fronteiras (Pydantic/JSON Schema) validam a entrada uma vez, na borda.
- Decisões de arquitetura relevantes viram ADR curto (contexto, decisão, consequências).
- Monólito modular primeiro; separar em serviços só com motivo medido (escala, time, isolamento).
+++
---
titulo: Tratamento de erros
pai: Engenharia de software
tags: erros, excecoes, resiliencia
relacionados: Código limpo; Observabilidade
---
Erros são parte do contrato.
- Falhe cedo e alto na borda (validação); dentro do domínio use exceções tipadas com código estável.
- Nunca engula exceção em silêncio; se tratar, registre com contexto (sem segredos) ou converta para um erro do domínio.
- Diferencie erro do usuário (4xx, mensagem clara) de erro do sistema (5xx, log com correlação, mensagem genérica).
- Retentativa só para falhas transitórias, com limite, atraso exponencial e jitter; operações repetidas precisam ser idempotentes.
- Falha fechada em segurança: na dúvida, negue (permissão, modelo indisponível, validação).
- Libere recursos com `with`/`finally`; timeouts em toda chamada de rede e processo.
+++
---
titulo: Concorrência e paralelismo
pai: Engenharia de software
tags: concorrencia, threads, async, race condition
relacionados: Transações e concorrência no banco; Tratamento de erros
---
Concorrência errada gera falhas raras e difíceis de reproduzir.
- Prefira não compartilhar estado mutável; quando precisar, proteja com lock e mantenha a seção crítica curta.
- Concorrência otimista (versão/ETag) para edição simultânea: quem salvou com versão antiga recebe conflito (409).
- I/O concorrente: threads ou asyncio; CPU pesado: processos.
- Arquivos temporários únicos por escritor e troca atômica (`os.replace`) evitam corrida em disco.
- Teste corridas de forma determinística (barreiras, muitas threads, repetição) e não só "rodou uma vez".
- Toda espera tem timeout e cancelamento.
