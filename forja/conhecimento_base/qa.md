---
titulo: Qualidade e testes
pai: Base de conhecimento da Forja
tags: qa, testes, qualidade
tipo: estrutural
---
Teste prova comportamento; cobertura sozinha não prova nada.
Subtópicos: [[Pirâmide de testes]], [[TDD e testes guiados por propriedades]], [[Testes de mutação]],
[[Testes instáveis (flaky)]], [[Testes de contrato e integração]].
Critério de aceite bom é verificável: um comando, um arquivo, um valor esperado.
+++
---
titulo: Pirâmide de testes
pai: Qualidade e testes
tags: piramide, unitario, integracao, e2e
relacionados: CI/CD; Testes de contrato e integração
---
- Muitos unitários (rápidos, puros), menos de integração (banco/HTTP reais), poucos ponta a ponta (navegador).
- Unitário testa regra, não implementação; nome do teste descreve o comportamento.
- Integração com dependência real (SQLite temporário, servidor local) pega erros que mocks escondem.
- Fakes rotulados (agente falso, relógio fixo) para determinismo; nunca declare um mock como funcionalidade real.
- Teste de regressão para todo bug corrigido.
+++
---
titulo: TDD e testes guiados por propriedades
pai: Qualidade e testes
tags: tdd, propriedades, hypothesis
relacionados: Pirâmide de testes; Testes de mutação
---
- TDD: escreva o teste que falha, implemente o mínimo, refatore. Bom para regras com casos claros.
- Testes por propriedade (Hypothesis, fast-check) geram entradas: ótimos para parsers, conversores e invariantes.
- Teste as bordas: vazio, um elemento, máximo, unicode, fuso horário, concorrência.
- Assert específico; evite `assert x or True` e testes que nunca falham.
+++
---
titulo: Testes de mutação
pai: Qualidade e testes
tags: mutacao, mutmut, qualidade de testes
relacionados: TDD e testes guiados por propriedades; Pirâmide de testes
---
- Altere o código de propósito (inverter condição, remover verificação) e veja se algum teste falha.
- Mutante sobrevivente = teste fraco ou código sem efeito; reforce o teste.
- Priorize defesas críticas (ACL, validação, segurança) para mutação manual ou automática (mutmut, Stryker).
+++
---
titulo: Testes instáveis (flaky)
pai: Qualidade e testes
tags: flaky, determinismo, tempo, concorrencia
relacionados: Concorrência e paralelismo; Pirâmide de testes
---
- Causas comuns: tempo real, ordem de execução, estado global, rede, corrida entre threads, cache do sistema.
- Use relógio injetável, dados isolados por teste, portas livres e esperas por condição (não `sleep` fixo).
- Reproduza repetindo o teste muitas vezes; corrija a causa em vez de retentar.
- Cache de bytecode e mtime em segundos podem esconder mudanças rápidas de arquivo: use cache limpo em verificações.
+++
---
titulo: Testes de contrato e integração
pai: Qualidade e testes
tags: contrato, api, integracao, schema
relacionados: Pirâmide de testes; Arquitetura em camadas e hexagonal
---
- Contrato: o formato que produtor e consumidor combinaram (OpenAPI, JSON Schema). Teste os dois lados contra ele.
- Para integrações externas, grave respostas reais anonimizadas como fixtures e rode contra elas.
- Teste os caminhos de erro (timeout, 401, 429, 500) e não só o sucesso.
- Integração com terceiros: uma chamada real mínima e de leitura no CI só quando for seguro e sem segredo.
