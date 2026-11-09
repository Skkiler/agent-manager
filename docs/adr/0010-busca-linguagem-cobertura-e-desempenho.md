# ADR-010 — Busca: linguagem, cobertura e desempenho; sem criptografia em repouso

- Status: aceito (Fase 4)
- Decisoes de busca:
  1. Termos viram grupos (termo, radical PT/EN com prefixo, sinonimos) com stopwords (`forja/memoria/linguagem.py`).
     Sinonimos extras vem de `knowledge/ontologias/sinonimos.json`.
  2. AND primeiro; se nada, **OR ponderado por cobertura** (idf dos grupos). Termo ausente do indice conta com peso maximo,
     entao reduz a cobertura em vez de sumir do calculo. Cobertura de simbolo = grupos casados / total de grupos.
  3. Ranker de grafo (no por nome -> vizinhos 1 salto -> memorias via `refs`), fator 0,8.
  4. Benchmark versionado (`knowledge/modelos_publicos/benchmark_busca.json`): recall@3 0,79 -> 0,94; MRR 0,70 -> 0,87.
- Desempenho: tabela `codigo_trecho` (id = rowid do FTS), `simbolo.nome_norm/nome_final` indexados e insercao em lote
  (migracao 0005 com backfill). Corpus local de 2.867 arquivos: mediana 135 ms -> 3,7 ms; ingestao 137,7 s -> 23,7 s.
- Alembic: tabelas virtuais FTS5 e sombras sao filtradas em `incluir_objeto` (o autogenerate propunha DROP delas).
- **Criptografia em repouso: nao adotada.** A ferramenta e local, de usuario unico. Protecao = ACL de namespace,
  `.gitignore`/`.kiroignore`, conta do SO e BitLocker. Cifrar campos ou usar SQLCipher quebraria o FTS5. Reavaliar se o banco
  for para disco compartilhado.
- Limites: busca lexical, sem embeddings (so apos provarem ganho no benchmark); stemmer PT aproximado.
