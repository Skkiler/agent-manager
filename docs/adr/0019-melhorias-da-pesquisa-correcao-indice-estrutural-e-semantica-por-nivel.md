# ADR-019: Melhorias da pesquisa de métodos

Cobre a rodada única de correção, o índice estrutural, a busca semântica por nível e os orçamentos rígidos.

- Status: aceito
- Substitui o relatório de pesquisa: ele foi implementado e removido. As decisões e as fontes ficam registradas aqui.

## Contexto (o que o mercado faz, nov/2026)

- **Busca em código:** o mercado prefere busca agêntica (grep e leitura sob demanda) a RAG vetorial [1][2]. Um **índice estrutural** de símbolos, imports e chamadas melhora a localização em mudanças com vários arquivos, sem aumentar o custo por tarefa resolvida [3].
- **Engenharia de contexto:** carregar só quando precisa (*just-in-time*), devolver resultados de ferramenta compactos e paginados, e prefixo fixo para o cache de prompt [4][5][6].
- **Arnês ("harness"):** orçamentos rígidos de passos, chamadas e tempo, mais condição explícita de parada [7]. A instrução original se perde no meio da janela em tarefas longas, então vale relembrá-la nos turnos seguintes [8].
- **Padrão avaliador-otimizador:** um avaliador objetivo devolve a falha para correção. Usar no máximo o necessário, porque agentes gastam cerca de 4× os tokens de um chat [9][10].

## Decisões

1. **Índice estrutural** (`codigo.estrutura`):
   - Operações: `mapa`, `definicao`, `referencias`, `dependencias`, `impacto` e `testes_afetados`.
   - Python é analisado por AST (definições com início e fim, imports resolvidos, chamadas). JS/TS usa regex leve; as demais linguagens, só definições.
   - Cache incremental por (tamanho, mtime). Reaproveita a varredura segura do indexador (sem links, segredos ou pastas proibidas).
   - Fallback: `repo.mapa`.
2. **Rodada única de correção:** em `alteracao_codigo`/`verificacao` com pasta de trabalho, a Forja roda os testes **reais** do projeto.
   - O comando vem do que o projeto declara (pytest, npm test, cargo, go); a Forja nunca inventa um.
   - Ordem: primeiro os testes afetados pelos arquivos alterados, depois a suíte completa. Se falhar, devolve a falha ao agente **uma vez** (com lembrete do objetivo) e roda de novo.
   - Execução sem shell, com tempo máximo e ambiente limpo: variáveis com nome de segredo e as `APP_*`/`FORJA_*` não chegam ao processo.
   - Pede aprovação, exceto no nível total. Resultado: evidência `testes_forja` (real), artefato com a saída, mensagem na conversa e pendências `testes_falhando`/`regressao`.
   - Preferência `correcao_automatica` (desligada | uma_rodada) e `testes_tempo_maximo`.
3. **Critérios verificáveis:** a Forja confere sozinha `arquivo: caminho` e `testes passam`. Os demais critérios ficam "manual". Resultado na evidência `criterios_forja` e nas pendências `criterios_nao_atendidos`/`criterios_sem_prova`. A tela de nova tarefa sugere critérios por modo.
4. **Busca semântica por nível** (`busca_semantica`: inativo | fallback | ativo; padrão **inativo**):
   - Dependência opcional (`fastembed`). Exige no mínimo 8 GB de RAM e faz um benchmark curto antes de indexar.
   - Indexação incremental por hash (migração 0011, `vetor_semantico`), em segundo plano.
   - ACL aplicada **antes** da pontuação.
   - **fallback** só entra quando a busca lexical não tem resultado ou a margem entre o 1º e o 2º é menor que 30% (o gatilho medido no ADR-017). **ativo** sempre funde, com peso 0,8.
   - Estado real na tela e em `GET /api/v1/busca/semantica`.
5. **Prompt:**
   - O prefixo fica idêntico entre usuários e tarefas; o perfil vem depois da tarefa.
   - Nova seção `## Evidências`, conferida pela checagem de alegações. Informação da web sempre com fonte.
   - Com 3 ou mais pastas, sugere delegar a exploração a um subagente.
6. **Contexto por referência:** com o MCP da Forja ligado, cada item vira local mais uma linha, e o agente lê sob demanda.
7. **MCP compacto:**
   - `forja_buscar_memoria` devolve referência, local, estado e trecho de no máximo 400 caracteres, com paginação (`pagina`, `ha_mais`).
   - `forja_executar_ferramenta` devolve `dados` só abaixo de 4 mil caracteres.
8. **Sinal real de MCP pronto:** a notificação `_kiro/mcp/status` com `connected`. O antigo (custo de ferramentas subir) falhava após a troca para o modo `forja`. Medido no Kiro real: 1,96 s, contra o teto de 15 s de antes.
9. **Modelo de reserva:** lista explícita e ordenada por parte (até 3), vazia por padrão. Sem reserva, continua a falha fechada.
10. **`env.verificar` + compose:** aponta as variáveis obrigatórias que o `docker-compose` interpola e faltam (ou estão vazias) no `.env`, sem mostrar valores.
11. **Orçamentos rígidos do turno:**
    - Limite de chamadas de ferramenta por execução (preferência, padrão 200).
    - **Laço:** a mesma chamada repetida 6 vezes seguidas.
    - Ao estourar: cancela o turno, guarda a resposta parcial e bloqueia com o motivo.
12. **Consumo medido pelo Kiro:** o `breakdown` de contexto vira o evento `kiro.contexto` e entra no resumo da evidência.

## Verificação real

| Item | Resultado no Kiro real |
|---|---|
| Sinal de MCP pronto (modo `forja`) | `mcp_status` em 1,96 s, 5 ferramentas |
| Correção de código (projeto sintético) | agente corrigiu `calc.py`; testes da Forja: afetados e depois suíte completa, PASSOU; critérios `testes passam` e `arquivo: calc.py` conferidos |
| Busca semântica real (fastembed) | 31 vetores em 3,2 s (~5 ms por bloco); consulta em dezenas de ms |
| Benchmark lexical | inalterado (GLOBAL 0.94/0.87/0.89) |

## Fontes

1. Relatos de Boris Cherny sobre RAG vs. busca agêntica no Claude Code: [officechai.com](https://officechai.com/ai/claude-researcher-explains-how-agentic-search-performed-better-than-rag-for-code-generation/).
2. [Is Grep All You Need? (arXiv 2605.15184)](https://arxiv.org/abs/2605.15184).
3. [Code Isn't Memory: A Structural Codebase Index Inside a Coding Agent (arXiv 2606.22417)](https://arxiv.org/pdf/2606.22417).
4. [Anthropic: Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents).
5. [Anthropic: Writing effective tools for agents](https://www.anthropic.com/research/writing-tools-for-agents).
6. [Anthropic: Prompt caching](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching).
7. [TrueFoundry: 10 rules for production agents](https://www.truefoundry.com/blog/agent-harness-best-practices).
8. [MarkTechPost: context engineering inside the harness](https://www.marktechpost.com/2026/09/12/context-engineering-inside-the-harness-4-mechanisms-that-beat-context-overflow-and-goal-loss-on-long-horizon-tasks/).
9. [Anthropic: Building effective agents](https://www.anthropic.com/engineering/building-effective-agents).
10. [Anthropic: multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system).

O conteúdo das fontes foi reescrito com palavras próprias para respeitar o licenciamento.
