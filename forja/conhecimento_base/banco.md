---
titulo: Banco de dados
pai: Base de conhecimento da Forja
tags: banco de dados, sql, persistencia
tipo: estrutural
---
Dados sobrevivem ao código: modele com cuidado, mude com migração e proteja com backup.
Subtópicos: [[Modelagem de dados]], [[Índices e desempenho de consultas]], [[Transações e concorrência no banco]],
[[Migrações de esquema]], [[SQLite na prática]], [[Backup e recuperação]].
+++
---
titulo: Modelagem de dados
pai: Banco de dados
tags: modelagem, normalizacao, chaves
relacionados: Índices e desempenho de consultas; Migrações de esquema
---
- Normalize até a 3ª forma normal; desnormalize só com motivo medido (leitura quente).
- Chave primária estável e sem significado de negócio (UUID/ID); chaves naturais viram restrição UNIQUE.
- Restrições no banco (NOT NULL, UNIQUE, FK, CHECK) são a última linha de defesa da integridade.
- Tipos certos: dinheiro em inteiro (centavos) ou decimal, datas em UTC (ISO 8601), booleanos como booleanos.
- Exclusão lógica (estado/arquivado) quando houver auditoria; histórico em tabela de versões.
- JSON em coluna só para dado realmente flexível; o que é filtrado vira coluna indexada.
+++
---
titulo: Índices e desempenho de consultas
pai: Banco de dados
tags: indices, performance, explain, n+1
relacionados: Modelagem de dados; Desempenho em Python
---
- Indexe colunas de filtro, junção e ordenação frequentes; índice composto segue a ordem de seletividade/uso.
- Leia o plano (`EXPLAIN`/`EXPLAIN QUERY PLAN`) antes e depois de otimizar.
- Evite N+1: carregue em lote ou com junção.
- Paginação por chave (keyset) escala melhor que OFFSET grande.
- Índice tem custo de escrita e espaço: não indexe tudo.
- Busca textual: índice próprio (FTS) em vez de `LIKE '%x%'`.
+++
---
titulo: Transações e concorrência no banco
pai: Banco de dados
tags: transacao, acid, lock, isolamento
relacionados: Concorrência e paralelismo; Modelagem de dados
---
- Agrupe operações que precisam ser atômicas em uma transação curta; nada de rede ou espera humana dentro dela.
- Conheça o nível de isolamento do banco e os efeitos (leitura suja, não repetível, fantasma).
- Atualização condicional por versão (`WHERE id=? AND versao=?`) evita perder escrita concorrente.
- Idempotência por chave única (ex.: chave de idempotência) evita duplicar em retentativa.
- Ordem consistente ao travar várias linhas reduz deadlock.
+++
---
titulo: Migrações de esquema
pai: Banco de dados
tags: migracao, alembic, schema
relacionados: Deploy seguro e rollback; Backup e recuperação
---
- Toda mudança de esquema por migração versionada (Alembic, Flyway); nunca à mão.
- Migração pequena, testada em cópia do banco e com `downgrade` quando possível.
- Compatível para trás: adicione coluna anulável/padrão, migre os dados, só depois remova o antigo.
- Dados grandes: migre em lotes, fora da transação de esquema.
- Backup antes de migrar em produção; aplique migrações na subida de forma controlada.
+++
---
titulo: SQLite na prática
pai: Banco de dados
tags: sqlite, wal, fts5
relacionados: Transações e concorrência no banco; Índices e desempenho de consultas
---
- Modo WAL para leitores concorrentes com um escritor; `busy_timeout` para esperar a trava.
- Um único escritor por vez: serialize escritas no processo; leituras em conexões separadas.
- `PRAGMA foreign_keys=ON` em toda conexão (vem desligado).
- FTS5 para busca textual, com bm25 e prefixos; filtre ACL junto do MATCH.
- `integrity_check` e backup online (`VACUUM INTO` ou API de backup).
- Excelente para local-first e uso solo; para muitos escritores na rede, use servidor (PostgreSQL).
+++
---
titulo: Backup e recuperação
pai: Banco de dados
tags: backup, restore, recuperacao
relacionados: Migrações de esquema; Deploy seguro e rollback
---
- Backup que nunca foi restaurado não é backup: teste a restauração.
- Regra 3-2-1: três cópias, duas mídias, uma fora do local.
- Defina RPO (quanto dado pode perder) e RTO (quanto tempo pode ficar fora) e escolha a frequência por eles.
- Backups com segredos ou PII são tão sensíveis quanto o original: criptografe e restrinja acesso.
