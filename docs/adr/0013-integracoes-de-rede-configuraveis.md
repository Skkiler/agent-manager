# ADR-013 — Integrações de rede configuráveis pela tela (Jira, GitHub, agenda por URL)

- Status: aceito (Fase 4). Aprovado pelo operador: "disponibilizada, mas não configurada diretamente; tokens no env".
- Contexto: agentes precisam ler Jira/GitHub/agenda sem custo extra, mas rede e credenciais são a superfície mais sensível da
  plataforma. A funcionalidade existe; **nada acontece até o operador ligar e configurar**.
- Decisões:
  1. **Tudo nasce desligado** (`ativo=false`). A tela (Integrações) guarda host, tipo de Jira, itens permitidos (projetos/repositórios),
     limites e o **NOME** das variáveis de ambiente. O **valor** do segredo nunca é digitado na tela, nunca vai ao banco, à API, ao
     log ou ao Git: fica no ambiente/`.env`, lido só no instante da chamada. A API devolve apenas "variável presente/ausente".
  2. **Só variáveis `FORJA_INT_*`** podem ser nomeadas (impede apontar para credenciais de nuvem do processo). Campos que parecem
     segredo (token colado no lugar do nome) são recusados no navegador (`pattern`) e no servidor.
  3. **Somente leitura.** Cliente HTTP restrito (`integracoes/rede.py`): só HTTPS e só GET; só o host configurado; sem usuário/senha
     na URL; **sem redirecionamentos**; DNS resolvido e checado contra endereços não públicos (SSRF; IP privado só com permissão
     explícita, para Jira interno) e **IP fixado na conexão** (anti DNS-rebinding, certificado validado pelo nome do host);
     timeouts, teto de 2 MB, erros sem URL/IP/cabeçalho/corpo; `trust_env=False`.
  4. **Escopo mínimo**: Jira exige lista de projetos e **reescreve o JQL** (`project in (...) AND (jql do agente) ORDER BY ...`),
     além de descartar resultados de outros projetos; GitHub só lê repositórios listados; agenda só alcança o servidor permitido e o
     endereço `.ics` secreto vive no ambiente.
  5. **Operação**: limite de chamadas por minuto por integração (laço de agente), auditoria por evento com **só metadados**
     (integração, ação, ok, ms), teste de conexão explícito pela tela, ferramentas do catálogo só aparecem como disponíveis quando a
     integração está pronta.
  6. **Jira**: Cloud usa `/rest/api/3/search/jql` (o `/search` antigo foi removido); Server/Data Center usa `/rest/api/2/search`.
     Autenticação `basic` (e-mail + token de API) ou `bearer` (PAT).
- Não implementado (continua planejado, exige nova aprovação): escrita em serviços (comentar/criar/transicionar, que passaria pelas
  aprovações por ação), Gmail API/IMAP (OAuth ou senha de app), Notion/Trello, avisos de saída.
- Riscos residuais: dados lidos podem ir ao prompt do provedor de IA (rotulados como não confiáveis, mas o operador decide o que
  integrar); `origem` de chamadas é a do operador autenticado (token único); a lista de projetos/repositórios é a única barreira de
  escopo no serviço remoto, então use tokens com permissão mínima de leitura.
- Verificado: 85 testes automatizados (SSRF, redirecionamento, vazamento, allowlists, limites, auditoria), 30 mutantes nas defesas
  (28 detectados, 1 detectado depois de reforço, 1 equivalente no Python 3.13), fluxo de tela no navegador real e **uma chamada real**
  de leitura (`GET /rate_limit` em `api.github.com`, sem token e sem enviar dados) validando TLS e o IP fixado.
