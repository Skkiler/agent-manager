# ADR-024: Segredos fora do alcance do shell, Codex vigiado, verificação sempre, créditos reais, processos reaproveitados e roteador inteligente

- Status: aceito
- Data: 2026-11-18
- Origem: `docs/RELATORIO_AVALIACAO_2026-11-18.md` (achados S1-S7, F1-F12, E1-E5, T1-T7) e decisões do usuário na mesma data.

## Contexto

A avaliação reproduziu, com dados fictícios e os agentes reais:

- S1: no nível `total`, o Kiro leu o `.env` por um comando de busca do PowerShell aprovado sozinho (o comando não cita `.env`).
- S2: o processo do Kiro herdava o ambiente inteiro da Forja, inclusive `FORJA_INT_*` (tokens das integrações).
- S3/S4: o Codex em `read-only` leu um arquivo fora da pasta do projeto sem pedir nada; os comandos dele rodam no sandbox sem passar
  pelo mediador.
- F1: uma correção de código "simples" terminava `concluida` sem a Forja rodar testes.
- E1: cada execução abria um processo novo do Kiro (2,5 a 4,6 s fixos). E2: o Kiro informa créditos reais por turno e a Forja ignorava.
- F6: o Codex rodava tudo no modelo/esforço padrão da conta (`high`): 72 s numa correção trivial.

Decisões do usuário: corrigir segurança e testes primeiro; mesmo no nível `total`, orientar a não tocar em segredos e usar uma cópia
sem o `.env`; manter o Codex ligado e validar o orquestrador de decisão entre Kiro e Codex; reaproveitar processos depois de medir
créditos reais; manter o painel em JS puro; arte própria na oficina.

## Decisões

1. **Fonte única de padrões de segredo** (`forja/seguranca/sensiveis.py`). Regex (classificador, ferramentas, cópia) e globs (perfil
   DENY do Kiro) saem da mesma lista, agora com `.git-credentials`, `*.tfvars`, `*.tfstate`, `kubeconfig`, `service-account*.json`,
   `.docker/config.json`, `.envrc`, `*.ppk`, `*.keystore` e as pastas `secrets/`, `.ssh/`, `.aws/`, `.gnupg/`, `.kube/`.
2. **Classificador de comandos** (`seguranca/acoes.py`): imprime ambiente por linguagem (`os.environ`, `process.env`,
   `[Environment]::`, `Get-Item Env:`, `cmd /c set`, `$NOME_SEGREDO`) = sensível; caminho absoluto/`~`/`..` dentro do comando = fora da
   pasta (o 1º token, o executável, não conta); comando ofuscado (`-enc`, `iex`, `| sh`) = "outra" (sempre pergunta); servidor que
   abre porta = rede; `$_` do PowerShell deixa de ser falso positivo; invólucro de shell do codex-acp é desembrulhado; novo sinal
   `varredura` (busca/cópia recursiva).
3. **Varredura em pasta com segredo nunca é automática** (`mediador.py`): o provedor confere só os NOMES das pastas; se houver
   segredo, comando de varredura pergunta (risco alto, aviso explícito), em qualquer nível e mesmo com regra "aprovar" do usuário.
4. **Cópia sem segredos** (`orquestracao/copia_segura.py`, preferência `copia_sem_segredos`, padrão `autonomia`): nos níveis
   `liberado`/`total`, em tarefa que escreve, se a pasta tiver segredo, o agente trabalha em `<pasta>/.forja-copias/<execução>/` sem
   segredos, `.git` e dependências. Ao terminar, a Forja devolve só o que mudou e só onde o usuário não mexeu (conflito = nada é
   sobrescrito, a cópia fica guardada); segredos nunca voltam. A cópia fica dentro do projeto para o Node achar `node_modules` e a
   verificação achar a `.venv` (`_python_do_projeto` sobe até 3 pastas; pytest com `--rootdir/--confcutdir`). Exclude local do Git.
   Pasta grande demais (20 mil arquivos / 400 MB) ou erro: segue na original com as outras proteções (evento `copia.indisponivel`).
   Rejeitado: git worktree (parte do HEAD e perde mudanças não commitadas; `.env` versionado iria junto).
5. **Regra de segredos em todo pedido e no perfil** (`perfil_kiro.SEGREDOS_REGRA`/`SEGREDOS_CURTO`): completa no perfil do Kiro e em
   tarefas que escrevem; curta em análise; completa + limite de pastas para o Codex (que não tem perfil DENY). Medido no Kiro real
   (nível total, mesmo pedido que antes vazou): o agente usou a busca nativa excluindo `.env` e não leu o segredo.
6. **Ambiente limpo também para o Kiro** (`_ambiente_processo` = `ambiente_limpo()`): sem `APP_*`, `FORJA_*` e nomes com cara de
   segredo. Conferido: login e respostas iguais.
7. **Codex vigiado em tempo real** (`codex_acp/provedor._leitura_proibida`): chamada que cita segredo ou caminho fora das pastas do
   projeto cancela o turno; a execução fica `bloqueada` e a resposta parcial NÃO é guardada. Testado no Codex real: bloqueado em 16 s,
   nada vazou. Perfis de permissão do Codex (`[permissions]`, via `CODEX_CONFIG` ou `.codex/config.toml`) foram tentados e a sessão
   foi recusada com "Internal error" no codex-acp 2.7.0/Windows; ficam para quando o adaptador suportar. Limite honesto: a vigia vê a
   chamada quando ela começa; uma leitura muito rápida pode chegar ao modelo antes do cancelamento (a resposta é descartada).
8. **Verificação sempre** (F1): toda tarefa que altera código numa pasta de trabalho roda os testes da Forja, inclusive no nível
   `simples`; o turno de correção continua só nas rotas que corrigem. Critério "testes passam" sem prova = `bloqueada`
   (`testes_sem_prova`). Lint declarado pelo projeto (ruff nos `.py` alterados; `npm run lint`) entra na mesma conferência e na
   rodada de correção; lint com problema vira pendência, sem bloquear sozinho.
9. **Créditos reais** (`provedor.registrar_creditos/medir_creditos`, `ConsumoMedicao.creditos`, `custos.py`, `views/custos.js`):
   `session_usage` é acumulado por sessão (medido: 0,0010 → 0,0020 → 0,0030 em 3 turnos iguais); a Forja guarda o maior valor por
   sessão e desconta o que já havia numa sessão reaberta. O painel mostra créditos medidos (com a cobertura) e a estimativa como referência.
10. **Processos reaproveitados** (`adapters/kiro_acp/pool.py`, preferência `reaproveitar_processos`, padrão ligado): uso exclusivo,
    sessões fechadas ao devolver (`session/close`), chave por comando + ambiente, até 2 ociosos por 15 min, 25 usos, aquecimento de 1
    processo do Kiro ao subir. Atualizações e pedidos de permissão de outra sessão são descartados/negados. Medido no Kiro real:
    pergunta simples 11,0-13,3 s → 6,3-6,5 s; correção 28,2 → 28,3 s (dominada por modelo e testes); créditos iguais.
11. **Codex com esforço por parte** (`ESFORCO_PADRAO`: rápida/status/coordenação `low`, execução/estudo `medium`,
    planejamento/revisão `high`; opção `reasoning_effort`) e aviso para não tentar rodar testes no sandbox dele (nesta máquina o
    `python` não existe lá). Medido: correção trivial 72,4 s → 35,2 s; pergunta simples ~20 s → 5,7-7,7 s.
12. **Roteador inteligente** (`agentes/roteador.decidir_inteligente`, padrão; `codex_ativo` padrão ligado). Base pública (comparativos
    de 2026): empate em benchmarks gerais; Claude com mais qualidade em mudanças multi-arquivo, refatoração e planejamento; GPT mais
    rápido, mais econômico em tokens e preciso em instruções curtas. Regra: estudo, coordenação, complexas, arquitetura, refatoração,
    migração, segurança, interface e alteração de código normal → Kiro; simples, status, verificação, análise/documentação normais e
    revisão (segunda opinião de outra família; revisão cruzada quando o autor é conhecido) → Codex. Pasta com segredo sem cópia →
    Kiro. Cada um é reserva do outro; o motivo vai no evento `provedor.escolhido`. Validado no real: pergunta simples → Codex;
    mesma pergunta em pasta com `.env` → Kiro.
13. **Ferramentas novas**: `codigo.buscar` (busca de texto/regex que pula segredos, dependências, binários; recusa regex com
    quantificador aninhado), `git.ler` (status/log/diff/blame/show/branches, só leitura, sem shell, `core.fsmonitor=false`,
    `--no-textconv`, refs sem `:`; segredos fora de status/diff), `testes.resumir_saida` com jest/vitest/go/cargo. O plano B
    `codigo.estrutura → repo.mapa` passa a disparar (pasta sem código) e a entrada do fallback leva só os campos aceitos.
14. Menores: texto do grafo de funções só cita `codigo.estrutura` com MCP ligado (F4); resumo com o nome do agente (F5); resposta
    parcial guardada também no tempo esgotado (F9); esforço fora da lista não quebra (F11); ferramentas MCP de caderno/memória deixam
    de cair em "ação não identificada".

## Consequências

- Mais proteção sem perder autonomia: no nível `total` o agente segue trabalhando sozinho, mas numa cópia sem segredos.
- Custo e tempo medidos com números reais; o roteamento por custo (Fase 6) pode usar `consumo.creditos`.
- O Codex continua com uma diferença de segurança: comandos dentro da pasta não passam pelas aprovações da Forja (o sandbox dele
  decide). A tela de Consumo explica isso.
- Pendências: perfis de permissão do Codex quando o adaptador aceitar; MCP da Forja para o Codex; créditos do Codex (o adaptador
  manda uso de tokens, ainda não lido); `_kiro/session/compact` (anunciado pelo kiro-cli 3.1.0) como alternativa à troca de sessão.
