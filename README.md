# Forja

Orquestrador **local** de agentes de IA para desenvolvimento de software. Você conversa com o **master**; ele entende o
pedido e cria tarefas. A Forja entrega cada tarefa a agentes reais (o **Kiro CLI** e, se você ligar, o **Codex**, ambos pelo
protocolo ACP), media cada permissão que o agente pede, confere o resultado por código (testes, critérios, escopo, alegações) e
guarda o conhecimento útil num **segundo cérebro** consultável. Tudo roda no seu computador: servidor em `127.0.0.1`, banco
SQLite no seu perfil e um painel web no navegador.

> Estado: em uso. Fases 0 a 4 e 9 implementadas e testadas (1118 testes automatizados, inspeção em navegador real e CI).
> Números medidos e pendências em [`docs/STATUS_IMPLEMENTACAO.md`](docs/STATUS_IMPLEMENTACAO.md); decisões em [`docs/adr/`](docs/adr/).
> Licença [Apache-2.0](LICENSE).

## Início rápido (fast-start)

Windows, sem administrador. Precisa de **Python 3.12+**, **Git** e do **Kiro CLI** com login feito (`kiro-cli login`).

```powershell
git clone https://github.com/Skkiler/agent-manager.git forja
cd forja
powershell -ExecutionPolicy Bypass -File scripts\instalar.ps1
```

O instalador cria o ambiente `.venv`, instala as dependências, confere o Kiro, deixa a Forja **no ar continuamente** (sobe
sozinha ao entrar no Windows e volta se cair) e abre `http://127.0.0.1:8787`. No primeiro acesso a tela pede para criar o
usuário (pode ser um e-mail) e a senha. Depois:

| Quero… | Comando (`powershell -ExecutionPolicy Bypass -File scripts\iniciar_forja.ps1 …`) |
|---|---|
| ver se está no ar | `-Status` |
| parar agora (volta no próximo login) | `-Parar` |
| tirar da inicialização | `-RemoverDaInicializacao` |
| subir à mão, numa janela | `-Abrir` |

Detalhes em [2 INSTALAÇÃO E HOSPEDAGEM](#2-instalação-e-hospedagem).

---

## Sumário

- [1 VISÃO GERAL](#1-visão-geral)
  - [1.1 Como a Forja funciona](#11-como-a-forja-funciona)
  - [1.2 Princípios](#12-princípios)
- [2 INSTALAÇÃO E HOSPEDAGEM](#2-instalação-e-hospedagem)
  - [2.1 Pré-requisitos](#21-pré-requisitos)
  - [2.2 Instalador](#22-instalador)
  - [2.3 Hospedagem contínua](#23-hospedagem-contínua)
  - [2.4 Execução manual](#24-execução-manual)
  - [2.5 Contas e acesso](#25-contas-e-acesso)
  - [2.6 Docker (só demonstração)](#26-docker-só-demonstração)
- [3 O PAINEL](#3-o-painel)
  - [3.1 Áreas](#31-áreas)
  - [3.2 Oficina pixel art](#32-oficina-pixel-art)
- [4 MASTER E SUB-MASTERS](#4-master-e-sub-masters)
  - [4.1 Conversa com o master](#41-conversa-com-o-master)
  - [4.2 Quando nasce um sub-master](#42-quando-nasce-um-sub-master)
  - [4.3 Limites](#43-limites)
- [5 CICLO DE UMA TAREFA](#5-ciclo-de-uma-tarefa)
  - [5.1 Estados](#51-estados)
  - [5.2 Etapas](#52-etapas)
  - [5.3 Subtarefas](#53-subtarefas)
- [6 AGENTES E MODELOS](#6-agentes-e-modelos)
  - [6.1 Roteamento por nível](#61-roteamento-por-nível)
  - [6.2 Perfis por papel no Kiro](#62-perfis-por-papel-no-kiro)
  - [6.3 Kiro e Codex](#63-kiro-e-codex)
  - [6.4 Roteamento que aprende](#64-roteamento-que-aprende)
- [7 CONTROLES DE QUALIDADE](#7-controles-de-qualidade)
  - [7.1 Aprovações, autonomia e regras](#71-aprovações-autonomia-e-regras)
  - [7.2 Controle de escopo](#72-controle-de-escopo)
  - [7.3 Verificação determinística](#73-verificação-determinística)
- [8 CONTEXTO E STATUS](#8-contexto-e-status)
  - [8.1 Contexto econômico](#81-contexto-econômico)
  - [8.2 Gestão de contexto](#82-gestão-de-contexto)
  - [8.3 Relatos de status](#83-relatos-de-status)
- [9 PROJETOS, DESFAZER E RETOMADA](#9-projetos-desfazer-e-retomada)
- [10 SEGUNDO CÉREBRO](#10-segundo-cérebro)
- [11 FERRAMENTAS, MCP E INTEGRAÇÕES](#11-ferramentas-mcp-e-integrações)
- [12 CUSTO E OBSERVABILIDADE](#12-custo-e-observabilidade)
- [13 SEGURANÇA](#13-segurança)
  - [13.1 Camadas de proteção](#131-camadas-de-proteção)
  - [13.2 Onde ficam os seus dados](#132-onde-ficam-os-seus-dados)
- [14 CONFIGURAÇÃO](#14-configuração)
  - [14.1 Variáveis de ambiente](#141-variáveis-de-ambiente)
  - [14.2 Preferências da tela](#142-preferências-da-tela)
- [15 API](#15-api)
- [16 ARQUITETURA DO CÓDIGO](#16-arquitetura-do-código)
- [17 DESENVOLVIMENTO E TESTES](#17-desenvolvimento-e-testes)
- [18 LIMITES CONHECIDOS](#18-limites-conhecidos)
- [19 LICENÇA](#19-licença)

---

## 1 VISÃO GERAL

### 1.1 Como a Forja funciona

```
 Você (navegador) ── login por usuário e senha
     │
     ▼
 Painel web ──► API /api/v1 (FastAPI, só 127.0.0.1) ──► Orquestração (estados, locks, orçamentos, escopo)
                                                           │
       ┌───────────────────────┬───────────────────────────┼──────────────────────────┐
       ▼                       ▼                           ▼                          ▼
 Master / sub-masters   Roteador de agentes         Segundo cérebro            Ferramentas determinísticas
 (decidem as tarefas)   Kiro (principal) e Codex    (memória, grafo, código)   (mapa, testes, segredos…)
                        (opcional), via ACP
                              │   ▲
                              │   └── mediador de permissões (cada pedido vira uma pergunta em linguagem natural)
                              └────── MCP local: memória, ferramentas e caderno da tarefa sob demanda
```

### 1.2 Princípios

- **Local-first.** O servidor só escuta no próprio computador. Kiro CLI, ACP, MCP e SQLite nunca ficam expostos na rede.
- **Segredos nunca são lidos.** Nem pela Forja, nem pelo agente (perfis de segurança no Kiro; o Codex só roda em pastas sem segredo).
- **Ferramenta determinística antes de LLM.** Testes, critérios, escopo e alegações são conferidos por código.
- **Mock é rotulado.** Evidência simulada nunca valida nada; telas mostram "simulado".
- **Três grafos separados:** execução (tarefas), conhecimento (notas) e código (símbolos e chamadas).

---

## 2 INSTALAÇÃO E HOSPEDAGEM

### 2.1 Pré-requisitos

- Windows 10/11 (alvo principal; Linux e macOS servem para desenvolvimento com `python -m forja`).
- Python 3.12 ou mais novo (testado em 3.13) e Git.
- **Kiro CLI** instalado e autenticado (`kiro-cli login`). Sem ele a Forja sobe, mas as execuções ficam bloqueadas com o motivo.
- Opcional: Node.js, para o Codex ([6.3](#63-kiro-e-codex)).

### 2.2 Instalador

`scripts\instalar.ps1` faz, de forma idempotente (rodar de novo só completa o que falta):

1. confere o Python;
2. cria `.venv` e instala `requirements.txt`;
3. diagnostica o Kiro (`scripts\diagnostico_kiro.py`: instalado, login, ACP respondendo), sem consumir créditos;
4. instala a tarefa agendada e a inicia;
5. espera o servidor responder e abre o navegador.

Opções: `-Porta 8790`, `-SemInicializacao` (só instala), `-NaoAbrir`.

### 2.3 Hospedagem contínua

#### 2.3.1 Tarefa agendada

A tarefa **"Forja (orquestrador local)"** roda na **sua** conta, sem privilégio de administrador, ao entrar no Windows, sem
janela. Usa o `kiro-cli` e o login SSO do seu usuário, que é o que um contêiner não teria.

#### 2.3.2 Supervisão e logs

- Se o servidor cair, a supervisão sobe de novo com espera crescente (5 s até 5 min); desiste depois de 10 quedas na mesma hora.
- Cada subida faz backup consistente do banco antes (guarda os 5 mais recentes) e limpa variáveis de teste do ambiente.
- Logs em `%LOCALAPPDATA%\Forja\`: `servidor.log`, `servidor.erro.log` e `supervisao.log` (a execução anterior fica em `*.1`).

#### 2.3.3 Comandos de controle

```powershell
$f = "scripts\iniciar_forja.ps1"
powershell -ExecutionPolicy Bypass -File $f -Status                   # tarefa, servidor e logs
powershell -ExecutionPolicy Bypass -File $f -Parar                    # para agora (encerra também os agentes abertos)
powershell -ExecutionPolicy Bypass -File $f -InstalarNaInicializacao  # (re)instala e inicia
powershell -ExecutionPolicy Bypass -File $f -RemoverDaInicializacao   # para e remove
```

### 2.4 Execução manual

```powershell
powershell -ExecutionPolicy Bypass -File scripts\iniciar_forja.ps1 -Abrir   # Kiro real, numa janela (Ctrl+C para parar)
python -m forja --abrir                                                     # desenvolvimento (agente simulado por padrão)
```

O painel pode ser instalado como aplicativo (PWA) pelo Edge/Chrome: "Instalar Forja".

### 2.5 Contas e acesso

- Primeiro acesso pela tela (só no próprio computador). O usuário aceita letras, números, `.`, `_`, `-`, `+` e `@` (e-mail serve).
- Senha com hash scrypt; sessão só na aba; bloqueio progressivo após erros.
- Linha de comando: `python -m forja.usuario.contas_cli criar|redefinir|listar --usuario NOME` (pede a senha sem mostrar).
- Acesso de outro computador só por túnel SSH ou HTTPS autenticado com firewall; nunca expondo a porta diretamente.

### 2.6 Docker (só demonstração)

`compose.yaml` sobe uma Forja **isolada, com agente simulado e dados fictícios**. Não é a forma de uso real: o Kiro CLI e o login
do Windows não existem no contêiner. Use só para mostrar a interface:

```powershell
$env:FORJA_PORTA = 8790; docker compose up -d --build
docker compose exec forja python scripts/semear_demo.py --porta 8787
docker compose down -v --rmi local      # apaga a demonstração
```

---

## 3 O PAINEL

Barra de atividades à esquerda; o menu de cada área abre por cima do conteúdo (Ctrl+B). Conversa da tarefa à direita
(Ctrl+Shift+B) e painel inferior (Ctrl+J). Tudo navegável por teclado, com descrição para leitores de tela e movimento reduzido.

### 3.1 Áreas

| Área | O que faz |
|---|---|
| **Master** (inicial) | Conversa com o coordenador. Ele cria tarefas e sub-masters, relata o andamento e consolida o resultado. Ao lado, a árvore master → sub-masters → tarefas, com link para cada conversa. |
| **Tarefas** | Quadro Kanban (Backlog, Pronta, Em execução, Precisa de você, Concluída, Falhou): criar, preparar, executar, cancelar, **desfazer alterações**, cópias isoladas e projetos com pastas. |
| **Conversa** (direita) | Briefing do agente em seções, relatos de status e verificação da Forja. Uma resposta sua cobre todas as decisões e retoma a execução. Anexos e @menção de arquivos. Aba **Decisões** com as aprovações pendentes. |
| **Quadro** | Mensagens tipadas entre master, operador, sistema e agentes, por prioridade. |
| **Memória** | Grafo do segundo cérebro (estilo Obsidian), backlinks, **Revisão (N)**, **Estudar e alimentar**, **Avaliar a busca**. |
| **Ferramentas** | Catálogo das ferramentas determinísticas, com execução e custo em tokens. |
| **Integrações** | Conectores externos, desligados até você configurar; escrita só como proposta aprovada. |
| **Custo** | Créditos **estimados** por dia, parte, modelo e tarefa; alerta de desvio; sucesso do roteamento por nível. |
| **Config** (janela) | Preferências em 7 categorias, cada opção com explicação, exemplos e consequências. |
| **Tela de acesso** | Primeiro acesso, login, bloqueio com contagem regressiva, "Sua conta" (trocar senha, sair). |

### 3.2 Oficina pixel art

No painel inferior; só projeta o estado real e pode ser desligada. Um personagem por papel (planejador, executor, testador,
revisor, estudante), animação pela ação atual, contorno pela complexidade, barra de orçamento, balão "aguardando você",
**replay** da execução e descrição em `aria-live`.

---

## 4 MASTER E SUB-MASTERS

### 4.1 Conversa com o master

Você escreve o pedido na área **Master**. Cada fala vira um turno do coordenador (parte `coordenacao`, perfil Kiro
`forja-coordenador`, sem ferramentas). Ele recebe o estado atual montado sem LLM (projetos, tarefas dele, sub-masters) e responde:

- `## Resposta`: para você, curta;
- `## Ações`: JSON com `criar_tarefa` e `criar_submaster`.

Quem decide é a Forja: cada ação é validada (formato, modo permitido pela sua autonomia, projeto, limites) antes de qualquer coisa
ser criada; as recusadas aparecem na conversa. Com a preferência `master_executar = executar`, as tarefas criadas já executam; com
`propor`, ficam prontas para você. Quando todas as tarefas de um lote terminam, o master ganha **um** turno de consolidação.
Decisões que só você pode tomar continuam na conversa da própria tarefa (o master avisa onde).

### 4.2 Quando nasce um sub-master

Só quando o pedido envolve **dois ou mais projetos** (ou já há sub-master ativo). Cada projeto ganha um coordenador próprio, que
age só nele e reporta ao master. Em um projeto só, o pedido vira uma tarefa: um coordenador a mais custaria turnos sem ganho.

### 4.3 Limites

| Limite | Valor |
|---|---|
| Ações por turno | 6 |
| Tarefas abertas por coordenador | 12 |
| Sub-masters ativos | 8 |
| Turnos do master / de cada sub-master | 40 / 15 |
| Profundidade | 2 (master → sub-masters → tarefas; sub-master não cria sub-master) |

Esgotado o orçamento, encerre a conversa ("Encerrar conversa") e um master novo é aberto. Os turnos internos não aparecem no Kanban.

---

## 5 CICLO DE UMA TAREFA

### 5.1 Estados

A interface nunca inventa transição; quem decide é o servidor.

```
rascunho → classificada → preparada → (aguardando_dependencias) → pronta → atribuida → executando → validando → concluida
                                                                                │
                                         aguardando_aprovacao ◄──┤          bloqueada (decisão sua, escopo, pasta, testes)
                                                                                └──► falhou | cancelada | expirada
```

### 5.2 Etapas

1. **Criar**: título, descrição, modo (`analise`, `documentacao`, `alteracao_codigo`, `verificacao`, `estudo`) e critérios de aceite.
2. **Preparar**: valida dependências; vira `pronta` quando todas concluírem.
3. **Executar**: escolhe o agente, reserva as pastas, fotografa o que vai mudar (desfazer), monta o contexto e chama o agente.
4. **Durante**: cada ferramenta passa pelo mediador; orçamentos rígidos (chamadas de ferramenta, laço, chamadas de modelo, tempo,
   arquivos alterados) interrompem ou perguntam.
5. **Concluir**: a Forja confere testes, critérios, escopo e alegações. Precisa de você? Fica `bloqueada` com as decisões agrupadas.

### 5.3 Subtarefas

Tarefas complexas podem ser divididas no planejamento (até 4, mais uma de consolidação), propostas no Backlog ou executadas em
paralelo, conforme a preferência `subagentes`.

---

## 6 AGENTES E MODELOS

### 6.1 Roteamento por nível

A Forja classifica cada tarefa sem LLM (texto, critérios, pastas, anexos, modo):

| Nível | Parte do modelo | Fluxo | Contexto | Limite de arquivos |
|---|---|---|---|---|
| simples | `rapida` (claude-haiku-5.5) | 1 turno | ×0,5 | 3 |
| normal | `execucao` (claude-sonnet-5.5) | 1 turno (+1 correção se os testes falharem) | ×1 | 10 |
| complexa | `planejamento` (claude-opus-5.5, high) → `execucao` | plano + execução (+1 correção) | ×1,5 | 25 |

Partes especiais: `revisao` (opus-5.5, high), `estudo` (haiku-5.5), `coordenacao` (sonnet-5.5, médio) e `status` (haiku-5.5,
baixo). Cada parte tem reservas terminando em `auto`. Precedência: o que você salvou na tela > `APP_KIRO_MODEL` > padrão.
Modelo inexistente na conta bloqueia a execução (nunca roda num modelo diferente sem avisar).

### 6.2 Perfis por papel no Kiro

A Forja grava em `~/.kiro/agents/` o perfil base `forja` e um por papel: `forja-planejador` (lê, sem escrita/shell),
`forja-executor`, `forja-revisor` (só leitura), `forja-estudo` (só leitura) e `forja-coordenador` (sem ferramentas). Todos têm as
mesmas regras **deny** de segredos e o contrato de escopo no prompt. A cada parte a sessão troca para o perfil do papel; se ele não
existir, usa o `forja`; se nenhum existir, a execução é bloqueada (falha fechada).

### 6.3 Kiro e Codex

#### 6.3.1 Distribuição

O Codex entra como segundo agente pelo mesmo protocolo (adaptador oficial `codex-acp`). Cada agente tem **contexto separado**: a
sessão pertence a quem a abriu e uma retomada volta para ele. Preferência `distribuicao_provedores`:

| Modo | Comportamento |
|---|---|
| `so_kiro` (padrão) | Tudo no Kiro; o Codex nem é consultado. |
| `auto` | Kiro primeiro; Codex de reserva quando o Kiro está indisponível (sem CLI, sem login, limite de uso). |
| `equilibrar` | Tarefas simples, revisões e status no Codex; o resto no Kiro (cada um é reserva do outro). |
| `codex_primeiro` | Codex primeiro, Kiro de reserva. |

A reserva só acontece quando o agente falhou **antes** de produzir trabalho; o que falhou fica 15 min em resfriamento.

#### 6.3.2 Como ligar o Codex

```powershell
npm i -g @agentclientprotocol/codex-acp     # adaptador ACP (precisa de Node.js)
codex login                                  # plano ChatGPT
```

Depois, em Config > Consumo: ligue `codex_ativo` e escolha a distribuição. `APP_CODEX_ACP_COMMAND` e `APP_CODEX_MODEL` são opcionais.
Confira as regras da sua organização antes de usar o Codex com código de empresa.

#### 6.3.3 Segurança do Codex

O Codex não tem as regras deny que a Forja aplica no Kiro. Por isso, em falha fechada:

- o processo recebe ambiente limpo (sem variáveis com cara de segredo e sem `APP_*`/`FORJA_*`; chave de API por variável não chega);
- só trabalha em pastas **sem** arquivos com cara de segredo (`.env`, chaves, credenciais); se houver, a tarefa fica bloqueada;
- modo da sessão: somente leitura para planejar, revisar, estudar, coordenar e status; escrita com aprovação para executar;
  nunca acesso total. Modo desconhecido = bloqueio.

### 6.4 Roteamento que aprende

Se um nível tem menos de 60% de sucesso em 5+ execuções, as próximas sobem um degrau. Nunca rebaixa sozinho; nível forçado na
tarefa (`politicas.complexidade`) nunca muda.

---

## 7 CONTROLES DE QUALIDADE

### 7.1 Aprovações, autonomia e regras

- **Por ação, agrupadas, com adendo.** "Posso excluir forçadamente `build`?" em vez do comando cru; você aprova todos, alguns ou
  nenhum e pode escrever um adendo, que o agente recebe. Sem resposta no prazo: **negado**.
- **Autonomia:** `restrito` (pergunta tudo), `liberado` (lê e edita na pasta de trabalho), `total` (também roda comandos na pasta).
  Sempre perguntam: excluir, publicar, descartar alterações, instalar dependências, rede, fora da pasta e ações não identificadas.
- **Métodos (tags)** e **observações guia** enviadas em toda tarefa.
- **Regras de controle** (Config > Segurança): negar, sempre perguntar ou aprovar por tipo de ação, comando e caminho. Vale a mais
  restritiva; nenhuma regra libera segredo.

### 7.2 Controle de escopo

Contra o agente "esticar" (fazer mais do que foi pedido, como criar documentação ou refatorar sem pedido). A causa medida é o
prompt do kiro-cli priorizar proatividade sobre o prompt do agente. A Forja não confia só na instrução:

1. **Contrato de escopo** forte e curto no perfil e em cada pedido.
2. **Durante:** passou do limite de arquivos do nível ([6.1](#61-roteamento-por-nível)), cada nova escrita **pergunta**, mesmo em
   autonomia `liberado`/`total`.
3. **Depois:** compara os arquivos alterados (medidos pelo ponto de restauração) com o plano e o limite e detecta documentação não
   pedida. Com `controle_escopo = pausar` (padrão), a tarefa fica `bloqueada` com a lista: desfaça com um clique ou responda
   aceitando. `avisar` só registra; `desligado` não confere.

### 7.3 Verificação determinística

- **Testes do projeto** (pytest, npm, cargo, go): primeiro os afetados, depois a suíte. Falhou: volta ao agente **uma vez**.
- **Isolamento dos testes:** árvore de processos presa (Job Object), teto de memória, TMP próprio; modo estrito troca HOME e corta rede.
- **Critérios verificáveis:** `testes passam` e `arquivo: caminho`.
- **Alegações** ("rodei os testes") comparadas com as ferramentas usadas de fato.
- **Plano com decisão:** para **antes** de mexer em qualquer coisa.

---

## 8 CONTEXTO E STATUS

### 8.1 Contexto econômico

O agente recebe só o necessário: protocolo curto e fixo (cache de prefixo), memórias relevantes dentro de um orçamento
(`contexto_orcamento_tokens`), resumo do **grafo de funções** do projeto e referências curtas (`[M1]`). Com o MCP ligado, consulta
memória e índice de código sob demanda em vez de ler arquivos inteiros.

### 8.2 Gestão de contexto

O ACP não deixa a Forja apagar mensagens da janela do Kiro. Então:

- **Caderno da tarefa** (fora da janela): o agente registra pelo MCP (`forja_caderno_salvar`) o que já resolveu, decidiu ou entendeu
  e consulta depois (`forja_caderno_consultar`) em vez de reler arquivos. Itens são redigidos e sem duplicata.
- **Ficha de estado** montada sem LLM: objetivo, critérios, caderno, alterações feitas e última verificação.
- **Renovação de sessão:** antes da etapa de execução do plano, do turno de adendos e da rodada de correção, se a sessão passou de
  `contexto_limite_sessao` (padrão 120 mil tokens medidos pelo Kiro), a Forja abre sessão nova com a ficha. O texto bruto continua
  no banco e nos artefatos.
- Aviso `kiro.contexto_inicial_alto` quando o primeiro turno já passa de 40% do limite (steering, skills ou arquivos grandes demais).

### 8.3 Relatos de status

Preferência `status_resumos`:

- `deterministico`: frases montadas dos eventos ("lendo auth.py", "testes falharam"), sem custo. `GET /execucoes/{id}/status`.
- `marcos` (padrão): quando uma tarefa termina ou para, um modelo barato (parte `status`, haiku, esforço baixo) escreve 1 a 3
  frases claras, **em lote** (até 6 tarefas por chamada, espera de 45 s, no máximo 20 chamadas por hora), sem ferramentas, só com
  os fatos dados. Falhou ou passou do teto: cai na frase determinística.
- O relato vai para a conversa da tarefa (se o agente não falou nela) e para a conversa do master que a criou.

---

## 9 PROJETOS, DESFAZER E RETOMADA

- **Projetos:** pastas de **trabalho** (o agente pode alterar, conforme a autonomia) e de **consulta** (só leitura). Anexos entram
  marcados como dado, nunca como instrução (spotlighting com código aleatório por pedido).
- **Desfazer por tarefa:** antes de escrever, a Forja guarda uma cópia (fora do projeto e do Git). O botão volta só os arquivos que
  ninguém alterou depois; os outros aparecem como conflito.
- **Paralelo:** pasta ocupada + Git = cópia isolada em `.worktrees/` num branch `forja/<tarefa>`; sem Git, a segunda tarefa espera.
- **Queda do servidor:** execuções interrompidas ficam retomáveis pelo checkpoint (`retomar_apos_queda`).
- **Retomada compacta:** resumo sem LLM do que a rodada anterior fez; contexto grande demais = sessão nova com a ficha.

---

## 10 SEGUNDO CÉREBRO

- **Notas** com tipo, namespace (`publico`, `pessoal`, `terceiros`, `empresa/<id>`), fonte, tags e estado
  (`candidato → observado → verificado → validado`, além de contestado, obsoleto, substituído, revogado). Validar exige evidência
  real; PII e segredos são redigidos antes de gravar.
- **Busca** por termos (FTS5 com radicais e sinônimos), símbolos de código, relações do grafo e, opcionalmente, semântica local.
- **Base curada** (`forja/conhecimento_base/`, ~70 notas em 10 áreas) e **pacotes opcionais** (`forja/conhecimento_pacotes/`).
- **Alimentação:** "Estudar e alimentar" cria notas candidatas a partir de uma pasta permitida ou tópico; tarefas reais registram
  decisões e aprendizados por projeto.
- **Organização automática** (local, sem IA): sugere unir duplicatas, marcar notas velhas, ligar soltas e criar tópicos. Aceitar um
  tópico pede ao Kiro (parte `estudo`) uma nota-tópico. Nada muda sem você aceitar em **Revisão (N)**.

---

## 11 FERRAMENTAS, MCP E INTEGRAÇÕES

- **31 ferramentas determinísticas** (`GET /api/v1/ferramentas`): `codigo.estrutura`, `repo.mapa`, `testes.resumir_saida`,
  `logs.agrupar_falhas`, `git.diff_analisar`, `segredos.varrer`, `env.verificar` (só presença), `tokens.orcar` e outras. As de
  arquivo só enxergam as **pastas permitidas**.
- **MCP da Forja** (stdio, sem porta; 9 ferramentas): `forja_listar_ferramentas`, `forja_executar_ferramenta`,
  `forja_buscar_memoria`, `forja_navegar_memoria`, `forja_propor_nota`, `forja_quadro_ler`, `forja_quadro_publicar`,
  `forja_caderno_salvar`, `forja_caderno_consultar`. Cada uso passa pelas suas aprovações.
- **Integrações** (Jira, GitHub, Trello, Notion, Google Agenda, Gmail, busca web, webhook e fontes locais): nascem desligadas; a
  tela recebe só o **nome** da variável (`FORJA_INT_*`), o valor fica no `.env` do seu perfil; só HTTPS; escrita só como proposta.

---

## 12 CUSTO E OBSERVABILIDADE

- **Custo:** créditos estimados = turnos × multiplicador do modelo; mock custa zero; alerta quando a semana passa do dobro da média.
- **Telemetria OpenTelemetry** (desligada): rastros `gen_ai.*` em JSONL ou para coletor OTLP **só em loopback**; sem prompt nem segredo.
- **Eventos** (SSE com replay), logs JSON sanitizados e `GET /api/v1/recursos`.

---

## 13 SEGURANÇA

### 13.1 Camadas de proteção

| Camada | Proteção |
|---|---|
| Rede | Bind em `127.0.0.1`; checagem de `Host` e `Origin`; limite de requisições; CSP sem `unsafe-inline`. |
| Acesso | Usuário e senha (scrypt), sessão só na aba, expiração, bloqueio progressivo, mesma resposta para usuário inexistente. |
| Agentes | Perfis `forja*` no Kiro com **deny** para segredos (falha fechada); Codex com ambiente limpo e só em pastas sem segredo; mediador de permissões; orçamentos; controle de escopo. |
| Coordenação | Ações do master validadas e limitadas; nunca aprova ação sensível nem executa trabalho. |
| Dados | Redação de PII/segredos, conteúdo recuperado marcado como dado, ACL por namespace. |
| Repositório | `.gitignore`/`.kiroignore` testados, **gitleaks** no pre-commit e no CI. |

Nunca sem você: excluir, publicar, descartar alterações, instalar dependências, rede, fora da pasta, deploy ou produção.

### 13.2 Onde ficam os seus dados

Fora do repositório, em `%LOCALAPPDATA%\Forja\perfis\<usuario>\` (mude com `APP_USER_HOME`/`APP_PROFILE`):

```
dados\forja.sqlite3        tarefas, master, caderno, memória, grafo, preferências, contas (hash), sessões
dados\backups\             cópias consistentes feitas a cada subida
dados\artefatos\           respostas e relatórios (endereçados por hash)
dados\pontos\              cópias para o "desfazer"
credenciais\api_token.txt  token da API (scripts e MCP)
.env                       segredos das integrações (FORJA_INT_*), nunca no Git
logs\                      logs JSON sanitizados e telemetria opcional
```

Backup manual: `python scripts\backup_banco.py`. Migrar de `./data`: `python scripts\migrar_dados_usuario.py --executar`.

---

## 14 CONFIGURAÇÃO

### 14.1 Variáveis de ambiente

O `.env` (modelo em `.env.example`; nunca commitado) define o que vale antes da tela:

| Variável | Padrão | Para quê |
|---|---|---|
| `APP_PORT` / `APP_BIND_HOST` | 8787 / 127.0.0.1 | Endereço. Fora de loopback exige `APP_ALLOW_LAN_BIND=true` e login. |
| `APP_REQUIRE_AUTH` | true | Exige login (desligue só em testes). |
| `APP_SESSION_TTL_MINUTES` | 60 | Inatividade máxima da sessão. |
| `APP_KIRO_ACP_ENABLED` | false | Liga o Kiro real (o `iniciar_forja.ps1` liga). |
| `APP_KIRO_CLI_PATH` / `APP_KIRO_MODEL` | (auto) | Caminho do CLI e modelo padrão. |
| `APP_CODEX_ACP_COMMAND` / `APP_CODEX_MODEL` | (auto) | Comando do adaptador do Codex (`codex-acp` no PATH) e modelo. |
| `APP_KIRO_PROMPT_TIMEOUT_SECONDS` | 300 | Tempo máximo por turno do agente. |
| `APP_APPROVAL_TIMEOUT_SECONDS` | 900 | Prazo de uma aprovação (depois: negado). |
| `APP_CONTEXT_ENABLED` / `APP_CONTEXT_NAMESPACES` / `APP_CONTEXT_BUDGET_TOKENS` | true / publico / 2000 | Memória no contexto. |
| `APP_MEMORY_ALLOWED_NAMESPACES` | publico,pessoal | Namespaces desta instância. |
| `APP_OTEL_ENDPOINT` | 127.0.0.1:4318 | Coletor OpenTelemetry (só loopback). |
| `APP_USER_HOME` / `APP_PROFILE` / `APP_DATA_DIR` | (perfil) | Onde ficam os dados. |

### 14.2 Preferências da tela

As que mais mudam o comportamento:

| Categoria | Preferências |
|---|---|
| Agentes | autonomia, correção automática, `subagentes`, `controle_escopo` (pausar/avisar/desligado), `master_executar` (executar/propor), métodos, observações guia |
| Eficiência | limites de ferramentas e tempo, contexto e orçamento, `contexto_limite_sessao`, `status_resumos` (desligado/deterministico/marcos), roteamento que aprende, MCP |
| Consumo | modelos por parte, `codex_ativo`, `distribuicao_provedores` |
| Segurança | pastas permitidas/proibidas, regras de controle, isolamento dos testes |
| Manutenção | desfazer, pastas isoladas, retomada após queda, organização da memória, pacotes, telemetria |

---

## 15 API

Documentação interativa em `http://127.0.0.1:8787/api/docs`. Todas sob `/api/v1`, com sessão ou token:

| Grupo | Exemplos |
|---|---|
| Acesso | `GET /auth/estado`, `POST /auth/configurar`, `POST /auth/entrar`, `POST /auth/sair`, `POST /auth/senha` |
| Master | `GET /master`, `POST /master/conversa`, `GET /coordenacoes/{id}`, `POST /coordenacoes/{id}/encerrar` |
| Tarefas | `POST /projetos`, `/objetivos`, `/tarefas`, `POST /tarefas/{id}/transicao`, `POST /tarefas/{id}/execucoes`, `POST /execucoes/{id}/iniciar\|pausar\|cancelar` |
| Conversa e contexto | `GET/POST /tarefas/{id}/conversa`, `GET /tarefas/{id}/contexto`, `GET/POST /tarefas/{id}/caderno`, `GET /execucoes/{id}/status`, anexos |
| Aprovações | `GET /aprovacoes`, `POST /aprovacoes/{id}/decidir`, `POST /aprovacoes/decidir-lote` |
| Desfazer e isolamento | `GET /tarefas/{id}/restauracao`, `POST /restauracao/{id}/desfazer`, `GET/DELETE /isolamentos` |
| Memória | `POST /memorias`, `GET /memorias/buscar`, `GET /memorias/navegar`, `GET /memorias/revisao`, `POST /memorias/organizar`, `POST /estudos` |
| Visões | `GET /kanban`, `GET /conhecimento/grafo`, `GET /oficina`, `GET /execucoes/{id}/replay`, `GET /custos`, `GET /roteamento/estatisticas` |
| Sistema | `GET /saude` (pública), `/recursos`, `/kiro/status`, `/provedores`, `/preferencias`, `/configuracao`, `/ferramentas`, `/integracoes`, `/quadro`, `GET /eventos/stream` |

---

## 16 ARQUITETURA DO CÓDIGO

```
forja/
  servidor/        FastAPI: app, middleware de segurança, rotas por área (só tradução HTTP)
  orquestracao/    casos de uso: servico, coordenacao (master), caderno, status, escopo, aprovacoes, roteamento,
                   restauracao, isolamento, subtarefas, custos, organizacao, oficina, estudos…
  agentes/         contrato do provedor, estilo/autonomia e roteador Kiro/Codex
  adapters/        kiro_acp (cliente ACP, provedor, mediador, perfis), codex_acp, sqlite, agentes_mock
  dominio/         contratos Pydantic, estados, erros, tempo
  memoria/ contexto/ conversa/ ferramentas/ seguranca/ preferencias/ integracoes/ observabilidade/ mcp/
  painel/estatico/ HTML/CSS/JS sem build (módulos ES), só consome a API
  migrations/      Alembic (0001…0014)
scripts/           instalar.ps1, iniciar_forja.ps1, backup, diagnóstico do Kiro, demo, inspeção do painel, benchmarks
tests/             pytest (unidade, integração, agente ACP falso por subprocesso, API)
docs/              STATUS_IMPLEMENTACAO.md e ADRs 0001…0023
```

Camadas não se misturam: rotas não têm SQL, a orquestração não conhece HTTP, adaptadores não têm regra de negócio.

---

## 17 DESENVOLVIMENTO E TESTES

```powershell
pip install -r requirements-dev.txt          # + requirements-ui.txt para o navegador real
python -m pytest -q                          # 1118 testes (agente ACP falso por subprocesso; nada real é chamado)
python -m ruff check forja tests scripts
pre-commit install                           # gitleaks + ruff a cada commit

# painel num navegador real (Playwright), com dados fictícios
$env:APP_REQUIRE_AUTH="false"; $env:APP_PORT="8799"; python -m forja      # outro terminal
python scripts\semear_demo.py --porta 8799
python scripts\inspecionar_painel.py --porta 8799 --interagir --a11y      # fluxos (inclui o master) + acessibilidade
python scripts\inspecionar_painel.py --porta 8798 --login --a11y          # tela de acesso (servidor com login, sem conta)

python scripts\benchmark_busca.py            # qualidade da busca (recall/MRR/nDCG)
python scripts\benchmark_tarefas.py [--real] # roteamento e conclusão (--real usa o Kiro e consome créditos)
```

O CI (GitHub Actions) roda gitleaks, ruff, a suíte, o painel em Chromium com acessibilidade e a tela de acesso.

---

## 18 LIMITES CONHECIDOS

- O Codex foi testado contra um agente ACP falso; a integração com o `codex-acp` real depende de você instalar e fazer login.
- Workflows do Kiro IDE e `/compact` não são expostos pelo ACP; a Forja orquestra e gerencia o contexto por conta própria.
- A hospedagem contínua é por sessão do Windows: a Forja fica no ar enquanto você estiver conectado.
- Pastas isoladas exigem Git; sem Git, tarefas na mesma pasta rodam uma por vez.
- A caixa de areia dos testes não é contêiner; créditos são estimativa; busca semântica é opcional e pesada.
- Recuperar senha esquecida é pela linha de comando no próprio computador.

---

## 19 LICENÇA

[Apache License 2.0](LICENSE). Avisos de atribuição em [`NOTICE`](NOTICE).
