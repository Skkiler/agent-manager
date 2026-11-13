# ADR-023: Master e sub-masters, Kiro + Codex, gestão de contexto, controle de escopo, status barato e perfis por papel

- Status: aceito

## Contexto

O usuário pediu, a partir da análise de mercado da etapa anterior: (1) conversar com um coordenador que cria e acompanha tarefas;
(2) usar o Codex junto com o Kiro; (3) manter o contexto dos agentes pequeno; (4) relatos de status legíveis e baratos;
(5) resolver o Kiro "esticar" a tarefa (fazer documentação e mudanças não pedidas); (6) seguir o item 2.8 (perfis de agente).
Fatos medidos que restringem o desenho: o ACP do kiro-cli 3.1.0 não expõe `/compact` nem workflows; perfis de `~/.kiro/agents`
aparecem como modos de sessão; o system prompt do kiro-cli manda agir sem hesitar e vence o prompt do agente em conflito
(kirodotdev/Kiro#7792); multiagente custa várias vezes mais tokens que um agente só.

## Decisões

1. **Master e sub-masters** (`orquestracao/coordenacao.py`, tabelas `coordenacao` e `mensagem_coordenacao`, migração 0014).
   Cada fala do usuário é um turno do coordenador, executado como tarefa interna (projeto `forja-coordenacao`, parte `coordenacao`,
   perfil `forja-coordenador` sem ferramentas). O estado que ele vê é montado sem LLM. A resposta tem `## Resposta` e `## Ações`
   (JSON). **Quem decide é o orquestrador:** cada ação é validada por Pydantic e por limites (6 ações por turno, 12 tarefas abertas,
   8 sub-masters, 40/15 turnos, profundidade 2) e pelo nível de autonomia (modos permitidos). Sub-master só quando o lote tem 2+
   projetos; em um projeto, vira uma tarefa complexa. Lote terminado = um turno de consolidação; sub-master reporta ao master.
   Turnos internos não aparecem no Kanban. Rejeitado: agentes conversando livremente entre si (custo e falta de controle).
2. **Kiro + Codex** (`adapters/codex_acp`, `agentes/roteador.py`). O Codex entra pelo adaptador oficial `@agentclientprotocol/codex-acp`
   reaproveitando todo o provedor ACP (mediador, orçamentos, verificação, escopo). Contextos separados: o checkpoint carimba o agente
   e a retomada volta para ele. Distribuição `so_kiro` (padrão), `auto`, `equilibrar`, `codex_primeiro`; reserva só quando o agente
   falhou sem produzir trabalho, com 15 min de resfriamento. **Falha fechada:** o Codex não tem regras deny de segredo, então recebe
   ambiente limpo, só roda em pastas sem arquivos com cara de segredo (varredura limitada a 20 mil arquivos; incompleta = bloqueia),
   usa somente leitura fora da execução e nunca acesso total; modo desconhecido bloqueia. MCP da Forja só no Kiro por enquanto.
3. **Gestão de contexto** (`orquestracao/caderno.py`, tabela `caderno_item`). Caderno da tarefa por MCP (`forja_caderno_salvar`,
   `forja_caderno_consultar`, ligados à tarefa por `FORJA_TAREFA_ID`) e ficha de estado determinística. Antes do turno de execução do
   plano, do turno de adendos e da rodada de correção, se o contexto medido pelo Kiro passou de `contexto_limite_sessao` (120 mil),
   a sessão é trocada por uma nova com a ficha. Rejeitado: resumir com LLM (a ficha basta e não alucina) e editar a janela do Kiro
   (o ACP não permite).
4. **Status barato** (`orquestracao/status.py`). Camada determinística em tempo real (mesma projeção da oficina) e, em marcos,
   resumo pela parte `status` (haiku, esforço baixo) em lote: até 6 tarefas por chamada, 45 s de espera, 20 chamadas por hora,
   turno sem ferramentas em workspace isolado com toda permissão negada. Falhou: frase determinística rotulada. Não duplica a
   conversa quando o agente já falou nela.
5. **Controle de escopo** (`orquestracao/escopo.py`). Contrato de escopo curto e forte no perfil e no pedido; durante a execução,
   passar do limite de arquivos do nível (3/10/25) faz cada nova escrita perguntar; depois, os arquivos medidos pelo ponto de
   restauração são comparados com o plano e com o pedido (documentação não pedida). Preferência `controle_escopo`: `pausar`
   (padrão, a tarefa fica bloqueada com a lista e o botão de desfazer), `avisar` ou `desligado`.
6. **Perfis por papel (2.8).** Além de `forja`, a Forja grava `forja-planejador`, `forja-executor`, `forja-revisor`, `forja-estudo`
   e `forja-coordenador`, todos com as mesmas regras deny; ferramentas por papel (revisor e estudo sem escrita; coordenador só leitura).
   A sessão troca de modo a cada parte; sem o perfil do papel usa `forja`; sem nenhum, bloqueia. Rejeitado: usar os agentes do
   workspace (arquiteto, implementador…), que não têm as regras deny de segredo.

## Consequências

- O master custa um turno por fala e um por lote; os limites deixam o custo previsível e visível na tela.
- O Codex só ajuda em pastas sem segredo; projetos com `.env` continuam só no Kiro (por desenho).
- Pausar por escopo pode gerar falso positivo em tarefas grandes legítimas: o usuário aceita respondendo, ou muda a preferência.
- Testado com agentes ACP falsos por subprocesso; o Codex real depende de instalação e login do usuário.
