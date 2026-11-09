# ADR-008 — Construtor de contexto economico

- Status: aceito (Fase 4)
- Contexto: injetar memoria no prompt custa tokens e envia dados ao provedor. Contexto inutil piora a resposta.
- Decisoes:
  1. `ConstrutorContexto` busca com termos de **titulo + descricao[:240]** (criterios de aceite so como fallback com <2 termos,
     pois descrevem o formato da resposta, nao o assunto).
  2. Portoes: piso de relevancia `1/(RRF_K+4)`, minimo relativo 0,45 ao melhor item, cobertura minima 0,5 (0,75 para hipoteses),
     no maximo 2 hipoteses, itens com sinal de injection excluidos, redundancia (Jaccard >= 0,6) descartada, teto de 350 tokens
     por item e orcamento total de 2000 tokens.
  3. `politicas.contexto = "nenhum"` pula a busca.
  4. So namespaces em `APP_CONTEXT_NAMESPACES` (padrao `publico`, subconjunto de `APP_MEMORY_ALLOWED_NAMESPACES`) vao ao prompt,
     porque o conteudo sai para o provedor.
  5. Persistencia do que entrou/omitido (`contexto_uso`) e marcacao de itens **realmente usados** (citacao `[M1]`). Na retomada
     entram so itens uteis.
  6. Tokens sao **estimados** (~4 car./token), sempre rotulados `fonte="estimado"`.
- Alternativas rejeitadas: descartar os termos mais comuns (regrediu a qualidade); enviar sempre top-k fixo (gasta token sem filtro).
- Limites: heuristica lexical; precisao em linguagem natural sobre corpus real nao medida.
