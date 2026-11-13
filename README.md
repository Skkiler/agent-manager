# Forja

Orquestrador **local** de agentes de IA para desenvolvimento de software. A Forja recebe tarefas, decide como executá-las,
entrega o trabalho a agentes reais (o **Kiro CLI**, via protocolo ACP), media cada permissão que o agente pede, confere o
resultado de forma determinística (testes, critérios, alegações) e guarda o conhecimento útil num **segundo cérebro**
consultável. Tudo roda no seu computador: servidor em `127.0.0.1`, banco SQLite no seu perfil e um painel web no navegador.

> Estado: em uso. Fases 0 a 4 e 9 implementadas e testadas (1080+ testes automatizados, inspeção em navegador real e CI).
> Detalhes, números medidos e pendências em [`docs/STATUS_IMPLEMENTACAO.md`](docs/STATUS_IMPLEMENTACAO.md); decisões em
> [`docs/adr/`](docs/adr/).

---

## Sumário

1. [Início rápido](#início-rápido)
2. [Como a Forja funciona](#como-a-forja-funciona)
3. [O painel, tela por tela](#o-painel-tela-por-tela)
4. [Ciclo de uma tarefa](#ciclo-de-uma-tarefa)
5. [Roteamento e modelos](#roteamento-e-modelos)
6. [Aprovações, autonomia e regras](#aprovações-autonomia-e-regras)
7. [Verificação: o que a Forja confere sozinha](#verificação-o-que-a-forja-confere-sozinha)
8. [Projetos, pastas e anexos](#projetos-pastas-e-anexos)
9. [Desfazer, pastas isoladas e retomada](#desfazer-pastas-isoladas-e-retomada)
10. [Segundo cérebro (memória)](#segundo-cérebro-memória)
11. [Contexto econômico](#contexto-econômico)
12. [Ferramentas dos agentes e MCP](#ferramentas-dos-agentes-e-mcp)
13. [Integrações externas](#integrações-externas)
14. [Custo, telemetria e observabilidade](#custo-telemetria-e-observabilidade)
15. [Segurança](#segurança)
16. [Onde ficam os seus dados](#onde-ficam-os-seus-dados)
17. [Hospedagem](#hospedagem)
18. [Configuração (.env e tela)](#configuração-env-e-tela)
19. [API](#api)
20. [Arquitetura do código](#arquitetura-do-código)
21. [Desenvolvimento e testes](#desenvolvimento-e-testes)
22. [Limites conhecidos](#limites-conhecidos)

---

## Início rápido

Pré-requisitos (Windows, que é o alvo principal; Linux/macOS funcionam para desenvolvimento):

- Python 3.12+ (testado em 3.13) e Git.
- **Kiro CLI** instalado e autenticado (`kiro-cli login`). Sem ele, a Forja sobe com o agente **simulado** (mock).

```powershell
# 1. dependências (uma vez)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. conferir o Kiro (não consome créditos)
python scripts\diagnostico_kiro.py

# 3. subir a Forja REAL (Kiro de verdade, seus dados, só 127.0.0.1) e abrir o navegador
powershell -ExecutionPolicy Bypass -File scripts\iniciar_forja.ps1 -Abrir
```

No primeiro acesso a tela pede para **criar o usuário e a senha** (só funciona no próprio computador). Depois é só entrar.

Para a Forja subir sozinha quando você entrar no Windows:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\iniciar_forja.ps1 -InstalarNaInicializacao   # cria a tarefa agendada
powershell -ExecutionPolicy Bypass -File scripts\iniciar_forja.ps1 -RemoverDaInicializacao    # remove
```

`iniciar_forja.ps1` faz backup consistente do banco antes de subir (guarda os 5 mais recentes), liga o Kiro real,
recusa porta ocupada e nunca lê nem mostra segredos.

---

## Como a Forja funciona

```
 Você (navegador)
     │  login por usuário e senha
     ▼
 Painel web ──► API /api/v1 (FastAPI, só 127.0.0.1) ──► Orquestração (máquina de estados, locks, orçamentos)
                                                           │
                    ┌──────────────────────────────────────┼─────────────────────────────┐
                    ▼                                      ▼                             ▼
          Provedor de agente                       Segundo cérebro                 Ferramentas determinísticas
   (Kiro CLI via ACP; mock nos testes)        (memória + grafo + código, FTS5)   (mapa, estrutura de código, testes…)
          │   ▲                                             ▲
          │   └── mediador de permissões (cada pedido do agente vira uma pergunta em linguagem natural)
          └────── MCP local opcional: o agente consulta a memória e as ferramentas da Forja sem ler arquivos inteiros
```

Princípios que valem em todo o código:

- **Local-first.** O servidor só escuta no próprio computador. Kiro CLI, ACP, MCP e SQLite nunca ficam expostos na rede.
- **Segredos nunca são lidos.** Nem pela Forja, nem pelo agente (perfil de segurança aplicado no Kiro, falha fechada).
- **Ferramenta determinística antes de LLM.** Testes, critérios e alegações são conferidos por código, não pela palavra do modelo.
- **Mock é rotulado.** Evidência simulada nunca valida nada.
- **Três grafos separados:** execução (tarefas), conhecimento (notas) e código (símbolos e chamadas).

---

## O painel, tela por tela

Barra de atividades à esquerda; o menu de cada área abre por cima do conteúdo (Ctrl+B). Conversa à direita (Ctrl+Shift+B)
e painel inferior (Ctrl+J). Tudo navegável por teclado, com descrição para leitores de tela e movimento reduzido respeitado.

| Área | O que faz |
|---|---|
| **Tela de acesso** | Primeiro acesso (cria usuário e senha), login, erro visível, bloqueio com contagem regressiva, "Sua conta" (trocar senha, sair). |
| **Tarefas** | Quadro Kanban (Backlog, Pronta, Em execução, Precisa de você, Concluída, Falhou). Criar tarefa com critérios sugeridos, preparar, executar, cancelar, **desfazer alterações**, ver **cópias isoladas** e projetos com pastas. |
| **Conversa** (direita) | Briefing do agente em seções (entendimento, plano, resposta, evidências, premissas, decisões). Uma resposta sua cobre todas as decisões e retoma a execução. Anexos e @menção de arquivos do projeto. Aba **Decisões** com as aprovações pendentes. |
| **Quadro** | Mensagens tipadas entre master, operador, sistema e agentes (comando, evento, apontamento, pergunta, resultado), por prioridade. |
| **Memória** | Grafo do segundo cérebro (estilo Obsidian): notas, [[wikilinks]], backlinks, ligações tipadas, base curada da Forja sob demanda, **Revisão (N)**, **Estudar e alimentar**, **Avaliar a busca**. |
| **Ferramentas** | Catálogo das ferramentas determinísticas, com execução e custo em tokens. |
| **Integrações** | Jira, GitHub, Trello, Notion, Google Agenda, Gmail, busca web, webhooks: desligados até você configurar; escrita só como proposta aprovada. |
| **Custo** | Créditos **estimados** por dia, parte, modelo e tarefa; alerta de desvio; taxa de sucesso do roteamento por nível. |
| **Config** (janela) | Preferências em 7 categorias (Agentes, Aparência, Eficiência, Consumo, Privacidade, Segurança, Manutenção), cada opção com explicação, exemplos e consequências. |
| **Painel inferior** | Eventos em tempo real (SSE), painel de controle do master e a **Oficina** pixel art. |

**Oficina pixel art** (só projeta o estado real; pode ser desligada): um personagem por papel (planejador, executor,
testador, revisor, estudante), animação pela ação atual (lendo, editando, comando, web, pensando, aguardando), contorno pela
complexidade, barra de orçamento, balão "aguardando você" que abre as decisões, cartão de detalhes, **replay** da execução
com passos e velocidade, descrição em `aria-live` e som opcional (desligado).

---

## Ciclo de uma tarefa

Estados (a interface nunca inventa transição; quem decide é o servidor):

```
rascunho → classificada → preparada → (aguardando_dependencias) → pronta → atribuida → executando → validando → concluida
                                                                                │
                                         aguardando_aprovacao ◄──┤          bloqueada (decisão sua, pasta ocupada, testes)
                                                                                └──► falhou | cancelada | expirada
```

1. **Criar**: título, descrição, modo (`analise`, `documentacao`, `alteracao_codigo`, `verificacao`, `estudo`) e critérios de aceite.
2. **Preparar**: valida dependências; vira `pronta` quando todas concluírem.
3. **Executar**: reserva as pastas, fotografa o que vai mudar (desfazer), monta o contexto e chama o agente.
4. **Durante**: cada ferramenta que o agente quer usar passa pelo mediador; orçamentos rígidos (chamadas de ferramenta,
   laço repetido, chamadas de modelo, tempo) interrompem com motivo.
5. **Concluir**: a Forja confere testes, critérios e alegações. Sem evidência, não conclui. Precisa de você? Fica `bloqueada`
   com as decisões agrupadas; responda na conversa e ela retoma.

Tarefas complexas podem ser **divididas em subtarefas** no planejamento (até 4, mais uma tarefa de consolidação), propostas
no Backlog ou executadas em paralelo, conforme a preferência `subagentes`.

---

## Roteamento e modelos

A Forja classifica cada tarefa sem LLM (texto, critérios, pastas, anexos, modo) e escolhe o fluxo:

| Nível | Parte do modelo | Fluxo | Contexto |
|---|---|---|---|
| simples | `rapida` (claude-haiku-5.5) | 1 turno | ×0,5 |
| normal | `execucao` (claude-sonnet-5.5) | 1 turno (+1 de correção se os testes falharem) | ×1 |
| complexa | `planejamento` (claude-opus-5.5, high) → `execucao` | plano + execução (+1 correção) | ×1,5 |

Partes especiais: `revisao` (opus-5.5, high) e `estudo` (haiku-5.5, usado também para resumir tópicos do segundo cérebro).
Cada parte tem modelos de reserva terminando em `auto`. Precedência: o que você salvou na tela > `APP_KIRO_MODEL` > padrão da Forja.
Modelo inexistente na conta bloqueia a execução (nunca roda num modelo diferente sem avisar).

**Roteamento que aprende:** se um nível tem menos de 60% de sucesso em 5+ execuções, as próximas sobem um degrau. Nunca rebaixa
sozinho; nível forçado na tarefa (`politicas.complexidade`) nunca muda.

---

## Aprovações, autonomia e regras

- **Por ação, agrupadas, com adendo.** "Posso excluir forçadamente `build`?" em vez do comando cru; pedidos simultâneos viram uma
  decisão; você aprova todos, alguns ou nenhum e pode escrever um adendo, que o agente recebe. Sem resposta no prazo: **negado**.
- **Nível de autonomia:** `restrito` (pergunta tudo), `liberado` (lê e edita na pasta de trabalho sem perguntar), `total`
  (também roda comandos dentro da pasta). Em qualquer nível, **sempre perguntam**: excluir, publicar, descartar alterações, instalar
  dependências, acessar a rede, agir fora da pasta e ações não identificadas.
- **Métodos (tags)** como "Cauteloso" ou "Orientado a testes" e **observações guia** (regras suas enviadas em toda tarefa).
- **Regras de controle** (Configurações > Segurança): negar, sempre perguntar ou aprovar por tipo de ação, trecho do comando e
  caminho (ex.: `*migrations*`). Vale a mais restritiva. Nenhuma regra libera segredo, pasta de consulta ou ação que sempre pergunta.

---

## Verificação: o que a Forja confere sozinha

- **Testes do projeto** (pytest, npm, cargo, go, conforme o projeto declara): primeiro os afetados pelos arquivos alterados, depois a
  suíte completa. Se falharem, a falha volta ao agente **uma vez** para correção. O resultado real vira evidência.
- **Isolamento dos testes:** árvore de processos presa (Job Object no Windows), teto de memória, TMP próprio; modo estrito troca
  o HOME e corta a rede. Proteção contra efeitos colaterais comuns, não contra código malicioso.
- **Critérios verificáveis:** `testes passam` e `arquivo: caminho` são conferidos; os demais ficam para você.
- **Alegações:** "rodei os testes", "criei o arquivo X" são comparadas com as ferramentas que o agente realmente usou.
- **Plano com decisão:** se o plano tiver uma decisão sua, a execução para **antes** de mexer em qualquer coisa.

---

## Projetos, pastas e anexos

Um projeto tem pastas de **trabalho** (o agente pode alterar, conforme a autonomia) e de **consulta** (só leitura, em qualquer
nível). Anexos de texto (redigidos) e imagens entram no pedido marcados como dado, nunca como instrução (spotlighting com código
aleatório por prompt). O explorador do projeto esconde `.env`, chaves e pastas ignoradas.

---

## Desfazer, pastas isoladas e retomada

- **Desfazer por tarefa:** antes de escrever, a Forja guarda uma cópia da pasta (fora do projeto e do Git). O botão volta só os
  arquivos que ninguém alterou depois; os outros aparecem como conflito (forçar exige confirmação).
- **Tarefas em paralelo:** pasta ocupada + Git = cópia isolada em `.worktrees/` num branch `forja/<tarefa>`; nada é mesclado sozinho.
  Sem Git, a segunda tarefa espera e retoma sozinha quando a pasta libera.
- **Queda do servidor:** execuções interrompidas ficam retomáveis pelo checkpoint; com `retomar_apos_queda = automatico`, retomam
  sozinhas no máximo uma vez.
- **Retomada compacta:** a Forja resume (sem LLM) o que a rodada anterior fez; se o contexto passou de 120 mil tokens, retoma numa
  sessão nova com esse resumo em vez de recarregar o histórico.

---

## Segundo cérebro (memória)

- **Notas** com tipo, namespace (`publico`, `pessoal`, `terceiros`, `empresa/<id>`), fonte, tags e estado epistemológico
  (`candidato → observado → verificado → validado`, além de contestado, obsoleto, substituído, revogado). Validar exige evidência
  **real**; PII e segredos são redigidos antes de gravar; resultados são sempre dados não confiáveis.
- **Busca** por termos (SQLite FTS5 com radicais, sinônimos e cobertura ponderada), símbolos de código, relações do grafo e,
  opcionalmente, semântica local (inativa por padrão). Notas realmente usadas pelas tarefas ganham um reforço pequeno.
- **Base curada da Forja** (`forja/conhecimento_base/`, ~70 notas em 10 áreas: engenharia, segurança, DevOps, banco, front-end,
  UX, QA, RPA, Python e agentes), somente leitura, organizada em tópicos e subtópicos. **Pacotes opcionais** (ex.: FastAPI) em
  `forja/conhecimento_pacotes/`.
- **Alimentação:** "Estudar e alimentar" pede a um agente que estude uma pasta permitida ou um tópico (com fontes) e crie notas
  candidatas ligadas por tópico. Ao concluir tarefas reais, a Forja registra decisões e aprendizados por projeto.
- **Organização automática** (a cada 30 min ou "Organizar agora", local e sem IA): sugere unir duplicatas, marcar notas velhas,
  ligar notas soltas e criar **tópicos**. Aceitar um tópico pede ao **Kiro** (parte `estudo`, modelo rápido) uma nota-tópico que
  resume o grupo e liga todas as notas a ela. Nada muda sem você aceitar na fila **Revisão (N)**.

---

## Contexto econômico

O agente recebe só o necessário: protocolo curto e fixo (cache de prefixo), memórias relevantes dentro de um orçamento de tokens
(`contexto_orcamento_tokens`), resumo do **grafo de funções** do projeto (até ~400 tokens) e referências curtas (`[M1]`) para citar.
Só o que foi citado conta como útil. Na retomada, vai apenas o que a rodada anterior usou. Com o MCP ligado, o agente consulta a
memória e o índice de código sob demanda em vez de ler arquivos inteiros.

---

## Ferramentas dos agentes e MCP

31 ferramentas determinísticas (`GET /api/v1/ferramentas`), entre elas:
`codigo.estrutura` (mapa, definição, referências, impacto, testes afetados, função, grafo), `codigo.outline`, `repo.mapa`,
`testes.resumir_saida`, `logs.agrupar_falhas`, `git.diff_analisar`, `segredos.varrer`, `sql.inspecionar`, `env.verificar`
(só presença de variáveis, nunca valores), `tokens.orcar`, `vault.indexar`, `web.buscar`/`web.ler_pagina` e as de integrações.
Ferramentas de arquivo só enxergam as **pastas permitidas** (desligado por padrão).

**MCP da Forja** (opcional, stdio, sem porta): `forja_listar_ferramentas`, `forja_executar_ferramenta`, `forja_buscar_memoria`,
`forja_navegar_memoria`, `forja_propor_nota`, `forja_quadro_ler`, `forja_quadro_publicar`. Cada uso passa pelas suas aprovações.

---

## Integrações externas

Jira, GitHub, Trello, Notion, Google Agenda, Gmail, agenda por URL, busca web (Brave ou SearXNG) e webhook de saída, além de
fontes locais (cofre Markdown, `.ics`, `.mbox`, planilhas, SQLite). Todas nascem **desligadas**. A tela recebe só o **nome** da
variável (`FORJA_INT_*`); o valor fica no `.env` do seu perfil. Somente HTTPS, restritas ao host configurado, com limite por
minuto e auditoria. **Escrita** (comentar, criar cartão, transicionar) só como proposta que você aprova em Integrações.

---

## Custo, telemetria e observabilidade

- **Custo:** créditos estimados = turnos × multiplicador do modelo (lista da sua conta); mock custa zero; alerta quando a semana
  passa do dobro da média. É estimativa: o valor cobrado aparece no painel da conta Kiro.
- **Telemetria OpenTelemetry** (desligada por padrão): rastros `gen_ai.*` (`invoke_agent`, `chat`, `execute_tool`) em JSONL nos logs
  ou enviados a um coletor OTLP **só em loopback** (`APP_OTEL_ENDPOINT`). Nunca levam prompt, resposta ou segredo.
- **Eventos** de tudo (SSE com replay por `Last-Event-ID`), logs JSON sanitizados e `GET /api/v1/recursos` (CPU, RAM, disco).

---

## Segurança

| Camada | Proteção |
|---|---|
| Rede | Bind em `127.0.0.1`; checagem de `Host` e `Origin` (CSRF/DNS rebinding); limite de requisições; CSP sem `unsafe-inline`. |
| Acesso | Login por usuário e senha (scrypt com sal), sessão só na aba, expiração por inatividade e em 12 h, bloqueio progressivo por conta e por endereço, mesma resposta para usuário inexistente. Token da API para scripts/MCP. |
| Agente | Perfil `forja` no Kiro com regras **deny** para segredos (falha fechada se o perfil não aparecer), mediador de permissões, pastas de consulta só leitura, orçamentos rígidos e detecção de laço. |
| Dados | Redação de PII/segredos, conteúdo recuperado marcado como dado (spotlighting), ACL por namespace antes de qualquer busca. |
| Repositório | `.gitignore`/`.kiroignore` testados (`tests/test_git_safe.py`), **gitleaks** no pre-commit e no CI (histórico inteiro, binário verificado por sha256). |
| Testes | Ambiente limpo (sem variáveis com cara de segredo), caixa de areia, tempo máximo. |

O que nunca é feito sem você: excluir, publicar (push), descartar alterações, instalar dependências, acessar a rede, agir fora
da pasta, deploy ou produção.

---

## Onde ficam os seus dados

Tudo que é seu fica **fora do repositório**, em `%LOCALAPPDATA%\Forja\perfis\<usuario>\` (mude com `APP_USER_HOME`/`APP_PROFILE`):

```
dados\forja.sqlite3        tarefas, memória, grafo, preferências, contas (hash), sessões
dados\backups\             cópias consistentes feitas pelo iniciar_forja.ps1
dados\artefatos\           respostas e relatórios (endereçados por hash)
dados\pontos\              cópias para o "desfazer"
credenciais\api_token.txt  token da API (scripts e MCP)
.env                       segredos das integrações (FORJA_INT_*), nunca no Git
logs\                      logs JSON sanitizados e telemetria opcional
```

Backup manual: `python scripts\backup_banco.py`. Migrar de `./data` (modo legado): `python scripts\migrar_dados_usuario.py --executar`.

---

## Hospedagem

| Forma | Quando usar | Kiro real? |
|---|---|---|
| **Nativa (recomendada)**: `scripts\iniciar_forja.ps1` | Uso diário neste computador. | **Sim**: usa o `kiro-cli` e o login do seu usuário do Windows. |
| `python -m forja --abrir` | Desenvolvimento. | Sim, com `APP_KIRO_ACP_ENABLED=true`. |
| Docker (`compose.yaml`) | Demonstração isolada com dados fictícios. | **Não**: o Kiro CLI do Windows e o login não existem no contêiner. |

A forma nativa é a certa para um computador só. O Docker não traz ganho aqui: o agente real depende do `kiro-cli` e do seu login
SSO no Windows, e a Forja já isola o que importa (loopback, perfil de dados, perfil de segurança no Kiro, caixa de areia dos testes).
O painel pode ser instalado como aplicativo (PWA) pelo Edge/Chrome: "Instalar Forja".

Docker, se quiser a demonstração:

```powershell
$env:FORJA_PORTA = 8790
docker compose up -d --build
docker compose exec forja python scripts/semear_demo.py --porta 8787 --pasta-trabalho /tmp/forja-demo-proj
docker compose exec forja python -m forja.usuario.contas_cli criar --usuario ana   # pede a senha
# http://127.0.0.1:8790
```

Contas pela linha de comando (qualquer forma): `python -m forja.usuario.contas_cli criar|redefinir|listar --usuario NOME`.

---

## Configuração (.env e tela)

A maior parte se ajusta na tela (Config). O `.env` (modelo em `.env.example`; nunca commitado) define o que vale antes da tela:

| Variável | Padrão | Para quê |
|---|---|---|
| `APP_PORT` / `APP_BIND_HOST` | 8787 / 127.0.0.1 | Endereço do servidor. Fora de loopback exige `APP_ALLOW_LAN_BIND=true` e login. |
| `APP_REQUIRE_AUTH` | true | Exige login (desligue só em testes). |
| `APP_SESSION_TTL_MINUTES` | 60 | Inatividade máxima da sessão. |
| `APP_KIRO_ACP_ENABLED` | false | Liga o Kiro real (o `iniciar_forja.ps1` liga). |
| `APP_KIRO_CLI_PATH` / `APP_KIRO_MODEL` | (auto) | Caminho do CLI e modelo padrão. |
| `APP_KIRO_PROMPT_TIMEOUT_SECONDS` | 300 | Tempo máximo por turno do agente. |
| `APP_APPROVAL_TIMEOUT_SECONDS` | 900 | Prazo para responder a uma aprovação (depois: negado). |
| `APP_CONTEXT_ENABLED` / `APP_CONTEXT_NAMESPACES` / `APP_CONTEXT_BUDGET_TOKENS` | true / publico / 2000 | Memória no contexto. |
| `APP_MEMORY_ALLOWED_NAMESPACES` | publico,pessoal | Namespaces desta instância. |
| `APP_OTEL_ENDPOINT` | 127.0.0.1:4318 | Coletor OpenTelemetry (só loopback). |
| `APP_USER_HOME` / `APP_PROFILE` / `APP_DATA_DIR` | (perfil) | Onde ficam os dados. |

Preferências da tela que mais mudam o comportamento: nível de autonomia, correção automática, limites de ferramentas e de tempo,
desfazer, pastas isoladas, subagentes, roteamento que aprende, retomada após queda, isolamento dos testes, modelos por parte,
pastas permitidas/proibidas, regras de controle, organização da memória, pacotes de conhecimento, MCP, busca semântica e telemetria.

---

## API

Documentação interativa em `http://127.0.0.1:8787/api/docs`. Principais grupos (todas sob `/api/v1`, com sessão ou token):

| Grupo | Exemplos |
|---|---|
| Acesso | `GET /auth/estado`, `POST /auth/configurar`, `POST /auth/entrar`, `POST /auth/sair`, `POST /auth/senha` |
| Tarefas | `POST /projetos`, `/objetivos`, `/tarefas`, `POST /tarefas/{id}/transicao`, `POST /tarefas/{id}/execucoes`, `POST /execucoes/{id}/iniciar\|pausar\|cancelar` |
| Conversa | `GET/POST /tarefas/{id}/conversa`, `GET /tarefas/{id}/contexto`, anexos em `/tarefas/{id}/anexos/*` |
| Aprovações | `GET /aprovacoes`, `POST /aprovacoes/{id}/decidir`, `POST /aprovacoes/decidir-lote` |
| Desfazer e isolamento | `GET /tarefas/{id}/restauracao`, `POST /restauracao/{id}/desfazer`, `GET/DELETE /isolamentos` |
| Memória | `POST /memorias`, `GET /memorias/buscar`, `GET /memorias/navegar`, `GET /memorias/revisao`, `POST /memorias/organizar`, `POST /memorias/sugestoes/{id}/decidir`, `/conhecimento/*`, `POST /estudos` |
| Visões | `GET /kanban`, `GET /conhecimento/grafo`, `GET /oficina`, `GET /execucoes/{id}/replay`, `GET /custos`, `GET /roteamento/estatisticas` |
| Sistema | `GET /saude` (pública), `/recursos`, `/kiro/status`, `/preferencias`, `/configuracao`, `/ferramentas`, `/integracoes`, `/quadro`, `GET /eventos/stream` (SSE) |

---

## Arquitetura do código

```
forja/
  servidor/        FastAPI: app, middleware de segurança, rotas por área (só tradução HTTP)
  orquestracao/    casos de uso: servico (estados, execuções), aprovacoes, roteamento, restauracao, isolamento,
                   subtarefas, aprendizado_rotas, custos, organizacao, oficina, estudos, contas_servico, memoria_servico…
  adapters/        kiro_acp (cliente ACP, provedor, mediador, perfil, sessão), sqlite (tabelas, repositório, FTS), agentes_mock
  dominio/         contratos Pydantic, estados, erros, tempo (sem dependências externas)
  memoria/         modelo (namespaces/ACL/estados), saneamento, indexador, base curada, semântica opcional
  contexto/        construtor de contexto com orçamento
  conversa/        briefing (seções, decisões, subtarefas) e conferência de alegações
  ferramentas/     ferramentas determinísticas, verificação de testes e caixa de areia
  seguranca/       ações (descrição/risco), pastas, regras do usuário, spotlighting, senhas, autenticação
  preferencias/    registro declarativo das opções e serviço com aplicação imediata
  integracoes/     conectores de rede e locais
  observabilidade/ logs, sanitização, recursos, telemetria OTel
  mcp/             servidor MCP da Forja (stdio)
  painel/estatico/ HTML/CSS/JS sem build (módulos ES), só consome a API
  migrations/      Alembic (0001…0013)
scripts/           iniciar_forja.ps1, backup, diagnóstico do Kiro, demo, inspeção do painel, benchmarks
tests/             pytest (unidade, integração, Kiro falso por subprocesso, API)
docs/              STATUS_IMPLEMENTACAO.md e ADRs 0001…0022
```

Camadas não se misturam: rotas não têm SQL, a orquestração não conhece HTTP, adaptadores não têm regra de negócio.

---

## Desenvolvimento e testes

```powershell
pip install -r requirements-dev.txt          # + requirements-ui.txt para o navegador real
python -m pytest -q                          # ~1080 testes (Kiro falso por subprocesso; nada real é chamado)
python -m ruff check forja tests scripts
pre-commit install                           # gitleaks + ruff a cada commit

# painel num navegador real (Playwright), com dados fictícios
$env:APP_REQUIRE_AUTH="false"; $env:APP_PORT="8799"; python -m forja      # outro terminal
python scripts\semear_demo.py --porta 8799
python scripts\inspecionar_painel.py --porta 8799 --interagir --a11y      # fluxos + acessibilidade (axe-core)
python scripts\inspecionar_painel.py --porta 8798 --login --a11y          # tela de acesso (servidor com login, sem conta)

python scripts\benchmark_busca.py            # qualidade da busca (recall/MRR/nDCG)
python scripts\benchmark_tarefas.py [--real] # roteamento e conclusão de tarefas (--real usa o Kiro e consome créditos)
```

O CI (GitHub Actions) roda gitleaks, ruff, a suíte, o painel em Chromium com acessibilidade e a tela de acesso.

---

## Limites conhecidos

- Um agente real por enquanto: o Kiro. A integração com outros (ex.: Codex) está em estudo.
- Workflows do Kiro IDE não são expostos pelo ACP; a Forja orquestra por conta própria.
- Pastas isoladas exigem Git e partem do último commit; sem Git, tarefas na mesma pasta rodam uma por vez.
- A caixa de areia dos testes não é contêiner; créditos são estimativa; busca semântica é opcional e pesada.
- Recuperar senha esquecida é pela linha de comando no próprio computador (não há e-mail).
- Licença ainda não definida (ver `docs/STATUS_IMPLEMENTACAO.md`).
