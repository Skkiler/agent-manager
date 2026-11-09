# Estado da implementacao

**Atualizado:** 2026-11-08. **Fases 0, 1, 2 e 3 implementadas e testadas.** Padrao de agente continua sendo o **mock SIMULADO**;
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
- `python -m pytest` -> **265 passed** (~44 s; 3 execucoes seguidas limpas), exit 0, sem warnings; cobertura **91%**. `ResourceWarning` continua tratado como erro.
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
| 0 — Diagnostico/Git-safe | testado | baseline; `.gitignore`/`.kiroignore` + `test_git_safe` | scanner dedicado (gitleaks) pendente de aprovacao |
| 1 — Nucleo deterministico | testado | testes + smoke | — |
| 2 — ACP/Kiro | testado (2.8 e 2.9 abertos) | ACP + aprovacao por acao, validado com Kiro real | 2.8 agentes/skills/Workflow; 2.9 pool/`session/load` |
| 3 — Memoria/grafo | **testado** (3.10–3.12 abertos) | 106 testes de memoria (43 dominio + 44 servico + 19 API) + 59 git-safe + mutacao + dados reais | 3.10 propostas de procedimento |
| 4 — Contexto/ferramentas | planejado | — | **proxima**: context builder com orcamento, ligar recuperacao ao prompt do Kiro, ferramentas N0, benchmark recall@k/MRR |
| 5 — Multiagentes | planejado | — | DAG, scheduler, worktrees; modos de escrita |
| 6 — Aprendizado | planejado | — | EWMA, roteamento, N1 opcional |
| 7 — UI/LAN | planejado | — | painel pixel art; tunel/HTTPS |
| 8 — Open source | planejado | — | licenca, CI, SBOM, release |

## Componentes novos (Fase 3)
- `forja/memoria/` — `modelo` (namespaces/ACL, estados, ontologia), `saneamento` (PII, segredos, injection, consulta FTS5 segura),
  `indexador` (varredura segura, simbolos AST, trechos), `contratos`.
- `forja/adapters/sqlite/memoria_fts.py` — SQL do FTS5 com ACL na consulta; ranker de simbolos. Migracao `0003`.
- `forja/orquestracao/memoria_servico.py` — ciclo de vida, promocao com evidencia real, contradicao, obsolescencia por origem,
  ingestao incremental, busca hibrida (FTS5 + simbolos, RRF), grafo tipado com escopo.
- `forja/servidor/rotas_memoria.py` — `/api/v1/memorias*`, `/conhecimento*`; painel com "Memoria e codigo". ADR-007.

## Limitacoes e pendencias (honestas)
- **Sem embeddings/vetores, sem expansao por grafo na busca, sem Tree-sitter (so AST Python), sem OCR/PDF, sem watcher de arquivos**
  (Fase 4). Busca e lexical: sinonimos e perguntas em linguagem natural longa funcionam mal.
- **Sem criptografia em repouso:** o banco com a memoria e protegido por ACL, `.gitignore`/`.kiroignore` e permissoes do SO — nao
  por cifra. Considerar antes de guardar memoria `empresa/*` em disco compartilhado.
- IDF do bm25 considera o corpus inteiro (sem vazar conteudo, mas com influencia numerica minima entre namespaces).
- Heuristicas de PII/injection (regex) reduzem risco, **nao** o eliminam; resultados sao sempre tratados como dados nao confiaveis.
- `confianca` e informada pelo usuario e **nao calibrada**; nao entra no ranking.
- A memoria ainda **nao e injetada automaticamente** no prompt do Kiro (Fase 4). Hoje o consumo e via API/painel.
- Painel (JS) sem teste de navegador: verificado por revisao, `node --check` e testes de API/SSE.
- Scanner dedicado de segredos (gitleaks) e CI continuam ausentes. Um processo `kiro-cli` por execucao (sem pool).

## Retomada sem reprocessar
1. `pip install -r requirements-dev.txt`; `python -m pytest` -> 265 passed.
2. Para ingerir um repo: definir `APP_MEMORY_INGEST_ROOTS` e chamar `POST /api/v1/memorias/ingerir` (ver README).
3. Proxima tarefa liberada: **Fase 4** — context builder com orcamento (§10.3) ligando memoria+codigo ao prompt do provedor Kiro,
   com `source_ref` e rotulo de dado nao confiavel; depois benchmark recall@k/MRR contra o baseline textual antes de embeddings.
