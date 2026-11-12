---
titulo: DevOps
pai: Base de conhecimento da Forja
tags: devops, operacao, entrega
tipo: estrutural
---
Entregar mudanças pequenas, frequentes, verificadas e reversíveis.
Subtópicos: [[CI/CD]], [[Containers e Docker]], [[Infraestrutura como código]], [[Observabilidade]],
[[Deploy seguro e rollback]], [[Git e fluxo de trabalho]].
Métricas úteis (DORA): frequência de deploy, tempo de entrega, taxa de falha de mudança, tempo de recuperação.
+++
---
titulo: CI/CD
pai: DevOps
tags: ci, cd, pipeline, github actions
relacionados: Cadeia de suprimentos de software; Pirâmide de testes
---
- CI em todo push/PR: lint, testes, varredura de segredos e de dependências; falha bloqueia o merge.
- Pipeline rápido primeiro (lint, unitários), lento depois (integração, navegador).
- Builds reproduzíveis: versões fixas, cache com chave por lockfile.
- Segredos do CI como secrets do provedor, com escopo mínimo; nunca impressos.
- Artefatos e relatórios de falha legíveis (anotações, JUnit) para corrigir sem rodar local.
- CD com gates: ambiente de teste, aprovação para produção, deploy automatizado e reversível.
+++
---
titulo: Containers e Docker
pai: DevOps
tags: docker, containers, compose, imagens
relacionados: Infraestrutura como código; Gestão de segredos
---
- Imagem pequena e fixada (tag com versão ou digest); multi-stage para não levar compilador para produção.
- Rode como usuário não-root; sistema de arquivos somente leitura quando possível.
- Segredos por `--env-file`/secrets do orquestrador, nunca no Dockerfile nem na imagem.
- `.dockerignore` sem `.git`, `.env`, dados e caches.
- Um processo por container; healthcheck definido; logs para stdout.
- `docker compose config` e `docker inspect` exibem variáveis: trate como sensível.
+++
---
titulo: Infraestrutura como código
pai: DevOps
tags: iac, terraform, configuracao
relacionados: Containers e Docker; Deploy seguro e rollback
---
- Toda infraestrutura descrita em código versionado e revisado (Terraform, Pulumi, Bicep, Ansible).
- Plano antes de aplicar; aplicar só pelo pipeline, nunca à mão em produção.
- Estado remoto com trava e criptografia; nada de segredo no estado em texto claro.
- Módulos pequenos e reutilizáveis; ambientes separados por variável, não por cópia.
- Detecte desvio (drift) periodicamente.
+++
---
titulo: Observabilidade
pai: DevOps
tags: logs, metricas, traces, opentelemetry
relacionados: Tratamento de erros; Avaliação de agentes
---
- Três sinais: logs estruturados (JSON), métricas (latência, erros, saturação) e traces distribuídos.
- Toda requisição/execução tem ID de correlação propagado.
- Logs sem segredos, PII ou payload grande; nível INFO para eventos de negócio, DEBUG desligado em produção.
- Alertas por sintoma (SLO violado), não por causa; cada alerta tem ação clara.
- OpenTelemetry como padrão aberto (inclui convenções para chamadas de modelos de IA).
+++
---
titulo: Deploy seguro e rollback
pai: DevOps
tags: deploy, rollback, canary, feature flag
relacionados: CI/CD; Migrações de esquema
---
- Deploy pequeno e frequente; cada mudança reversível.
- Estratégias: blue/green, canário (pequena fração primeiro) e feature flags para desligar sem novo deploy.
- Migração de banco compatível para trás (expandir, migrar, contrair) para permitir rollback do código.
- Backup verificado antes de mudança destrutiva.
- Produção, deploy e acesso público só com aprovação explícita.
+++
---
titulo: Git e fluxo de trabalho
pai: DevOps
tags: git, branch, commit, revisao
relacionados: CI/CD; Código limpo
---
- Commits pequenos, com mensagem que explica o porquê; uma intenção por commit.
- Branch curta com PR revisado; integração frequente na principal.
- Nunca reescreva histórico compartilhado sem combinar; prefira `--force-with-lease` a `--force`.
- `.gitignore` para dados, segredos, caches e artefatos gerados.
- Revisão de código foca em comportamento, risco e testes, não só estilo (o lint cuida do estilo).
- Worktrees isolam trabalho paralelo (ex.: um agente por worktree) sem misturar alterações.
