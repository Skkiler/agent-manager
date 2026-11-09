# ADR-007 — Memória própria: SQLite/FTS5, namespaces com ACL e proveniência

- Status: aceito (Fase 3)
- Contexto: o "segundo cérebro" guarda conhecimento reutilizável, mas o repositório é **público**. Só a lógica, as
  ferramentas, o controle e a orquestração são open source; credenciais, dados internos e o conteúdo da memória não
  podem subir ao Git (ver `docs/STATUS_IMPLEMENTACAO.md`, "Regra de publicação").
- Decisões:
  1. **Armazenamento**: SQLite (WAL) + FTS5 (`memoria_fts`, `codigo_fts`), sem Neo4j/Qdrant/vetores (§10.5). Embeddings só
     após provarem ganho sobre o baseline textual (Fase 4). O banco vive em `data/` (ignorado pelo Git).
  2. **Três grafos separados** (§9.1): execução (`tarefa`/`execucao`), conhecimento (`no_conhecimento`/`aresta_conhecimento`,
     ontologia §9.3 validada) e código (`arquivo_indexado`/`simbolo` + `codigo_fts`). Nunca em uma tabela só.
  3. **Namespaces** `publico | pessoal | terceiros | empresa/<id>[/sub…]` com ACL por **prefixo**. Pedido fora da ACL é
     **erro (403)**, nunca filtro silencioso. Memória inacessível responde **404** (sem oráculo de existência). Aresta só liga
     nós visíveis no seu escopo (nó no próprio namespace ou em ancestral). A instância libera `publico,pessoal` por padrão;
     `empresa/*` e `terceiros` exigem inclusão explícita em `APP_MEMORY_ALLOWED_NAMESPACES`.
  4. **ACL antes do ranking**: o filtro de namespace é parte do `WHERE` do FTS5 (comparação por `substr`, não `LIKE`, pois `_`
     é válido em namespace e viraria curinga). Limite honesto: o IDF do bm25 conta o corpus inteiro; nenhum conteúdo vaza, mas
     há influência numérica mínima no ranking. Mitigação futura: um índice por sensibilidade.
  5. **Estados epistemológicos** (§9.4). `verificado` exige evidência **real** (evidência simulada/mock é recusada).
     `validado` só por `/validar`, a partir de `verificado`, sem sinais de prompt injection e sem contradição aberta.
     Editar o conteúdo de uma memória validada a devolve a `candidato` (o histórico permanece em `memoria_versao`).
  6. **Contradição** (`afirma = {sujeito, valor}`): a busca **devolve** os dois lados e bloqueia a validação; só uma
     resolução **explícita** (`resolver-conflito`) marca a perdedora como `substituido`. Nada é escolhido em silêncio.
  7. **Obsolescência por origem** (§9.5): memória com `fonte.{repositorio,caminho,hash}` é marcada `necessita_revalidacao`
     quando a ingestão detecta mudança/remoção do arquivo (por SHA-256, não por timestamp). Não se apaga; `revalidar` exige
     evidência real **posterior** à mudança.
  8. **Saneamento na entrada** (nunca na saída): PII (e-mail, CPF, CNPJ, telefone, cartão com Luhn) e segredos são redigidos
     **antes** de gravar e de indexar. Detecção de prompt injection marca o conteúdo; todo resultado vem com
     `conteudo_nao_confiavel=true` — dado, nunca instrução.
  9. **Ingestão**: somente dentro de `APP_MEMORY_INGEST_ROOTS` (vazio = desligada via API). Ignora symlinks, segredos
     (`.env`, chaves…), binários, >1 MB, diretórios de cache/dados; arquivo inválido cai no fallback textual.
  10. **Eventos**: carregam só IDs/estado/sensibilidade — o SSE não filtra por namespace, então nunca levam título/conteúdo.
  11. **Recuperação**: FTS5 (BM25) + ranker de **símbolos** (nome exato > componente final > prefixo, apontando para a linha da
      definição), fundidos por **RRF**; peso por estado epistemológico (validado > verificado > observado > candidato).
      `confianca` é exibida, mas **não** é usada no ranking (não é calibrada). `apenas_validadas` exclui código bruto.
- Consequências: busca exata em poucos ms (96 arquivos do próprio repo em 0,7 s; reindexação sem mudanças em 0,2 s).
- Não coberto nesta fase: embeddings/`sqlite-vec`, expansão por grafo na busca, Tree-sitter, OCR, watcher de arquivos,
  criptografia em repouso do banco (a proteção atual é ACL + `.gitignore`/`.kiroignore` + permissões do SO).
