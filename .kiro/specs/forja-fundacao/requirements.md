# Requisitos — Forja Fundacao (Fases 0 e 1)

Fonte normativa: `ORIENTACAO_MESTRA_ECOSSISTEMA_KIRO.md` (secoes 6, 15, 17, 18, 19).
Escopo desta spec: higiene do repositorio (Fase 0) e nucleo local deterministico (Fase 1).
Fora de escopo: adaptador Kiro ACP, memoria/grafos, multiagentes, UI pixel art (Fases 2+).

## Requisitos (EARS) e criterios de aceite

### REQ-001 — Configuracao Git-safe
- Quando o repositorio for versionado, o sistema deve manter `.gitignore`, `.kiroignore` e `.env.example`
  sem valores reais de segredo.
- Aceite: `git ls-files` nao contem `.env`, chaves, `*.sqlite3`, `data/`, `logs/`, tokens. (Testado — ver STATUS.)

### REQ-002 — Bind loopback por padrao
- O servidor deve escutar em `127.0.0.1` por padrao; bind fora de loopback exige `APP_ALLOW_LAN_BIND=true`
  e `APP_REQUIRE_AUTH=true`.
- Aceite: `Configuracoes` rejeita host nao-loopback sem aprovacao explicita (teste de config).

### REQ-003 — Autenticacao obrigatoria
- Enquanto `APP_REQUIRE_AUTH=true`, toda rota de dados deve exigir token Bearer valido.
- Aceite: requisicao sem token recebe 401; com token valido, 2xx. (Testado: `test_exige_autenticacao`, smoke.)

### REQ-004 — Modelo de dominio e persistencia
- O sistema deve persistir projeto, objetivo, tarefa, execucao, evento, artefato, evidencia, aprovacao,
  lock e idempotencia, com migracoes versionadas (Alembic) e SQLite WAL.
- Aceite: migracao cria o schema; downgrade remove; backup/restore preserva dados. (Testado: `test_banco`.)

### REQ-005 — Maquina de estados da tarefa
- Transicoes devem seguir a secao 6.2; transicoes impossiveis sao rejeitadas; estados terminais nao saem.
- Transicoes reservadas ao orquestrador nao sao aceitas via comando manual.
- Aceite: `test_estados`, `test_transicao_reservada_rejeitada`, `test_conflito_versao`.

### REQ-006 — Concorrencia otimista e idempotencia
- Comandos de criacao aceitam `Idempotency-Key`; transicoes usam `expected_version`.
- Aceite: chave repetida retorna a mesma resposta; corpo divergente conflita; versao obsoleta e rejeitada.
  (Testado: `test_idempotencia_*`, `test_conflito_versao`.)

### REQ-007 — Execucao por agente mock e verificacao real
- O nucleo executa tarefas via `ProvedorAgente`; na Fase 1 apenas o mock (SIMULADO).
- Conclusao exige ao menos uma evidencia e integridade (hash) dos artefatos gravados.
- Evidencia de mock e sempre marcada `simulada=true` e nao conta como funcionalidade real.
- Aceite: `test_fluxo_ponta_a_ponta_sucesso`, `test_cenario_falha`, `test_cenario_bloqueio_e_retomada`.

### REQ-008 — Orcamento e politicas
- O sistema deve respeitar `max_tentativas`, `max_duracao_segundos`, `max_chamadas_modelo` e politica de aprovacao.
- Aceite: `test_orcamento_max_tentativas`, `test_expiracao_por_deadline`, `test_aprovacao_*`.

### REQ-009 — Locks de recurso
- Execucoes concorrentes com padroes de escrita sobrepostos devem ser bloqueadas; locks expiram por lease.
- Aceite: `test_lock_de_recurso_bloqueia_sobreposicao`, `test_duas_execucoes_concorrentes_rejeitadas`.

### REQ-010 — Eventos e SSE com replay
- O sistema deve emitir eventos sequenciais sanitizados e transmitir por SSE com `Last-Event-ID`/replay.
- Eventos duplicados sao deduplicados por `dedup_key`.
- Aceite: `test_sse_replay_e_last_event_id`, `test_stream_exige_token`.

### REQ-011 — Recuperacao pos-crash e shutdown gracioso
- Apos reinicio, execucoes `executando` sem worker viram `pausada`/tarefa `bloqueada` (retomaveis).
- Aceite: `test_recuperacao_pos_crash`.

### REQ-012 — Logs sanitizados e CSRF/host
- Logs em JSON com `correlation_id`; segredos redigidos; validacao de Host e protecao CSRF por Origin.
- Aceite: `test_host_invalido_rejeitado`, `test_origin_cross_site_rejeitada`.

### REQ-013 — Perfis de recurso adaptativos, sem LLM local
- O sistema detecta hardware e decide perfil; `APP_ENABLE_LOCAL_LLM=false` e invariante na Fase 1.
- Aceite: `GET /recursos` retorna metricas + perfil com `local_llm_enabled=false`.

## Rastreabilidade
Cada REQ aponta para teste automatizado real. O estado verificado fica em `docs/STATUS_IMPLEMENTACAO.md`.

## Fase 2 — Adaptador Kiro ACP (ver ADR-004)

### REQ-014 — Cliente ACP V3 seguro
- O cliente deve negociar `initialize` (protocolVersion 1), anunciar capacidades minimas (sem fs/terminal), responder a
  TODO pedido do agente e negar permissoes de ferramenta por padrao; nunca usar `--trust-all-tools`.
- Aceite: `test_handshake_e_sessao`, `test_protocolo_incompativel_rejeitado`,
  `test_permissao_negada_e_metodo_nao_anunciado_responde_erro`, `test_comando_nunca_confia_em_tudo`.

### REQ-015 — Falhas tipadas e degradacao
- CLI ausente, falta de login, timeout, desconexao, ruido em stdout e protocolo incompativel devem produzir erros tipados
  e estados recuperaveis (`bloqueada` + pendencia) ou `falhou`, sem travar o orquestrador.
- Aceite: `test_cli_ausente`, `test_autenticacao_necessaria_tipada`, `test_timeout_no_handshake`,
  `test_ruido_em_stdout_nao_derruba_cliente`, `test_desconexao_falha_pendentes`,
  `test_orquestrador_auth_deixa_tarefa_bloqueada_e_retomavel`.

### REQ-016 — Provedor Kiro somente leitura e honesto
- O provedor aceita apenas modos analise/documentacao, redige segredos na resposta, suporta cancelamento cooperativo e
  timeout, e nunca estima consumo de tokens.
- Aceite: `test_provedor_*`, `test_orquestrador_com_provedor_acp`; handshake real: `test_handshake_real_com_kiro_cli`.

## Fase 2b — Aprovação por ação (ver ADR-006)

### REQ-017 — Pergunta por ação, em linguagem natural
- O sistema deve traduzir chamadas de ferramenta em ações ("Posso excluir forçadamente `build`?"), com categoria e risco,
  correlacionando o pedido de permissão ao `tool_call` anterior (formato real do Kiro CLI).
- Aceite: `tests/test_acoes.py` (25 testes, incl. o exemplo `rm -rf` e a regressão de alvo duplicado/absoluto).

### REQ-018 — Um pedido por grupo, com adendo e decisão parcial
- Pedidos simultâneos devem virar UM pedido; o operador aprova todos, alguns ou nenhum, com adendo e "lembrar na execução";
  decisão em lote para vários pedidos.
- Aceite: `test_grupo_uma_pergunta_*`, `test_aprovacao_parcial_*`, `test_negar_grupo_*`, `test_lembrar_*`,
  `test_decisao_em_lote_*`, `test_decisao_dupla_conflita`, `test_concorrencia_de_decisoes_so_uma_vence`.

### REQ-019 — Segurança da aprovação
- Ações com segredos são negadas sem perguntar; timeout/cancelamento/expiração/reinício negam (nunca aprovam por omissão);
  nada permanece pendente sem worker; nunca usar `allow_always` do Kiro.
- Aceite: `test_timeout_nega_*`, `test_cancelar_enquanto_aguarda_aprovacao`, `test_recuperacao_de_pedido_orfao_*`,
  `test_segredos_sao_sensiveis_e_criticos`, `test_comando_que_toca_segredo_e_sensivel`; migração 0002 sem divergência de modelo.

## Fase 3 — Memória textual e grafos (ver ADR-007)

### REQ-020 — Namespaces e ACL antes da busca
- Todo acesso (busca, leitura, escrita, ingestão, grafo) passa pela ACL por prefixo de namespace; pedido fora da ACL é 403,
  memória inacessível é 404; o filtro está dentro da consulta FTS5 e não vaza entre irmãos com nomes parecidos (`_`).
- Aceite: `test_filtro_entre_namespaces_na_busca`, `test_pedido_de_namespace_sem_acesso_e_negado`,
  `test_memoria_inacessivel_parece_inexistente`, `test_subnamespace_herda_*`, `test_underscore_no_namespace_*`,
  `test_simbolo_so_aparece_para_quem_tem_acesso_ao_namespace`, `test_memoria_de_outro_namespace_e_404_nao_403`.

### REQ-021 — Qualidade epistemológica
- `verificado` exige evidência real; `validado` só por `/validar` sem injection e sem contradição; contradição é devolvida e
  nunca resolvida em silêncio; edição derruba validação; obsoletas saem da busca padrão.
- Aceite: `test_promocao_exige_evidencia_real`, `test_dois_fatos_contraditorios_*`, `test_editar_conteudo_derruba_*`,
  `test_memoria_obsoleta_*`, `test_hipotese_e_rotulada_*`, `test_duas_transicoes_concorrentes_so_uma_vence`.

### REQ-022 — Ingestão incremental, hashes e obsolescência por origem
- Ingestão por SHA-256, só em raízes autorizadas; arquivo alterado/removido marca memórias da origem para revalidação.
- Aceite: `test_ingestao_incremental_por_hash`, `test_mudanca_na_origem_*`, `test_arquivo_removido_*`,
  `test_ingestao_exige_raiz_autorizada`, `test_varredura_ignora_*`, `test_arquivo_com_erro_de_sintaxe_*`.

### REQ-023 — Privacidade: PII, segredos e prompt injection
- PII/segredos redigidos antes de gravar/indexar; injection sinalizada e bloqueia validação; resultados são dados não
  confiáveis; eventos não vazam conteúdo; nada privado é rastreável pelo Git.
- Aceite: `test_pii_e_segredos_redigidos_*`, `test_prompt_injection_*`, `test_segredo_dentro_de_arquivo_ingerido_*`,
  `test_eventos_de_memoria_nao_vazam_*`, `tests/test_git_safe.py` (59 casos).

### REQ-024 — Retenção e remoção
- `retencao_dias` define expiração; `purgar_expiradas` e `remover` apagam memória, índice, versões e vínculos.
- Aceite: `test_retencao_expirada_e_purgada`, `test_remocao_apaga_tudo_*`.

### REQ-025 — Gate da fase
- Uma nova tarefa localiza um procedimento sintético validado, com fonte e pré-condições, num repositório grande, dentro do
  orçamento de recuperação, sem devolver o repositório.
- Aceite: `test_gate_nova_tarefa_encontra_procedimento_validado_sem_ler_o_repositorio`; busca de símbolo leva à linha da
  definição: `test_busca_de_simbolo_leva_a_linha_da_definicao_em_arquivo_longo`.
