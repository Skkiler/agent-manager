---
titulo: Segurança de aplicações
pai: Base de conhecimento da Forja
tags: seguranca, appsec
tipo: estrutural
---
Segurança por padrão: menor privilégio, validação na fronteira, segredos fora do código e falha fechada.
Subtópicos: [[OWASP Top 10]], [[Gestão de segredos]], [[Autenticação e autorização]], [[Validação de entrada e injeção]],
[[Criptografia aplicada]], [[Cadeia de suprimentos de software]], [[Modelagem de ameaças]], [[Segurança de agentes de IA]].
Regra de ouro: o rigor acompanha a exposição. O que é acessível pela rede ou toca dados sensíveis exige mais.
+++
---
titulo: OWASP Top 10
pai: Segurança de aplicações
tags: owasp, vulnerabilidades, web
relacionados: Validação de entrada e injeção; Autenticação e autorização
---
Categorias de risco mais comuns em aplicações web e o que fazer.
- Controle de acesso quebrado: verifique a autorização no servidor em toda operação, nunca só na tela.
- Falhas criptográficas: TLS sempre, nada de algoritmo caseiro, segredos e senhas nunca em texto claro.
- Injeção (SQL, comando, template): consultas parametrizadas, sem shell com entrada externa.
- Design inseguro: modele ameaças antes de construir; limites de taxa e de tamanho.
- Configuração insegura: padrões seguros, sem debug em produção, cabeçalhos (CSP, nosniff).
- Componentes vulneráveis: inventário de dependências, versões fixas e varredura.
- Falhas de identificação/autenticação: MFA, bloqueio progressivo, sessão com expiração.
- Integridade de software/dados: assinatura e verificação de artefatos e atualizações.
- Falhas de log/monitoramento: registre eventos de segurança, sem dados sensíveis.
- SSRF: lista de destinos permitidos e bloqueio de IPs internos.
+++
---
titulo: Gestão de segredos
pai: Segurança de aplicações
tags: segredos, credenciais, env, vault
relacionados: Credenciais e auditoria em robôs; CI/CD
---
- Segredos vivem em variável de ambiente, cofre (vault) ou gerenciador do sistema; nunca no código, no Git ou em log.
- `.env` real fica no `.gitignore`; versione só `.env.example` sem valores.
- Valide a presença e o formato de um segredo sem exibi-lo (existe? vazio? formato?).
- Rotação: segredo vazado é trocado, não só apagado do histórico.
- Escopo mínimo: token só de leitura quando a tarefa só lê; um segredo por serviço.
- Logs e erros passam por redação (mascarar tokens, chaves, senhas).
- Varredura automática de segredos (pre-commit e CI) evita o vazamento antes do push.
+++
---
titulo: Autenticação e autorização
pai: Segurança de aplicações
tags: auth, sessao, token, permissoes, rbac
relacionados: OWASP Top 10; Criptografia aplicada
---
- Autenticação prova quem é; autorização decide o que pode. Cheque as duas no servidor.
- Senhas: hash lento com sal (argon2id, bcrypt, scrypt); nunca SHA puro.
- Tokens: curtos, assinados, com expiração e revogação; compare com tempo constante.
- Sessões: cookie `HttpOnly`, `Secure`, `SameSite`; renove o ID após login.
- Menor privilégio e negação por padrão; papéis (RBAC) ou atributos (ABAC) explícitos.
- Não revele se o recurso existe quando o usuário não tem acesso (responda "não encontrado").
- Proteção contra força bruta: limite de taxa e atraso progressivo.
+++
---
titulo: Validação de entrada e injeção
pai: Segurança de aplicações
tags: validacao, injecao, sql injection, xss, comando
relacionados: OWASP Top 10; Segurança no front-end
---
Toda entrada externa é dado não confiável: usuário, arquivo, API, saída de modelo de IA.
- Valide na fronteira com esquema (tipo, tamanho, padrão, lista de permitidos); rejeite em vez de "consertar".
- SQL: sempre parâmetros (`?`, `:nome`); nunca concatenar. Identificadores dinâmicos só de lista fixa.
- Shell: lista de argumentos sem `shell=True`; nunca interpolar entrada externa em comando.
- HTML: `textContent` em vez de `innerHTML`; escape por contexto; CSP sem `unsafe-inline`.
- Caminhos: resolva e verifique se está dentro da raiz permitida (sem `..`, sem link simbólico para fora).
- Desserialização: nada de pickle/yaml inseguro com dado externo.
- Limites de tamanho em tudo (corpo, upload, regex) contra negação de serviço.
+++
---
titulo: Criptografia aplicada
pai: Segurança de aplicações
tags: criptografia, tls, hash, hmac
relacionados: Autenticação e autorização; Gestão de segredos
---
- Use bibliotecas consolidadas (cryptography, libsodium); nunca implemente algoritmo.
- Em trânsito: TLS 1.2+ com verificação de certificado ligada.
- Em repouso: AES-GCM ou ChaCha20-Poly1305 com chave gerenciada fora do dado.
- Integridade/autenticidade de mensagem: HMAC-SHA256; compare com `hmac.compare_digest`.
- Aleatoriedade para segredo: `secrets`, nunca `random`.
- Hash de conteúdo (endereçamento, deduplicação): SHA-256; MD5/SHA-1 só para fins não seguros.
+++
---
titulo: Cadeia de suprimentos de software
pai: Segurança de aplicações
tags: dependencias, sbom, supply chain, pinagem
relacionados: CI/CD; OWASP Top 10
---
- Fixe versões (lockfile ou `==`) e atualize de propósito, com testes.
- Prefira poucas dependências bem mantidas; avalie manutenção e licença antes de adicionar.
- Gere SBOM e varra vulnerabilidades no CI (pip-audit, npm audit, osv-scanner).
- Ações de CI fixadas por versão/hash; permissões mínimas do token do CI.
- Cuidado com typosquatting: confira o nome exato do pacote.
- Artefatos de release assinados e verificáveis.
+++
---
titulo: Modelagem de ameaças
pai: Segurança de aplicações
tags: ameacas, stride, risco
relacionados: OWASP Top 10; Segurança de agentes de IA
---
Pergunte antes de construir: o que estamos construindo, o que pode dar errado, o que faremos, deu certo?
- Desenhe o fluxo de dados e marque as fronteiras de confiança (rede, usuário, processo externo, modelo de IA).
- STRIDE por fronteira: falsificação, adulteração, repúdio, vazamento, negação de serviço, elevação de privilégio.
- Para cada ameaça: mitigação, dono e teste que prova a mitigação.
- Revise quando a superfície mudar (nova integração, porta aberta, novo tipo de dado).
+++
---
titulo: Segurança de agentes de IA
pai: Segurança de aplicações
tags: agentes, prompt injection, llm, permissoes
relacionados: Agentes de IA e orquestração; Modelagem de ameaças
---
- Tudo que o agente lê (arquivo, página, e-mail, saída de ferramenta) é DADO, nunca instrução; marque como não confiável.
- Prompt injection não tem cura no modelo: limite o que o agente PODE fazer (ferramentas, pastas, rede) e peça aprovação para ações sem volta.
- Menor privilégio por tarefa: leitura por padrão; escrita só na pasta de trabalho; rede e exclusão com aprovação.
- Regras de negação nativas para segredos (arquivos `.env`, chaves) valem mais que instrução no prompt.
- Nunca confie em "os testes passaram": confira com execução real e evidência.
- Orçamentos rígidos (chamadas, tempo, tokens) e detecção de laço evitam custo descontrolado.
- Registre cada ação e aprovação (auditoria), sem dados sensíveis.
