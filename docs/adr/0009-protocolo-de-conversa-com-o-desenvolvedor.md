# ADR-009 — Protocolo de conversa agente-desenvolvedor

- Status: aceito (Fase 4)
- Contexto: perguntas pontuais isoladas de CLI/IDE sao pobres. O desenvolvedor precisa de explicacao e de decidir em bloco.
- Decisoes:
  1. O agente responde em secoes: Entendimento, Resposta, Premissas, Decisoes para voce, Proximos passos.
  2. Decisoes vem agrupadas, cada uma com `Recomendo:` e `Alternativas:`.
  3. Havendo decisao, o resultado e `bloqueada` com pendencia `aguardando_decisoes_do_usuario`. O desenvolvedor responde **uma vez**
     (`POST /tarefas/{id}/conversa`) e a execucao retoma.
  4. Retomada usa prompt compacto: protocolo curto + entendimento + decisoes + respostas + so contexto util. Nao reenvia a
     resposta anterior nem o protocolo completo.
  5. `chamadas_modelo` acumula entre retomadas (orcamento nao zera).
  6. Mensagens passam por `redigir_segredos` e tem teto de 20000 caracteres.
- Rejeitado por ora: ACP `session/load` (reuso de sessao; futuro).
- Medido com Kiro real (tarefa sintetica): retomada ~67% mais barata que reenviar prompt + resposta anterior (estimado).
