# Estado da implementacao

**Atualizado:** 2026-11-06 (Fase 9: melhorias da validação de mercado, gitleaks e Docker; ver a seção "Fase 9" abaixo). **Fases 0 a 4 testadas; Fase 9 implementada (9.12 parcial). Abertos: licença (Fase 8, decisão sua); planos em estudo: multi-provedor (Codex), master/sub-masters, gestão de contexto.** Padrao de agente continua sendo o **mock SIMULADO**;
o Kiro real so e usado com `APP_KIRO_ACP_ENABLED=true` (validado em sessao autenticada na etapa anterior).

## Regra de publicacao (repositorio publico)
O repositorio publica apenas **logica, ferramentas, controle e orquestracao**. Nunca sobem: credenciais, tokens, dados internos
da empresa, conteudo do "segundo cerebro"/memoria, bancos, logs, respostas reais do Kiro. `data/` (onde vive o banco com a memoria),
`.env`, `*.sqlite3`, `knowledge/{privado,pessoal,empresa,terceiros}/`, `memoria-local/`, `segundo-cerebro/` estao em `.gitignore` e
`.kiroignore`, e **`tests/test_git_safe.py` (59 casos) quebra se alguma protecao for removida ou se algo privado for rastreado**.
O uso do Kiro empresarial para este projeto foi **informado pelo usuario como aprovado** para desenvolvimento.

## Ambiente verificado (esta maquina e o alvo)
- Python 3.13.5; Git 2.50.0; SQLite 3.49.1 (FTS5 disponivel); Node 24.18 (so para `node --check` do JS); Kiro IDE 1.4.121;
  Kiro CLI 3.1.0 autenticado (login feito pelo usuario). Terminal da sessao roda como **Administrador** (o CLI recomenda evitar).

## Resultados reais de teste (2026-11-08)
- `python -m pytest` -> **690 passed** (~115 s), exit 0, sem warnings; cobertura **93%** (a Fase 3 tinha 265 testes/91%). `ResourceWarning` continua tratado como erro.
- `python -m ruff check forja tests scripts` -> All checks passed. `node --check` do `app.js` -> ok.
- **Testes de mutacao nas defesas criticas (9 mutantes, 9 detectados):** ACL do FTS removida; `substr`->`LIKE`; raiz de ingestao nao
  verificada; evidencia simulada aceita; ACL ignorada ao carregar memoria; validacao ignora injection; validacao ignora contradicao;
  PII nao redigida no indice; ACL removida do ranker de simbolos. (Um mutante sobreviveu na 1a tentativa — teste do `_` era fraco —
  e foi reforcado ate ser detectado.)
- **Dados reais (o proprio repositorio da Forja, banco temporario):** 96 arquivos indexados em 0,68 s; reindexacao sem mudancas 0,18 s
  (96 inalterados); buscas exatas em 2–8 ms; `data/` e `.env` nunca entram no indice. Buscar `ClienteAcp` leva a `cliente.py:85`
  (a definicao), `MediadorPermissoes` a `mediador.py:50`, `descrever_acao` a `acoes.py:126`.
- Gate da Fase 3: uma tarefa nova encontra o procedimento sintetico validado (com fonte, pre-condicoes e estado) num repositorio de
  60+ arquivos, dentro do orcamento de 2.000 tokens estimados, sem devolver o repositorio.

## Bugs/lacunas reais achados e corrigidos nesta etapa
1. **Qualidade (so apareceu em dados reais):** buscar um simbolo devolvia um trecho do arquivo sem a definicao -> ranker de simbolos
   (exato > componente final > prefixo) + RRF; teste de regressao com arquivo longo.
2. **API:** `Query(pattern=...)` sobre `list[str]` estourava HTTP 500 em `?fonte=` -> `Literal`/enum.
3. **Semantica:** `apenas_validadas` deixava codigo bruto passar -> agora so memoria validada.
4. **Seguranca (lacuna):** `.kiroignore` nao cobria `id_rsa*`, `id_ed25519*`, `credentials.json`, `secrets.*` (o `.gitignore` cobria) ->
   acrescentados (so aditivo, mais bloqueio) e coberto por teste usando o `git check-ignore` real.
5. **Testes meus que eram falsos positivos** (`if False else True`, assercao vazia, cenario que nao montava o caso) -> reescritos.
6. **Bug de concorrencia em producao (Fases 1/2), pego como teste instavel (2 falhas em 12 execucoes):** artefatos sao enderecados por
   conteudo e duas execucoes simultaneas com resposta identica escreviam no MESMO `.tmp`; no Windows uma falhava com `PermissionError`
   e a tarefa nao concluia. Corrigido (`.tmp` unico por escritor; perder a corrida e aceitavel, pois o conteudo e identico por hash);
   teste deterministico (12 threads) que falhava 12/12 antes e passa agora; o teste antes instavel passou 25/25.
7. Suite de 107 s -> 44 s (banco migrado uma vez por sessao e copiado por teste).

## Fases

| Fase | Estado | Evidencia | Proximo passo |
|---|---|---|---|
| 0 — Diagnostico/Git-safe | testado | baseline; `.gitignore`/`.kiroignore` + `test_git_safe`; gitleaks no pre-commit e no CI | — |
| 1 — Nucleo deterministico | testado | testes + smoke | — |
| 2 — ACP/Kiro | testado (2.8 e 2.9 abertos) | ACP + aprovacao por acao, validado com Kiro real | 2.8 agentes/skills/Workflow; 2.9 pool/`session/load` |
| 3 — Memoria/grafo | **testado** (3.10–3.12 abertos) | 106 testes de memoria (43 dominio + 44 servico + 19 API) + 59 git-safe + mutacao + dados reais | 3.10 propostas de procedimento |
| 4 — Contexto/ferramentas | **testado** (4.7-4.9 abertos) | 396 testes, benchmark, Kiro real, mutacao | 4.7 ferramentas N0 medidas; 4.8 precisao NL em corpus real |
| 5 — Multiagentes | parcial (9.2, 9.8) | worktrees por pasta ocupada, subtarefas paralelas + consolidacao | scheduler com prioridade global |
| 6 — Aprendizado | parcial (9.9) | EWMA de sucesso por nivel/parte/modelo, promocao de rota | custo no criterio de rota |
| 7 — UI/LAN | testado (9.15-9.19) | oficina interativa; tunel SSH documentado no README; Docker em loopback | HTTPS com proxy (opcional) |
| 8 — Open source | planejado | — | licenca, CI, SBOM, release |

## Componentes novos (Fase 3)
- `forja/memoria/` — `modelo` (namespaces/ACL, estados, ontologia), `saneamento` (PII, segredos, injection, consulta FTS5 segura),
  `indexador` (varredura segura, simbolos AST, trechos), `contratos`.
- `forja/adapters/sqlite/memoria_fts.py` — SQL do FTS5 com ACL na consulta; ranker de simbolos. Migracao `0003`.
- `forja/orquestracao/memoria_servico.py` — ciclo de vida, promocao com evidencia real, contradicao, obsolescencia por origem,
  ingestao incremental, busca hibrida (FTS5 + simbolos, RRF), grafo tipado com escopo.
- `forja/servidor/rotas_memoria.py` — `/api/v1/memorias*`, `/conhecimento*`; painel com "Memoria e codigo". ADR-007.

## Fase 4 — resultados reais
- **Busca (benchmark sintetico versionado, k=3):** recall/MRR/nDCG 0,79/0,70/0,72 -> **0,94/0,87/0,89**; categoria "dificil" 0,44 -> 0,78; nenhuma categoria piorou.
- **Kiro real (tarefa sintetica + memoria validada sintetica):** seguiu o protocolo em secoes; 1 item de contexto (68 tokens estimados) citado como util;
  1 decisao com recomendacao; retomada concluiu sem novas decisoes. Prompt ~309 tokens estimados (inicial e retomada); retomada ~67% mais barata que reenviar prompt + resposta anterior (886 estimados). Tokens sao **estimados**, nao do provedor.
- **Indexacao de pasta local grande (apenas agregados; conteudo nunca registrado aqui):** ~2.867 arquivos, ~12,5 mil simbolos distintos. Acerto@3 de definicoes 99,8% (nomes unicos) e 98% (ambiguos).
  Latencia de busca por simbolo: mediana 135 ms -> 3,7 ms (p95 180 -> 13 ms) apos a migracao 0005; ingestao completa 137,7 s -> 23,7 s; incremental sem mudancas ~6 s.
- Auto-indexacao da Forja: 200/200 definicoes no top-3, mediana 3,8 ms.
- Consulta sem sentido (`assunto inexistente zzqxw`) agora reporta cobertura 0,33 (antes 1,00); teste de regressao + mutante morto.
- Mutacao: busca 4/4 e contexto 10/10 detectados (rodada anterior); cobertura de simbolo 1/1. Nao re-executei a rodada completa apos as ultimas mudancas.
- Lint: `ruff check` limpo; E501 passou a ser ignorado na config (textos PT longos), `ruff format` aplicado nos arquivos tocados; `node --check app.js` ok.
- Bugs achados e corrigidos: contadores `tokens_*` redigidos como segredo; resposta do Kiro truncada em 2000 car.; sombreamento de variavel na busca;
  autogenerate do Alembic propondo DROP das tabelas FTS; regressao de "relaxar termos raros"; mensagem >100k car.; stdin cp1252 no agente falso; cobertura de simbolo fixa em 1,0.
- Decisao: **sem criptografia em repouso** (ferramenta local, usuario unico); ver ADR-010.

## Ferramentas N0 (item 4.7) — resultados reais
- Novas: `forja/ferramentas/{contrato,outline,testes,diff}.py`, `tests/test_ferramentas.py` (17), `scripts/medir_ferramentas.py`. Somente leitura; segredos redigidos; saida rotulada como dado nao confiavel.
- Mutacao: 7/7 detectados (1 sobreviveu na 1a rodada: link simbolico sem teste; reforcado). Bug real achado pelo teste: o outline omitia o nome do metodo.
- Medicao no proprio repositorio (tokens **estimados**, ~4 car./token; compara com ler o material inteiro, nao com o que o agente leria de fato):
  outline de 29 arquivos .py >3.000 car.: 77.045 -> 5.283 tokens (reducao mediana 93,8%, minima 80,7%);
  resumo de pytest com 8 falhas: 675 -> 117 (82,7%; amostra sintetica pequena, saidas maiores tendem a reduzir mais);
  resumo de diff de 3 commits recentes: 97,1% a 98,8%.
- Limites: so pytest; diff por regex (sem AST); ferramentas ainda **nao expostas ao agente** (4.7b) — a economia real no Kiro nao foi medida.
## Ferramentas ampliadas, quadro, painel e propostas (itens 4.7b, 4.10-4.13, 3.10) — resultados reais
- **Novos:** `forja/ferramentas/{catalogo,caminhos,amostra,logs,mapa,segredos,esquema,conversor,orcamento}.py`; `forja/dominio/quadro.py`;
  `forja/orquestracao/{quadro_servico,propostas,aprovacoes,conversa_contexto}.py`; `forja/servidor/{rotas_ferramentas,rotas_quadro}.py`;
  migracao `0006`; testes `test_ferramentas_catalogo.py` (42), `test_quadro.py` (35), `test_propostas.py` (4). ADR-011.
- **Regressao/integridade:** `Servico` (1133 linhas) dividido em mixins (764 linhas) sem mudar a API; as 413 verificacoes anteriores seguiram verdes
  depois do refator. Benchmark de busca identico (recall/MRR/nDCG 0,94/0,87/0,89). O prompt do Kiro nao foi alterado (catalogo nao e injetado).
- **Mutacao (24 mutantes nas defesas novas):** 21 detectados (1 deles so depois de novo teste: difusao `todos` duplicada) e 3 equivalentes por
  defesa em camadas (`PRAGMA query_only` x `mode=ro`; recusa de caminho absoluto em `Contexto.resolver` x guarda lexica).
- **Bugs reais achados pelos testes:** oracle de existencia fora da raiz (`../x` inexistente 404 x existente 422) -> contencao lexica antes do
  `resolve`; scanner de segredos com 7 falsos positivos em 8 (`token = obter(...)`) -> detector proprio (agora 1 achado em `forja/`, o proprio
  regex de chave privada).
- **Economia medida (tokens estimados; baseline = ler o material inteiro):** outline de 38 arquivos 87.637 -> 6.143 (mediana 92,6%);
  diff de commits recentes 97,7% e 98,8%; pytest com falhas 82,7% (amostra pequena); esquema SQLite do DDL real 47,8% (3.104 -> 1.620).
  `repo.mapa` e `segredos.varrer` mostram ~100%, mas o baseline (ler o repositorio todo) e um limite superior irreal: nao use como ganho esperado.
  Em arquivo minusculo o resumo e MAIOR que o bruto (reducao truncada em 0): as ferramentas so compensam em material grande.
- **Limites:** ferramentas ainda nao expostas via MCP e a economia **dentro do Kiro real nao foi medida**; `origem` do quadro e declarada pelo chamador
  (token unico de operador); quadro ainda nao e alimentado automaticamente pelo orquestrador (4.14) nem aparece no painel web; sem timeout por
  ferramenta (tetos de tamanho de entrada); `logs.agrupar_falhas` e `dados.converter` medidos so em testes sinteticos; `sql.inspecionar` so SQLite.
- **Superficie nova (padrao desligada):** `APP_TOOLS_ROOTS` vazio = ferramentas de arquivo desligadas; ao ativar, o operador autenticado le arquivos dessas pastas.
## Painel IDE, configuracao por parte, integracoes e revisao (itens 4.15-4.19) — resultados reais
- **Novos (backend):** `dominio/{configuracao,revisao}.py`, `orquestracao/{configuracao_servico,visoes,grafo_servico,revisao}.py`, `adapters/kiro_acp/{modelos,sessao_config}.py`,
  `ferramentas/{vault,agenda,email_mbox}.py`, `integracoes/registro.py`, `memoria/wikilinks.py`, rotas `rotas_{visoes,sistema}.py`, migracao `0007`. **Novos (front):** `painel/estatico/` reescrito em 15 modulos ES. ADR-012.
- **Validacao dos checkpoints anteriores (re-executada agora):** suite completa 605 verdes; benchmark de busca identico (recall/MRR/nDCG 0,94/0,87/0,89);
  ciclo completo de migracoes (head -> base -> head, uma revisao por vez), sem deriva entre modelos e migracoes e FTS5 preservado (`test_migracoes.py`);
  smoke contra servidor real (mock): fluxo ponta a ponta concluido; Kiro real: handshake, listagem de modelos (21), sessao com modelo/esforco e bloqueio de modelo invalido.
- **Interface verificada num navegador real** (Edge via Playwright, `scripts/inspecionar_painel.py --interagir`): 6 vistas renderizam e 18 interacoes passam
  (abrir tarefa e ver briefing, arrastar para coluna invalida, resolver mensagem do quadro, abrir/editar/salvar nota e navegar por wikilink, buscar no grafo,
  salvar modelo por parte, pedir revisao sem executar, executar ferramenta, atalhos, nivel simples/avancado). Zero erros de console/CSP.
- **Bugs reais achados so no navegador/CLI real e corrigidos:** (1) tempestade de requisicoes: o replay do SSE ao conectar disparava um refresh por evento e estourava o rate limit
  (HTTP 429) -> debounce; (2) colisao de CSS (`.agente` da Oficina deformava as mensagens do agente); (3) render concorrente duplicava o conteudo do painel de conversa;
  (4) a CSP restritiva bloqueia `eval`, inclusive do Playwright (esperado: o teste usa `expect`); (5) `--model`/`--effort` sao **recusados** pelo engine v3 do Kiro e o agente
  **aceita modelo inexistente em silencio** -> aplicacao por `session/set_config_option` com validacao e falha fechada; (6) `email.ler_mbox` colocava corpo de e-mail em `dados`
  sem redigir segredos -> redacao agora em todo texto de `dados`.
- **Mutacao nas defesas novas:** 22 mutantes, 20 detectados de imediato e 2 depois de novos testes (busca multi-termo no grafo; `\n` escapado em `.ics`).
- **Limites:** economia em tokens das novas ferramentas nao foi medida no Kiro real; integracoes com rede/OAuth (Gmail API etc.) seguem planejadas e dependem da sua aprovacao;
  nao ha regressao visual automatizada nem auditoria com leitor de tela (so HTML semantico, foco visivel, ARIA de tabs e `prefers-reduced-motion`); grafo trunca em ~500 nos;
  a lista de modelos depende do CLI instalado e logado.

## Integracoes de rede configuraveis (item 4.20) — resultados reais
- **Novos:** `integracoes/{ambiente,rede,config,conectores}.py`, `orquestracao/integracao_servico.py`, `servidor/rotas_integracoes.py`, 6 ferramentas de rede no catalogo (`jira.*`, `github.*`, `agenda.ler_ics_url`),
  tela de configuracao em `Integracoes`, `tests/test_integracoes_rede.py` (85 testes). ADR-013. Registro reescrito: locais x rede x planejados.
- **Regra seguida:** a funcionalidade existe, **nada vem configurado nem ligado**; o segredo vive so no ambiente (`FORJA_INT_*`) e a tela guarda o NOME da variavel; tudo somente leitura.
- **Verificado:** 690 testes; mutacao nas defesas de rede (30 mutantes: 28 detectados, 1 depois de reforco, 1 equivalente no Python 3.13); navegador real (6 vistas e 23 interacoes, 0 erros de console/CSP);
  **uma chamada real de leitura** (`GET /rate_limit` em `api.github.com`, sem token e sem enviar dados) validou TLS, SNI e o IP fixado. O Jira so foi testado com transporte simulado: **nao ha Jira real validado**.
- **Bugs reais achados so no navegador/ambiente real:** (1) `input.list` e somente leitura e quebrava a tela de Configuracao (corrigido em `ui.js`); (2) `package-data` do `pyproject.toml` nao incluia `painel/estatico/js/`
  (um wheel perderia a interface; corrigido); (3) servidores demo antigos continuavam vivos apos parar o terminal e serviam codigo velho (cuidado operacional: confira `-m forja` em execucao); (4) `IcsUrl` lia o endereco pelo
  ambiente padrao em vez do injetado (corrigido antes de commitar).
- **Dependencia:** `httpx==0.28.1` passou de dev para runtime (fixa).
- **Limites/pendencias:** sem escrita em servicos; Gmail API/IMAP, Google Agenda API, Notion/Trello seguem planejados; Jira Cloud real, Server/DC e o `.ics` secreto precisam de validacao com credenciais reais suas;
  a lista de projetos/repositorios e a unica barreira de escopo (use tokens somente leitura); o limite de requisicoes agora e configuravel (menu Seguranca) e os arquivos estaticos do painel nao contam por padrao.

## Dados do usuario, menu de configuracoes e politica de pastas (itens 4.14, 4.23) — resultados reais
- **Novos:** `usuario/{layout,migracao}.py`, `scripts/migrar_dados_usuario.py`, `seguranca/pastas.py`, `preferencias/{registro,servico}.py`, `servidor/rotas_preferencias.py`, tela de Configuracoes reescrita (6 categorias x Gerais/Avancadas), `_avisar_quadro` no orquestrador. ADR-014.
- **Verificado:** 757 testes passando, cobertura 94 %, Ruff limpo; benchmark de busca inalterado (GLOBAL 0.94/0.87/0.89 com sinonimos); mutacao manual em 22 defesas novas (pastas, validacao de preferencias, concorrencia, layout fora do Git, isencao de estaticos, mascara de e-mail): 22 detectadas, 0 vivas;
  navegador real (Playwright/Edge): menu, abas, exemplo aplica valor, tema claro/automatico, pasta proibida salva, pasta permitida inexistente recusada, modelo por parte, 0 erros de console/CSP.
- **Auditoria do Git remoto (somente leitura):** 11 commits sem banco, `.env`, tokens reais, logs ou caminhos pessoais; unico dado pessoal: e-mail de autor/committer. **Nao foi reescrito** (exige force-push e sua decisao).
- **Migracao dos seus dados atuais (`./data`) NAO foi executada**: aguarda sua decisao. Enquanto isso o modo legado segue funcionando.
- **Limites:** o servidor so recusa dados dentro do repo quando o Git nao os ignora; backup do perfil e responsabilidade sua; agentes reais ainda nao publicam respostas proprias no quadro (depende do MCP, 4.7c); `ferramentas adicionais` do perfil tem a pasta, mas nao ha carregador.
## MCP, sessao reaberta, escrita com aprovacao e rotulagem (itens 4.7c, 2.9, 4.20b, 4.8) — resultados reais
- **Novos:** `forja/mcp/` (servidor stdio), `integracoes/produtividade.py` (Trello, Notion, Google Agenda, Gmail), `orquestracao/acoes_externas.py`
  + migracao `0008` (tabela `acao_externa`), `memoria/rotulagem.py`, `painel/.../views/rotulagem.js`, secao "Acoes aguardando voce" em Integracoes,
  preferencias `kiro_mcp_ativo` (padrao off) e `kiro_reusar_sessao` (padrao on). ADR-015.
- **Verificado:** 834 testes passando (suite completa), Ruff limpo, benchmark inalterado (GLOBAL 0.94/0.87/0.89); testes novos: `test_mcp.py` (24), `test_acp_sessao.py` (11), `test_integracoes_produtividade.py` (37),
  `test_rotulagem.py` (4). Mutacao em 32 defesas novas: 28 detectadas de primeira, 3 sobreviveram (validacoes do MCP mascaradas porque a API tambem recusava) e foram mortas com testes que provam que nenhuma requisicao sai; 1 equivalente (revalidacao redundante em `Jira.comentar`). Navegador real: 35 passos, 0 erros de console/CSP; achado e corrigido um `null` renderizado na tela de Integracoes.
- **Kiro real (kiro-cli 3.1.0, conta empresarial, MCP liberado na politica):** `session/load` reabriu uma sessao em OUTRO processo e o agente lembrou um codigo combinado antes.
  O MCP conectou e listou as 5 ferramentas (log `mcp.connect.ok`/`mcp.listTools.ok`); o Kiro as carrega sob demanda (`tool_load`). **Bug real achado so no Kiro real:**
  o prompt saia antes do MCP conectar (~2-4 s apos `session/new`) e o agente dizia que a ferramenta nao existia; corrigido esperando o sinal de prontidao (com teto).
  Medicao (mesma tarefa, "mapear o repositorio"): sem MCP 0,323/0,415/0,414 creditos (media 0,384); com MCP e uso pedido explicitamente 0,280 (1 chamada a `repo.mapa`);
  com MCP sem pedir, o agente NAO usou as ferramentas da Forja (0,299-0,412). Conclusao honesta: ha economia quando a ferramenta e usada, mas o agente nao a escolhe
  sozinho; MCP segue desligado por padrao. Amostra pequena (n=1 a 3).
- **Nao validado com servico real:** Trello, Notion, Google Agenda, Gmail e as escritas no Jira/GitHub (transporte simulado e dados ficticios). Precisam das suas credenciais.
- **4.8:** a ferramenta existe (Memoria > "Avaliar a busca"); a medicao sobre o seu corpus depende de voce rotular perguntas reais (>= 15 para decidir algo).
- **Limpeza do repositorio:** removidos caches (`__pycache__`, `.pytest_cache`, `.ruff_cache`, `.coverage`) e docs excedentes (`docs/REFERENCIAS_VISUAIS.md`,
  `docs/arquitetura/ferramentas-planejadas.md`); `AGENTS.md`, `ORIENTACAO_MESTRA_ECOSSISTEMA_KIRO.md` e `PROMPT_INICIAL_KIRO.md` foram **retirados de todo o historico**
  (git filter-repo + force-push com lease; backup em bundle feito antes, fora do repositorio) e entraram no `.gitignore`; continuam so locais.

## Autonomia, metodos, busca web, grafo editavel, CI e avaliacao real (itens 4.8, 4.9, 4.21, 4.22, 4.24-4.26) — resultados reais
- **Novos:** `agentes/estilo.py`, categoria Agentes nas preferencias (nivel, tags, observacoes), `integracoes/busca_web.py`, `integracoes/catalogo_conectores.py`
  (quebra de ciclo de import), `tabelas.LigacaoGrafo` + migracao 0009, `views/rotulagem.js`, `tema.css`, PWA (`manifest.webmanifest`, icones), `--abrir`,
  `.github/workflows/ci.yml`, `requirements-ui.txt`, `scripts/avaliar_busca_codigo.py`. ADR-016.
- **Seus dados:** `./data` migrado para o perfil (`%LOCALAPPDATA%\Forja\perfis\<usuario>`, banco integro, esquema atualizado; a pasta antiga ficou intacta com MIGRADO.txt).
  A pasta de codigos foi liberada (leitura + ingestao), sempre com `.git`, perfil e credenciais protegidos.
- **Git:** e-mail do autor reescrito em todo o historico para o endereco noreply do GitHub (force-push com lease; backup em bundle feito antes).
- **Verificado:** 881 testes passando (suite completa), Ruff limpo, benchmark publico inalterado (0,94/0,87/0,89); navegador real: 47 passos, 0 problemas, axe 0 violacoes
  nas 6 vistas, 6 vistas sem estouro horizontal a 420 px. Avaliacao no corpus real: ver ADR-016 (numeros e decisao do 4.9).
- **CI no GitHub (ubuntu-24.04, Python 3.13): verde** (lint, testes, navegador real, layout estreito, axe). Achados SO no Linux e corrigidos:
  (1) seguranca: caminho `..\x` nao era 'fora da pasta de trabalho' no POSIX (afetava a aprovacao automatica) -> `\` conta como separador em qualquer SO;
  (2) fixture de teste com `serialize()` de banco vazio recusado por algumas builds do SQLite, que vazava conexoes como ResourceWarning em outro teste;
  (3) inspetor com caminhos fixos do Windows; (4) Starlette nao fixado (CI instalava versao diferente) -> fixado. Falhas do CI viram anotacoes legiveis sem login.
- **Nao validado com servico real:** busca web (Brave/SearXNG) e os conectores do 4.20b.
- **Pendente de decisao:** busca hibrida com embeddings (4.9); pasta de trabalho do agente para os niveis liberado/total (hoje um diretorio isolado do perfil).

## Projetos com pastas, anexos e fallback hibrido (itens 4.27-4.29) — resultados reais
- **Novos:** `orquestracao/projetos_servico.py`, `servidor/rotas_projetos.py`, `views/projetos.js`, migracao 0010 (`projeto.pastas`, tabela `anexo`), pastas de trabalho/consulta no provedor e no mediador, modo da tarefa na tela. ADR-017.
- **Verificado:** 897 testes passando, Ruff limpo; navegador real: 52 passos, 0 problemas (projeto com pasta, @mencao, explorador sem `.env`, anexo enviado e removido), axe sem violacao grave.
- **Medido (ADR-017):** fallback hibrido por margem 1o-2o < 0,30 = recall@5 0,222 (hibrido sempre 0,218; busca atual 0,163), usado em 86% das perguntas; o custo dominante e indexar, nao consultar.
- **Pendente de decisao:** ativar o hibrido opcional (modelo ~220 MB, ~6 min de CPU na 1a indexacao). Nao validado com o Kiro real: se ele pede permissao para LER dentro da pasta de trabalho (no restrito, a pergunta depende disso).

## Perfil de segurança no Kiro, `.env` sem leitura, conferência de alegações e interface refeita (itens 4.30-4.33): resultados reais (2026-11-06)
- **Achado crítico no Kiro real (kiro-cli 3.1.0):** a política padrão lê qualquer arquivo da pasta de trabalho sem perguntar. Um `.env` fictício foi lido e o valor apareceu na resposta.
  Além disso, `--agent` é recusado pelo engine v3, então `APP_KIRO_AGENT` nunca funcionou.
- **Correção:** perfil `~/.kiro/agents/forja.json`, gravado pela Forja, aplicado como **modo** da sessão e combinado com presets por nível. O perfil tem regras `deny` para segredos e para comandos que imprimem o env.
  Falha fechada: em pasta de projeto, sem o modo a execução fica bloqueada. ADR-018.
- **Verificação no Kiro real com `.env` fictício:**
  - **restrito:** `nota.txt` lido sem perguntar; `.env` negado (`deny fs_read`, `Source: agent-profile`); `type .env` negado (`deny shell`); criar arquivo pediu permissão.
  - **liberado:** igual ao restrito, exceto que o arquivo foi criado sem perguntar.
  - As ferramentas MCP `@forja` continuam disponíveis no modo.
  - Pelo provedor completo, o próprio modelo se recusou a tentar ler o `.env` por causa do protocolo.
- **Novos:**
  - `adapters/kiro_acp/perfil_kiro.py`, `ferramentas/ambiente_env.py` (ferramenta `env.verificar`: só booleanos e nomes) e `conversa/alegacoes.py` (salvaguarda determinística contra "testes passaram" sem execução observada).
  - Mediador: comandos que **usam** o `.env` sem exibi-lo (`docker compose --env-file`...) contam como execução comum; comandos que imprimem o env são sensíveis.
  - Pesquisa de métodos contra o mercado (relatório implementado e removido; decisões e fontes no ADR-019).
- **Interface:**
  - Tokens de design: uma fonte, escala tipográfica, espaçamentos e camadas de z-index.
  - **8 paletas** (4 escuras + 4 claras) com contraste AA verificado por teste (`tests/test_paletas.py`) e prévia ao vivo.
  - Configurações em **janela flutuante** arrastável.
  - Menu lateral, conversa e painel inferior **sobrepostos**: não empurram o conteúdo, ficam inertes quando fechados e fecham com Esc ou clique fora.
  - Botões com altura fixa e reticências, com dica automática quando o texto é cortado. Textos longos ganham "Ler mais".
  - Avisos aparecem acima das janelas (popover). Ao arrastar um cartão, os painéis ficam translúcidos e deixam o ponteiro passar.
- **Verificado:**
  - **963 testes passando** (`python -m pytest`), Ruff limpo, `node --check` em todos os módulos JS.
  - Benchmark de busca inalterado (GLOBAL 0.94/0.87/0.89).
  - Navegador real (Edge + Playwright): **todos os passos OK, 0 problemas**; axe sem violações nas 6 vistas; 420 px sem estouro horizontal.
- **Achado pelo navegador:**
  - A janela de Configurações não reabria após recarregar a página: o endereço voltava para `#/tarefas`. Corrigido: `#/config` agora fica no endereço enquanto a janela está aberta.
  - A conversa sobreposta cobria a coluna de destino ao arrastar um cartão. Corrigido: os painéis ficam translúcidos durante o arraste.
- **Pendências:**
  - (resolvido na etapa seguinte) sinal "MCP pronto" com o modo `forja`; melhorias da pesquisa implementadas (ver abaixo).

## Melhorias da pesquisa, correção com testes reais, índice estrutural e semântica por nível (itens 4.34-4.36): resultados reais (2026-11-06)
- **Novos:**
  - Ferramentas: `ferramentas/estrutura.py` (`codigo.estrutura`: mapa, definição, referências, dependências, impacto, testes afetados) e `ferramentas/verificacao.py` (descobre e roda os testes do projeto com ambiente limpo).
  - Memória: `memoria/semantica.py` (busca semântica opcional por nível) + migração 0011.
  - Provedor: rodada única de correção, critérios verificáveis, orçamentos rígidos (laço e limite de chamadas), lembrete do objetivo, sinal `_kiro/mcp/status`, modelo de reserva, consumo medido pelo Kiro.
  - MCP compacto e paginado; contexto por referência com MCP; `env.verificar` lê o compose; sugestões de critérios na nova tarefa. ADR-019.
- **Verificado:**
  - **1009 testes passando**, Ruff limpo, benchmark inalterado (GLOBAL 0.94/0.87/0.89).
  - Navegador real: **63 passos OK, 0 problemas**, axe sem violações, 420 px sem estouro.
  - **Kiro real:** MCP pronto em 1,96 s pelo `_kiro/mcp/status` (modo `forja`).
  - **Kiro real:** correção de código num projeto sintético (o agente corrigiu; a Forja rodou o teste afetado e depois a suíte; PASSOU; os 2 critérios conferidos).
  - **fastembed real:** 31 vetores em 3,2 s.
- **Achado e corrigido:**
  - O gatilho do fallback tratava "1 único acerto" como dúvida; agora é confiança (só "nenhum resultado" ou margem < 30% aciona).
  - O caminho do arquivo editado não era lido no formato real do Kiro; agora usa o mesmo extrator do mediador.
  - **Achado pelo CI (Linux):** a nova execução dos testes podia usar *bytecode* velho. O `.pyc` é validado por mtime em segundos mais o tamanho, então uma correção do mesmo tamanho no mesmo segundo carregava o código antigo e o teste "continuava falhando".
    - Agora cada rodada usa um cache de *bytecode* novo e vazio (`PYTHONPYCACHEPREFIX`) e nunca grava no `__pycache__` do projeto.
    - Teste de regressão: falhava sem a correção (conferido) e passa com ela.
- **Pendências:**
  - A rodada de correção só reconhece pytest, npm test, cargo e go.
  - A semântica em `fallback`/`ativo` baixa o modelo na 1ª ativação (rede; aceito ao escolher o nível).

## Grafo de funções, hierarquia de modelos, roteamento, segundo cérebro base e estudo (itens 0.6, 4.37-4.40): resultados reais
- **Novos:**
  - Grafo de funções em `ferramentas/estrutura.py` (operações `funcao` e `grafo`), gerado por padrão no preparo de tarefas com pasta de trabalho.
  - Roteamento por complexidade em `orquestracao/roteamento.py`; hierarquia de modelos por parte (`dominio/configuracao.py`, padrões + reservas).
  - Segundo cérebro: base curada em `forja/conhecimento_base/` (63 notas em 10 áreas) com `memoria/base.py` (semeadura idempotente, navegação), mais `orquestracao/estudos.py` (estudo de pasta/tópico e registro de decisões).
  - MCP: `forja_navegar_memoria` e `forja_propor_nota`.
  - Benchmark de tarefas: `avaliacao/tarefas.py` + `scripts/benchmark_tarefas.py`. ADR-020.
- **Verificado:**
  - **1036 testes passando**, Ruff limpo, benchmark de busca inalterado (GLOBAL 0.94/0.87/0.89).
  - Navegador real: **65 passos OK, 0 problemas** (inclui a base no grafo sob demanda e o pedido de estudo), axe sem violações.
  - **Kiro real, 6 tarefas sintéticas, 6/6 com sucesso e roteamento 100% correto:**
    - simples: haiku-5.5, 1 chamada, 13 a 16 s;
    - normal: sonnet-5.5, 1 chamada, 24 a 36 s, testes da Forja passaram;
    - complexa: plano em opus-5.5/high e execução em sonnet-5.5/high, 2 chamadas, 82 s, testes passaram.
- **Achado e corrigido:**
  - Trabalho com testes/critérios falhando era registrado como `concluida`; agora vira `bloqueada`.
  - O grafo de conhecimento ignorava subnamespaces (`publico/x`) por comparação exata; agora usa a mesma regra de prefixo da ACL.
  - Chamadas `obj.get()` viravam falsas ligações no grafo de funções; agora a resolução é conservadora e considera os imports.
- **Planejado, não implementado:** itens 9.1 a 9.19 em `tasks.md` (validação de mercado: checkpoint/rollback, worktrees, execução durável, OpenTelemetry GenAI, sandbox, consolidação de memória, melhorias da oficina pixel art).
- **Pendentes:**
  - 0.5: instalar gitleaks/detect-secrets exige sua aprovação.
  - 2.8: Workflows/skills do Kiro não confirmados na conta.

## Fase 9 — validação de mercado (9.1-9.19), gitleaks (0.5) e Docker: resultados reais (2026-11-06)
Decisões no ADR-021; migração 0012 (aditiva). Novos módulos: `orquestracao/{restauracao,isolamento,subtarefas,aprendizado_rotas,custos,
organizacao,oficina}.py`, `observabilidade/telemetria.py`, `ferramentas/sandbox.py`, `seguranca/{regras,spotlight}.py`; vista "Custo",
fila "Revisão (N)", editor de regras, pacotes de conhecimento (`forja/conhecimento_pacotes/fastapi`) e oficina reescrita.
- `python -m pytest` -> **1075 passed** (230 s; eram 1036). Novos: `test_orquestrador_melhorias.py` (12), `test_orquestrador_inteligencia.py` (14),
  `test_cerebro_oficina.py` (11). `ruff` limpo; `node --check` em todos os JS: 0 erros.
- `scripts/benchmark_busca.py` -> GLOBAL **0,94/0,87/0,89** (igual ao anterior: o reforço por uso não altera o corpus sintético, usos = 0).
- Navegador real (Edge, servidor nativo, `--interagir --a11y`): **91 passos OK, 0 problemas**; axe-core sem violação nas 7 vistas
  (inclui a nova "Custo"); layout estreito sem estouro. Fluxos novos: desfazer (arquivo criado pelo mock some), cópias isoladas,
  custo e período, Revisão (organizar, unir duplicata, promover candidata), regra criada/removida, pacote FastAPI instalado/removido,
  telemetria, oficina (papel, orçamento, aria-live, setas/Home/End, replay com passos e velocidade, balão abre Decisões).
- **Docker** (`compose.yaml`, imagem não-root, somente leitura, `cap_drop: ALL`): healthy; publicado só em `127.0.0.1:8790`, token
  obrigatório; semeado dentro do contêiner; inspeção com token: **31 passos OK, 0 problemas**, axe-core sem violação.
- **gitleaks 8.30.1**: histórico (26 commits) tinha 14 achados, todos fixtures SINTÉTICAS dos testes de redação (conferidas com o valor
  mascarado); `.gitleaks.toml` libera só a regra genérica e só em `tests/`. Depois: 0 achados no histórico e na árvore. Pre-commit instalado.
- Kiro real (3.1.0), sem créditos: a sessão anuncia como comandos só `context-gatherer`, `forja`, `general-task-execution` (sem `/compact`);
  por isso a compactação (9.7) é feita pela Forja (resumo determinístico + sessão nova acima de 120 mil tokens).
- **Bug real achado pela inspeção e corrigido:** `#area` com `overflow: hidden` rolava para o lado num foco programático (os painéis
  recolhidos ficam transladados para fora); o conteúdo ficava deslocado sem barra de rolagem. Agora `overflow: clip`.
- Isolamento de testes (9.5) provado: o processo "neto" de um teste que estoura o tempo morre junto (Job Object no Windows).
- Limites honestos: worktree exige Git e parte do último commit; o sandbox não é contêiner; créditos são estimativa; 9.12 não resume
  clusters em tópicos (só sugere duplicata, nota velha e ligação); subtarefas sem Git na mesma pasta rodam uma de cada vez.

## Login por usuario e senha (item 4.41, ADR-022): resultados reais (2026-11-06)
- Antes: o dialogo do token nao conferia nada, nao mostrava erro nem sucesso e voltava para a mesma pagina.
- Agora: contas locais (scrypt com sal, migracao 0013), primeiro acesso so no proprio computador (ou pela linha de comando
  `python -m forja.usuario.contas_cli`), sessao de 256 bits guardada so como sha256, inatividade de `APP_SESSION_TTL_MINUTES`
  e teto de 12 h, bloqueio progressivo por conta e por endereco, mesma mensagem para usuario inexistente. O token da API
  continua valendo para scripts, MCP e CI.
- `python -m pytest` -> **1082 passed** (206 s); `tests/test_contas.py` (6 testes) repetido 3x sem falha intermitente.
- Navegador real, servidor COM login e sem conta (`inspecionar_painel.py --login --a11y`): **12 passos OK, 0 problemas**, axe-core
  sem violacao na tela de acesso (primeiro acesso, senhas diferentes, senha comum recusada, medidor de forca, mostrar senha,
  sucesso -> painel, sair, senha errada com alerta, sessao invalida volta ao login, bloqueio com contagem regressiva).
- Sem regressao no painel sem login: `--interagir --a11y` -> 91 passos OK, 0 problemas.
- Docker: conta `demo` criada pela linha de comando (senha lida da entrada padrao); login, erro e sair conferidos no navegador.
- CI ganhou o passo "Tela de acesso" (servidor com login na porta 8798).

## Uso real, topicos pelo Kiro (9.12) e 2.8 (2026-11-06)
- **Forja real em uso:** `scripts/iniciar_forja.ps1` (backup do banco antes de subir, Kiro real, so 127.0.0.1:8787, tarefa agendada
  opcional). Subiu com o perfil real do usuario; primeiro acesso pendente de o usuario criar a conta na tela.
- **9.12 concluido:** a organizacao sugere TOPICOS (4 a 25 notas com a mesma tag sem um topico comum). Aceitar cria uma tarefa de estudo
  (parte 'estudo' = claude-haiku-5.5) com as notas marcadas como dado; ao concluir, a nota-topico candidata e criada e as notas ligadas.
  **Kiro real:** 4 notas sinteticas -> tarefa concluida em 19,1 s com claude-haiku-5.5; topico "Fila: regras de saida, prioridade e
  concorrencia" com 4 subtopicos, sem inventar fatos e apontando lacunas.
- **2.8:** sonda sem creditos no kiro-cli 3.1.0 aberto no repositorio: modos `vibe, spec, quick-spec, bug-fix, plan, autonomous,
  semantic_reviewer, forja, arquiteto, explorador, implementador, revisor`; comandos `context-gatherer, general-task-execution` e as
  skills do workspace. Workflows do IDE nao aparecem no ACP.
- README reescrito (sistema completo). `python -m pytest` -> 1083 passed.

## Limites da Fase 4 (honestos)
- Busca lexical; sem embeddings. Stemmer PT aproximado. **Precisao em linguagem natural sobre o corpus real nao foi medida** (exige rotulagem manual).
- Prompt de retomada tem tamanho parecido com o inicial; a economia e frente ao reenvio ingenuo, nao absoluta.
- `memoria_fts` ainda varre na remocao (aceitavel para poucas memorias).
- Economia das ferramentas planejadas **nao medida**.
- `session/load` do ACP e pool de processos continuam abertos (2.9).
## Limitacoes e pendencias (honestas)
- **Sem embeddings/vetores, sem Tree-sitter (AST so para Python; regex leve para md/js/ts/ps1/sql), sem OCR/PDF.** Watcher existe so no script de ingestao.
  Busca e lexical com radicais/sinonimos e expansao por grafo (ver Fase 4).
- **Sem criptografia em repouso (decisao consciente, ADR-010):** protecao por ACL, `.gitignore`/`.kiroignore` e permissoes do SO. Reavaliar se o banco for a disco compartilhado.
- IDF do bm25 considera o corpus inteiro (sem vazar conteudo, mas com influencia numerica minima entre namespaces).
- Heuristicas de PII/injection (regex) reduzem risco, **nao** o eliminam; resultados sao sempre tratados como dados nao confiaveis.
- `confianca` e informada pelo usuario e **nao calibrada**; nao entra no ranking.
- A memoria e injetada no prompt apenas para namespaces em `APP_CONTEXT_NAMESPACES` (padrao `publico`).
- Painel (JS): verificado em navegador real por script (Playwright), nao ha CI; auditoria com leitor de tela pendente.
- gitleaks e CI ativos (ver Fase 9). Um processo `kiro-cli` por execucao (sem pool).

## Retomada sem reprocessar
1. `pip install -r requirements-dev.txt`; `python -m pytest` -> 1082 passed. Demo em Docker: README, secao 'Em Docker'. Proximo: licenca (Fase 8, decisao sua), resumo de clusters (9.12, opcional), 2.8.
2. Para ingerir um repo: definir `APP_MEMORY_INGEST_ROOTS` e chamar `POST /api/v1/memorias/ingerir` (ver README).
3. Proxima tarefa liberada: rotular >= 15 perguntas reais (4.8) para decidir 4.9 (embeddings so se superarem o baseline); 4.21 (CI visual); 4.22 (arestas pela UI). Historico anterior: Historico: Fase 4 inicial ligou memoria+codigo ao prompt do provedor Kiro,
   com `source_ref` e rotulo de dado nao confiavel; depois benchmark recall@k/MRR contra o baseline textual antes de embeddings.
