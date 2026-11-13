# ADR-021: Desfazer por tarefa, pastas isoladas, retomada, telemetria, regras, cérebro organizado e oficina interativa

- Status: aceito
- Itens: 9.1 a 9.19 do plano (validação de mercado de nov/2026), 0.5 (gitleaks) e hospedagem em Docker.

## Contexto

A validação de mercado apontou lacunas em relação a orquestradores de agentes conhecidos: não havia como desfazer o que uma
tarefa alterou, duas tarefas na mesma pasta se atropelavam, uma queda do servidor exigia retomar à mão, não havia telemetria
padrão, os testes rodavam sem isolamento, o segundo cérebro acumulava duplicatas e notas velhas e a oficina pixel art só
mostrava o estado do quadro.

## Decisões

1. **Desfazer por tarefa** (`orquestracao/restauracao.py`, tabela `ponto_restauracao`). Antes de uma execução que escreve
   (alteração de código, verificação, documentação), a Forja fotografa as pastas de trabalho: hash de cada arquivo e cópia
   endereçada por conteúdo na área de dados (fora do Git e do projeto). Ao terminar, guarda a diferença. Desfazer:
   - restaura alterados/apagados e remove criados, **só** se o arquivo continua como a execução deixou (senão é conflito);
   - forçar é explícito e confirmado na tela; a execução mais recente da pasta é desfeita primeiro;
   - segredos (`.env`, chaves), links simbólicos, pastas ignoradas e arquivos acima de 5 MB nunca são copiados.
   Escolhido em vez de `git stash`/commits automáticos: funciona sem Git e não mexe no histórico do usuário.
2. **Pastas isoladas** (`orquestracao/isolamento.py`, tabela `area_isolada`). Cada execução reserva suas pastas de trabalho.
   Pasta ocupada + Git: `git worktree` em `<repo>/.worktrees/` num branch `forja/<tarefa>-<exec>` (no exclude local do Git;
   nada é mesclado sozinho; remover a cópia mantém o branch). Sem Git: a execução bloqueia com `pasta_ocupada` e é retomada
   sozinha quando a pasta libera. A área de dados da Forja foi descartada para os worktrees porque o perfil do Kiro a nega.
   `politicas.sandbox = "worktree"` força a cópia isolada.
3. **Retomada após queda**: preferência `retomar_apos_queda` (manual por padrão). Automático retoma pelo checkpoint no
   máximo **uma vez** por execução (contado nos eventos), para que uma tarefa que derruba o servidor não entre em laço.
4. **Telemetria OpenTelemetry** (`observabilidade/telemetria.py`, só biblioteca padrão). Ao fim de cada execução, os eventos
   viram um rastro OTLP/JSON com as convenções `gen_ai.*` (`invoke_agent`, `chat <modelo>`, `execute_tool`). Destinos: JSONL nos
   logs e/ou coletor OTLP/HTTP **só em loopback** (`APP_OTEL_ENDPOINT`, validado). Nunca leva prompt, resposta ou segredo.
   Desligada por padrão.
5. **Isolamento dos testes** (`ferramentas/sandbox.py`): Job Object no Windows (mata a árvore inteira, teto de memória e de
   processos), grupo de processos + teto de memória no Linux, TMP próprio. Modo estrito: HOME próprio e rede cortada por proxy.
   Documentado como proteção contra efeitos colaterais comuns, **não** contra código malicioso (não é contêiner).
6. **Retomada compacta**: a Forja monta (sem LLM) o resumo do que a rodada anterior fez (ferramentas concluídas, testes) e o
   envia na retomada. Se o contexto medido pelo Kiro passou de 120 mil tokens, a retomada abre sessão nova com esse resumo em
   vez de recarregar o histórico. Verificado no Kiro real (3.1.0): a sessão anuncia como comandos só `context-gatherer`,
   `forja` e `general-task-execution`; não há `/compact` via ACP, por isso a compactação é da Forja.
7. **Subagentes**: o turno de planejamento pode devolver `## Subtarefas` (2 a 4). A Forja cria uma tarefa por parte (nível
   `normal` forçado, sem recursão) e uma tarefa de consolidação que depende de todas e herda os critérios. Preferência
   `subagentes`: desligado | propor (padrão, ficam no Backlog) | executar (iniciam em paralelo, cada uma reservando a pasta;
   a consolidação inicia quando a última conclui).
8. **Roteamento que aprende** (`aprendizado_rotas.py`, tabela `estatistica_rota`): média móvel exponencial (α = 0,3) do
   sucesso por nível/parte/modelo. Nível com menos de 60% em 5+ execuções sobe um degrau. Nunca rebaixa sozinho; nível forçado
   na tarefa nunca muda. Cancelamentos e pausas para decisão não contam.
9. **Painel de custo** (`custos.py`, vista "Custo"): créditos **estimados** = turnos × multiplicador do modelo listado pela
   conta (1,00x se desconhecido); mock custa zero; alerta quando os últimos 7 dias passam do dobro da média semanal.
10. **Regras de controle do usuário** (`seguranca/regras.py`, preferência `regras_controle`): negar | perguntar | aprovar por
    categoria, trecho do comando e caminho. Vale a mais restritiva. Nenhuma regra libera segredo, pasta de consulta, ação fora
    da pasta de trabalho, risco alto ou categoria que sempre pergunta: "aprovar" nesses casos vira "perguntar". Cada decisão por
    regra vira evento `kiro.regra_aplicada`.
11. **Spotlighting**: anexos e contexto recuperado vão entre marcadores com código aleatório por prompt
    (`<<ANEXO x #k3f9q2>> ... <<FIM ANEXO x #k3f9q2>>`): o dado não consegue forjar o fim do bloco.
12. **Segundo cérebro organizado** (`organizacao.py`, tabela `sugestao_memoria`): varredura local a cada 30 min (ou "Organizar
    agora") sugere duplicatas (mesmo hash ou Jaccard ≥ 0,75 com título parecido), desatualizadas (origem mudou, validade
    vencida, contestada há 30+ dias, candidata esquecida há 90+ dias) e ligações (2+ tags em comum). Nada muda sem aceite; aceitar
    usa os caminhos auditáveis (substituído, obsoleto/revogado, ligação RELACIONADO_A). Fila "Revisão (N)" com as candidatas.
    Utilidade medida (`memoria.usos`) dá reforço de até +20% no ranking. Pacotes de conhecimento opcionais
    (`forja/conhecimento_pacotes/`, ex.: FastAPI) instalam como subnamespace somente leitura da base.
13. **Oficina interativa** (`GET /oficina`, `GET /execucoes/{id}/replay`): personagem por papel (planejador, executor, testador,
    revisor, estudante), animação pela ação (lendo, editando, comando, web, pensando, aguardando), contorno pelo nível da tarefa,
    barra de orçamento (ferramentas, chamadas ou tempo), balão "aguardando você" que abre as decisões, cartão de detalhes ao passar
    o mouse ou focar, setas/Home/End, replay com passos e velocidade, descrição em `aria-live`, som opcional desligado, movimento
    reduzido respeitado e chão com as cores da paleta.
14. **gitleaks** no pre-commit e no CI (binário fixo verificado por sha256, histórico inteiro). Fixtures sintéticas dos testes de
    redação liberadas só para a regra genérica e só em `tests/`.
15. **Docker**: imagem não-root, sistema de arquivos somente leitura, sem capabilities, volume próprio. No contêiner o servidor
    escuta em 0.0.0.0 (necessário para o encaminhamento), mas o compose publica **só** em `127.0.0.1` do host e o token é obrigatório.
    Sem Kiro CLI no contêiner: o agente é o simulado.

## Consequências

- Migração 0012 (5 tabelas/colunas e índice `evento(execucao_id, seq)`), aditiva.
- Toda peça nova é de melhor esforço: falhar nela nunca altera o resultado de uma execução (testado).
- Pendências honestas: worktrees exigem Git e partem do último commit; o isolamento de testes não substitui contêiner;
  créditos são estimativa; a organização não resume clusters em tópicos automaticamente (só sugere ligações).
