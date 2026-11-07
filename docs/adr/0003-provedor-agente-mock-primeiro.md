# ADR-003 — Interface ProvedorAgente com mock antes do Kiro ACP

- Status: aceito (Fase 1); Kiro ACP planejado (Fase 2)
- Contexto: o nucleo precisa ser testavel sem Kiro CLI/entitlement e sem rede.
- Decisao: definir `ProvedorAgente` (executar/checkpoint/cancelamento cooperativo) e implementar primeiro um
  `AgenteMock` deterministico e claramente SIMULADO. O adaptador Kiro ACP V3 entra depois atras da mesma interface,
  com negociacao de capabilities e mock JSON-RPC antes de integracao real.
- Consequencias: nucleo validado ponta a ponta sem Kiro; evidencias de mock marcadas `simulada=true`,
  nunca contadas como funcionalidade real.
- Alternativas: integrar ACP direto (acoplaria testes a credencial/rede e violaria a independencia de fornecedor).
