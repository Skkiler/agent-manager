# Boas praticas: RPA, banco de dados, UI/UX e busca

## RPA (automacao de robos)
- Idempotencia: reprocessar o mesmo item nao pode duplicar efeito. Registre estado por item.
- Tentativas com backoff e limite; falha definitiva vai para fila de excecao com motivo.
- Seletores resilientes, esperas explicitas (nunca `sleep` cego), captura de evidencia em falha.
- Credenciais fora do codigo; logs sem dados pessoais; separar configuracao, regra de negocio e interacao com a interface.

## Banco de dados (DBA)
- Migracoes versionadas (Alembic); nunca alterar esquema a mao em ambiente compartilhado.
- Indices para colunas de filtro e juncao frequentes; confirme com plano de execucao (EXPLAIN) antes de criar.
- Transacoes curtas; chaves estrangeiras e restricoes no banco, nao so na aplicacao.
- Backup testado por restauracao; SQLite em modo WAL para leitura concorrente local.

## UI/UX e acessibilidade
- Hierarquia visual clara, foco visivel, contraste adequado, navegacao por teclado.
- Rotulos em todos os campos, mensagens de erro que dizem como corrigir, estados de carregamento e vazio.
- Nao depender so de cor para transmitir estado. Acessibilidade completa exige teste manual com tecnologias assistivas.

## Busca e recuperacao
- Ferramenta deterministica antes de LLM. Busca lexical (FTS5/BM25) com radicais e sinonimos cobre muito antes de embeddings.
- Meca antes de otimizar: recall@k, MRR, nDCG num conjunto de consultas com respostas conhecidas.
- Entregue ao agente so o que passa por limiar de relevancia e cobertura; contexto inutil custa tokens e piora a resposta.
