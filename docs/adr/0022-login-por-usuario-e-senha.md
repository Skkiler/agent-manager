# ADR-022: Login do painel por usuário e senha

- Status: aceito

## Contexto

O painel pedia o token da API num diálogo simples: não conferia o token, não mostrava erro nem sucesso e voltava para a mesma
página. Colar um token de 43 caracteres também não é um jeito razoável de entrar todos os dias.

## Decisões

1. **Contas locais** (tabela `usuario`, migração 0013): senha só como hash **scrypt** (n = 2^14, r = 8, p = 1, sal de 16 bytes),
   com os parâmetros guardados junto (subir o custo depois não invalida senhas antigas). Política: 8 a 200 caracteres, sem senhas
   comuns, sem o nome de usuário.
2. **Primeiro acesso** só enquanto não existe conta e só do próprio computador (loopback) ou com o token da API. Em Docker/LAN a
   primeira conta vem da linha de comando (`python -m forja.usuario.contas_cli`), que lê a senha sem ecoar e nunca por argumento.
3. **Sessão**: token aleatório de 256 bits entregue uma vez; no banco fica só o sha256 (tabela `sessao`). Expira por inatividade
   (`APP_SESSION_TTL_MINUTES`, renovada no uso) e no máximo em 12 h. Sair revoga; trocar a senha derruba as outras sessões. O navegador
   guarda a sessão só na aba (sessionStorage) e a envia como Bearer, inclusive no SSE.
4. **Força bruta e enumeração**: mesma mensagem e mesmo custo (hash fictício) para usuário inexistente; bloqueio progressivo da
   conta (5 erros: 30 s, dobrando até 15 min) e do endereço (10 erros em 15 min); a resposta 429 traz `tentar_em_s` e `Retry-After`,
   e a tela mostra a contagem regressiva. Eventos `auth.*` não guardam senha, token nem o nome digitado errado.
5. **Token da API continua** valendo para scripts, MCP e CI (compatível com tudo que já existia).
6. **Tela**: cartão centralizado sobre o painel inerte, rótulos visíveis, mostrar/esconder senha, aviso de Caps Lock, medidor de força
   no primeiro acesso, erro em `role="alert"`, botão com estado "Entrando…", confirmação "Bem-vindo" e volta automática ao login quando
   a sessão expira. Chip com o usuário no cabeçalho: trocar senha e sair.

## Consequências

- Recuperar senha esquecida é pela linha de comando (`redefinir`), no computador do servidor: não há e-mail nem pergunta secreta.
- Uma conta por pessoa; não há papéis/permissões diferentes entre contas (todas têm o mesmo acesso ao painel local).
