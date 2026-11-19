# Ficha de contexto: Forja (para abrir um chat novo)

Atualizada em 2026-11-18. Esta ficha substitui o histórico do chat anterior: leia-a inteira antes de agir. Não contém segredos.

## 1 O projeto

- **Forja**: orquestrador local-first de agentes de IA para desenvolvimento. Python 3.13, FastAPI, SQLite + Alembic (migrações
  0001-0014), painel em JS puro (módulos ES, sem build). Repositório público `Skkiler/agent-manager`, branch `main`, licença Apache-2.0.
- Pasta: `c:\Users\joao.siqueira\Pessoal\3.0 - Codigos Python\.0. Estudos e projetos pessoais\1.7. Cod - Forja`.
- **Em uso real nesta máquina**: hospedada continuamente em `http://127.0.0.1:8787` pela tarefa agendada "Forja (orquestrador
  local)" (sobe ao entrar no Windows, sem janela, supervisionada). Kiro CLI 3.1.0 real, com login. Conta do usuário já criada
  (usuário é um e-mail; a senha foi dita no chat anterior, então **sugira trocá-la** em "Sua conta").
- Dados do usuário fora do Git: `%LOCALAPPDATA%\Forja\perfis\joao-siqueira\` (banco, backups, artefatos, credenciais, `.env`).
  Logs da hospedagem: `%LOCALAPPDATA%\Forja\` (`servidor.log`, `servidor.erro.log`, `supervisao.log`).

## 2 Arquivos de orientação (ler conforme a tarefa)

| Arquivo | Para quê |
|---|---|
| `AGENTS.md` | Regras essenciais de engenharia (curto; sempre vale). |
| `ORIENTACAO_MESTRA_ECOSSISTEMA_KIRO.md` | Orientação mestra; ler antes de mexer em arquitetura. |
| `PROMPT_INICIAL_KIRO.md` | Prompt de origem do projeto. |
| `.kiro/steering/00-principios.md`, `10-python.md`, `11-typescript.md`, `20-aprovacoes.md` | Princípios, Python, front-end, forma de pedir aprovação. |
| `.kiro/skills/diagnostico-arquitetural`, `.kiro/skills/revisao-seguranca` | Skills do workspace. |
| `.kiro/specs/forja-fundacao/{requirements,design,tasks}.md` | Spec; `tasks.md` tem os itens (último: 4.49; Fase 9 = 9.1-9.19). |
| `docs/STATUS_IMPLEMENTACAO.md` | Estado real, testes executados, pendências. **Atualizar ao fim de cada fase.** |
| `docs/adr/0001…0023` | Decisões. ADR-023 = master, Codex, contexto, escopo, status, perfis. |
| `docs/RELATORIO_AVALIACAO_2026-11-18.md` | Avaliação geral, achados de segurança/eficiência, ferramentas e direção visual. |
| `README.md` | Uso completo: fast-start, sumário e seções numeradas estilo ABNT (1, 1.1, 1.1.1). |

## 3 Regras do projeto e preferências do usuário

- **Segurança é invariante**: nunca ler, registrar ou publicar segredos, `.env`, tokens, credenciais, PII ou código de empresa.
  Dados de demonstração e de teste sempre sintéticos. Mock é rotulado e nunca conta como funcionalidade real.
- **Rede**: servidor só em loopback; Kiro CLI/ACP/MCP/SQLite nunca expostos. Acesso de fora só por túnel SSH ou HTTPS autenticado.
- **Camadas separadas** (rotas sem SQL, orquestração sem HTTP, adaptadores sem regra de negócio); três grafos separados (execução,
  conhecimento, código); ferramenta determinística antes de LLM; contratos tipados (Pydantic), logs sanitizados, testes reais.
- **Aprovações**: pedir pela ação em linguagem natural, agrupadas, aceitando adendo; declarar risco em ações de alto risco.
- **Já autorizado pelo usuário**: push para `main`; qualquer teste ("bandeira verde"); uso do Kiro empresarial para desenvolver.
  **Não autorizado ainda**: usar o Codex com código de empresa (conferir governança antes). Desde 2026-11-18 o Codex vem
  **ligado por padrão** (pedido do usuário) com o roteador `inteligente`: para projetos com código de empresa, use `so_kiro`.
- **Commit**: `git -c user.name=Kjo commit ...` (pre-commit roda gitleaks, ruff e checagens; nunca `--no-verify`). Depois do push,
  conferir o CI (`https://api.github.com/repos/Skkiler/agent-manager/actions/runs?per_page=1`; a API pública tem limite de taxa).
- **Ao terminar**: atualizar `docs/STATUS_IMPLEMENTACAO.md` com os testes realmente executados; relatório final **em português**.
- Sistema roda em **uma máquina só**. Código modular (SOLID), com salvaguardas, fallbacks e sem regressões.

## 4 O que foi feito (resumo das etapas)

- Fases 0-4: núcleo determinístico, adaptador Kiro ACP, memória FTS5 com namespaces/ACL, grafos, contexto econômico, conversa com o
  desenvolvedor, ferramentas, quadro, integrações, preferências, MCP, CI.
- Fase 9 (validação de mercado 9.1-9.19): desfazer por tarefa, pastas isoladas (worktree), retomada após queda, isolamento dos testes,
  telemetria OTel, custo estimado, regras de controle, organização do segundo cérebro (tópicos resumidos pelo Kiro), oficina pixel
  art com replay, gitleaks.
- Login por usuário e senha (scrypt, sessão, bloqueio progressivo; ADR-022). Usuário pode ser e-mail.
- **Última etapa (commit `f705048` + ajustes do Codex desta sessão), ADR-023, itens 4.42-4.49:**
  - **Master e sub-masters** (`forja/orquestracao/coordenacao.py`, tela `views/master.js`, rotas `servidor/rotas_coordenacao.py`):
    ações JSON validadas; limites 6 ações/turno, 12 tarefas abertas, 8 sub-masters, 40/15 turnos, profundidade 2; sub-master só com
    2+ projetos; consolidação por lote; turnos internos fora do Kanban.
  - **Kiro + Codex** (`forja/agentes/roteador.py`, `forja/adapters/codex_acp/provedor.py`): contextos separados, distribuição
    `so_kiro`(padrão)/`auto`/`equilibrar`/`codex_primeiro`, reserva só sem trabalho produzido. Codex em falha fechada: ambiente limpo,
    só pastas sem segredo, `read-only` para tudo que não escreve, `workspace-write` só para alterar; nunca `agent` (Auto review) nem
    `agent-full-access`.
  - **Gestão de contexto** (`orquestracao/caderno.py`): caderno da tarefa por MCP, ficha de estado sem LLM, sessão renovada acima de
    `contexto_limite_sessao` (120 mil tokens).
  - **Status barato** (`orquestracao/status.py`): frases determinísticas + resumo em lote pela parte `status` (haiku, esforço baixo).
  - **Controle de escopo / anti "esticar"** (`orquestracao/escopo.py`, mediador): contrato no perfil, escrita além do limite do nível
    (3/10/25) pergunta, conferência pós-execução com `controle_escopo = pausar`.
  - **2.8 perfis por papel** (`adapters/kiro_acp/perfil_kiro.py`): `forja`, `forja-planejador/executor/revisor/estudo/coordenador`.
  - **Hospedagem contínua**: `scripts/instalar.ps1` e `scripts/iniciar_forja.ps1` (`-Status`, `-Parar`, `-InstalarNaInicializacao`,
    `-RemoverDaInicializacao`, `-Abrir`, `-Supervisionar`). Queda forçada testada: volta sozinho.
  - Demonstração Docker apagada (contêiner, volume, imagem); `compose.yaml`/`Dockerfile` mantidos como demo de dados fictícios.
  - README reescrito; `LICENSE` (Apache-2.0 oficial) e `NOTICE`.
- **Codex nesta sessão**: a máquina tinha o app Codex da Microsoft Store (`OpenAI.Codex`) e o ChatGPT desktop, logados (`~/.codex`),
  mas **não** o adaptador ACP (o app do ChatGPT não fala ACP). Instalado `@agentclientprotocol/codex-acp` 2.7.0 (npm global, traz
  `@openai/codex`). Sonda real: login do app reaproveitado; modos `read-only | workspace-write | agent | agent-full-access`.
  Turno real "pronto" em 5,6 s; tarefa de análise real em pasta sintética concluída em 22,5 s em `read-only`. Na Forja hospedada o
  Codex aparece `configurado: true`, `ativo: false` (preferência `codex_ativo` desligada; ligar em Config > Consumo).

- **Etapa de 2026-11-18 (ADR-024)**: avaliação geral (`docs/RELATORIO_AVALIACAO_2026-11-18.md`) e correções aprovadas:
  lista única de segredos (`seguranca/sensiveis.py`), classificador de comandos reforçado, varredura em pasta com segredo sempre
  pergunta, **cópia sem segredos** (`orquestracao/copia_segura.py`), regra de segredos no perfil e em todo pedido, ambiente limpo no
  Kiro, **vigia do Codex** (cancela leitura fora da pasta), **verificação sempre** em tarefa de código (+ lint declarado),
  **créditos reais** (`consumo.creditos`), **processos reaproveitados** (`adapters/kiro_acp/pool.py`), esforço por parte no Codex,
  **roteador inteligente** (padrão; Codex ligado por padrão), ferramentas `codigo.buscar` e `git.ler`.
  O usuário decidiu: painel continua em JS puro sem build; oficina com arte própria; próximas etapas = fases visuais V1-V4.
- **Rodada 3 de 2026-11-18 (ADR-025)**: Codex no nível do Kiro (`CODEX_CONFIG` com `developer_instructions` + `shell_environment_policy`;
  o Codex recusa sozinho ler fora da pasta), MCP da Forja no Codex, `contentCollection` desligado no Kiro, coordenação com consulta
  filtrada e trava, laço A/B, roteamento, ferramentas (amostra com busca, outline CSS, fim de funções JS, teto de 30 s) e a
  **bancada** do painel: três visualizações (Editor estilo VS Code, Chat estilo Codex, Agentes em pixel art), painéis que empurram
  com divisórias, editor próprio (`js/editor.js` + `js/realce.js`), Explorador/Busca/Git/Docker (`js/area.js`), terminal e
  problemas (`js/inferior.js`), paleta (`js/comandos.js`), escritório (`js/escritorio.js`), API `/api/v1/area/*`
  (`orquestracao/area_trabalho.py`, `servidor/rotas_area.py`) e logomarca vetorizada (`icone.svg`, `logo.svg`).
- **Rodada 4 de 2026-11-18 (ADR-026)**: política "bloqueio só para agentes; usuário recebe aviso". O usuário lê/edita/busca
  segredos no painel (marcados `segredo`); ação arriscada responde 428 (`ConfirmacaoNecessaria`) e o painel reenvia com
  `confirmado: true` (`js/confirmar.js`). Terminal/Git/Docker do usuário com `ambiente_usuario()` (sem `APP_*`/`FORJA_*`), Git e
  Docker completos. **Assistente de comandos** determinístico (`forja/assistente/`: `catalogo.json` com 70 comandos, 14 perigos e
  14 receitas; `comandos.py`; `servico.py` com documentação por IA via tarefa no projeto `forja-comandos`; comandos do usuário em
  `<dados_dir>/comandos_usuario.json`). Painel: terminal com assistente (`js/inferior.js`, `js/completar.js`), receitas
  (`js/receitas.js`), telas Comandos e HTTP (`js/views/comandos.js`, `js/views/http.js`), diff lado a lado (`js/diff.js`, Myers),
  autocompletar local e F12 no editor, Ctrl+/ atalhos, `@` símbolos. Teto diário de créditos (`limite_creditos_dia`), ferramentas
  `deps.listar`, `json.consultar`, `tabela.resumir`, `links.verificar` (37 no total). **Perfil de permissão nativo do Codex**
  (`perfil_permissoes()` em `codex_acp/provedor.py`: estende `:workspace` + deny dos globs de segredo). Dados de demo com acentos.

- **Rodada 5 de 2026-11-19 (ADR-027)**: reciclagem de sessões antigas (`orquestracao/reciclagem.py`, tabela `reciclagem`, migração
  0015; só cria nota com valor, enriquece a existente, liga ao tópico do projeto; prévia e "Reciclar agora" em Config > Manutenção);
  ponte caderno ↔ segundo cérebro ↔ grafo (`ConhecimentoTarefa`, `GET /tarefas/{id}/caderno?amplo=true`, `links()` com ligações
  tipadas, contexto com o namespace do projeto, `POST /memorias?evitar_duplicata=true`); catálogo de autocompletar de código
  (`assistente/codigo.py` + `assistente/codigo/*.json`, 30 ramos, 969 itens; IA cria/atualiza ramo pelo projeto `forja-codigo`);
  LSP (`adapters/lsp/`: Pyright, typescript-language-server com typescript@5, HTML/CSS do VS Code, csharp-ls; instalação pela tela
  em `<dados>/lsp`, em fila); editor com completar por contexto, explicação, assinatura, hover e F12 pelo LSP (`js/completar.js`,
  `js/editorcfg.js`, `js/editor.js`); Config > Editor (`views/config_editor.js`, tipo `escolhas`); política `acesso_fora_pasta`
  (Kiro lê sozinho o caminho citado; Codex lê e registra) e `codex_pastas_com_segredo`; visual (`movimento.css`, `js/movimento.js`:
  dicas, transições, troca de tema, avisos).

## 5 Testes e verificações (último estado)

- `python -m pytest -p no:cacheprovider -q` -> **1280 passed** (~4,6 min).
- LSP real: Pyright, TypeScript, HTML e CSS instalados pela API e testados (`%TEMP%\forja_sonda\sonda_lsp.py`, `sonda_lsp_ui.py`).
- Testes reais desta etapa com Kiro e Codex: scripts e resultados em `%TEMP%\forja_sonda\` (fora do Git, dados fictícios).
- `python -m ruff check .` -> ok; `node --check` em todos os módulos JS -> ok.
- Navegador real: `inspecionar_painel.py --interagir --a11y` -> 136 OK, 0 falhas (14 vistas, axe sem violação); `--login --a11y` -> 0 problemas.
- Acessibilidade: árvore do Chromium + volta de Tab em 9 vistas limpa (NVDA não instalado; teste com leitor real pendente).
- Codex real com o perfil nativo: sessão aceita, deny aplicado pelo sandbox, sem vazamento (`c_rapida`, `c_fora`, `c_env_proc`).
- `benchmark_busca.py` global 0.94/0.87/0.89 (recall@5/MRR/nDCG@5).
- CI do commit `f705048`: verde.

## 6 O que falta

1. Bancada: C# com servidor de linguagem real (falta .NET SDK nesta máquina); teste com leitor de tela real (NVDA).
2. Codex: ler o uso/créditos do Codex; medir o roteador `inteligente`. Medir o ganho da reciclagem no contexto de tarefas reais.
3. Catálogo de comandos: ampliar com o uso real (a documentação por IA entra só após importação do usuário).
4. Medir com o Kiro real: taxa de pausas por escopo (falso positivo) e economia da renovação de sessão.
5. Lacunas antigas (ver STATUS): auditoria com leitor de tela, embeddings só se superarem o baseline (4.9), pool de processos ACP.

## 7 Como rodar e armadilhas do ambiente

- Antes do pytest, limpar variáveis: `Get-ChildItem Env: | Where-Object { $_.Name -like 'APP_*' -or $_.Name -like 'FORJA_*' } |
  ForEach-Object { Remove-Item "Env:$($_.Name)" }`.
- Kiro CLI fora do PATH em shells novos: `$env:Path += ";$env:LOCALAPPDATA\Kiro-Cli"`. npm global em `%APPDATA%\npm`.
- PowerShell 5: o stderr do git aparece como "erro" vermelho mesmo com sucesso; arquivos em `%TEMP%` às vezes falham na 1ª leitura.
- Edições por PowerShell podem gravar BOM UTF-8: preferir as ferramentas de edição de arquivo.
- Inspeção do painel: servidor de teste com `APP_DATA_DIR` temporário, `APP_REQUIRE_AUTH=false`, `APP_PORT=8799`,
  `APP_KIRO_ACP_ENABLED=false`, `APP_RATE_LIMIT_PER_MINUTE=3000`, Trello fictício; depois `semear_demo.py --porta 8799`.
  Tela de login: servidor com login na 8798, sem conta. Nunca usar a 8787 (é a instância real).
- `control_pwsh_process stop` pode deixar o `python -m forja` filho rodando: conferir a porta com `Get-NetTCPConnection` e parar o PID.
- Reiniciar a instância real depois de mudar código: `scripts\iniciar_forja.ps1 -Parar` e `-InstalarNaInicializacao`.
