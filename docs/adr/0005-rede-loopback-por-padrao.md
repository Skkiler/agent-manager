# ADR-005 — Servidor loopback por padrao, LAN sob aprovacao

- Status: aceito (Fase 1)
- Contexto: acesso do notebook ao desktop deve ser seguro (secoes 4.3 e 15.4).
- Decisao: bind padrao `127.0.0.1`. Bind fora de loopback so com `APP_ALLOW_LAN_BIND=true` e `APP_REQUIRE_AUTH=true`
  (validado em `Configuracoes`). Acesso remoto recomendado por tunel SSH; HTTPS/reverse proxy autenticado como alternativa.
  Token Bearer obrigatorio; validacao de Host/Origin; rate limit.
- Consequencias: nao ha endpoint aberto por acidente; LAN exige decisao explicita do operador.
- Alternativas: `0.0.0.0` por conveniencia (rejeitado: expoe o servico sem controle).
