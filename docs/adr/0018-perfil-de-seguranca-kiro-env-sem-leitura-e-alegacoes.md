# ADR-018: Perfil de segurança no Kiro, `.env` sem leitura e conferência de alegações

- Status: aceito

## Contexto (achados no Kiro real, kiro-cli 3.1.0, engine v3)

- A política padrão do Kiro **lê qualquer arquivo da pasta de trabalho sem perguntar**, inclusive `.env`. No teste, um `.env` com valor fictício foi lido e o valor apareceu na resposta. Nenhum pedido de permissão chegou ao mediador da Forja.
  - Leitura fora da pasta e execução de comandos, por outro lado, pedem permissão.
  - Com pastas de projeto reais (ADR-017), isso vazaria segredos.
- `--agent` é **recusado** pelo engine v3 (`the following arguments are not supported with --agent-engine=v3: --agent`). Por isso `APP_KIRO_AGENT` não funcionava.
- Perfis em `~/.kiro/agents/<nome>.json` aparecem como **modos** da sessão (`configOptions` id `mode`) e são escolhidos com `session/set_config_option`.
- `_meta.kiro.policyPreset` em `session/new` aplica presets nativos (`read-workspace`, `edit-workspace`, `dev-shell`...).
- Regras `deny` do perfil vencem qualquer preset ou aprovação. O Kiro informa `Source: agent-profile` no erro.

## Decisões

1. **Perfil `forja`** gravado pela Forja ao iniciar (`perfil_kiro.garantir`; idempotente).
   - Regras: `deny fs_read`/`fs_write` para segredos (`**/.env`, `**/.env.*`, chaves, `credentials*`, `secrets*`, `.netrc`, `.npmrc`, `.pypirc`...) e para as pastas de dados e credenciais da Forja. Os modelos `.env.example/.sample/.template` continuam legíveis.
   - `deny shell` para comandos que imprimem o env (`cat/type/Get-Content *.env*`, `printenv`, `env`, `set`, `docker compose config`, `docker inspect`).
   - O perfil **só restringe**: nenhuma regra `allow`.
2. **Presets por nível de autonomia:**
   - `restrito` → `read-workspace`: lê a pasta em silêncio; segredos negados; editar e executar perguntam.
   - `liberado` e `total` → `edit-workspace`.
   - **Não** usamos `dev-shell`: ele libera `cat`/`grep` em silêncio, e um comando poderia imprimir segredo sem a Forja ver.
3. **Falha fechada:** se o modo `forja` não aparecer na sessão e houver pasta de trabalho de projeto, a execução fica `bloqueada` (`perfil_kiro_indisponivel`).
   - No diretório isolado e vazio a execução segue, porque não há o que vazar. O evento `kiro.perfil` registra o resultado.
   - Uma sessão reaberta (`session/load`) sem o modo cai para sessão nova.
4. **`--agent` removido** do comando. `APP_KIRO_AGENT` agora é ignorado com aviso no log.
5. **`.env` sem leitura:**
   - `env.verificar` devolve só booleanos e nomes: existe, vazia, formato, igual ao valor informado (comparação HMAC, no máximo 3 por chave a cada 10 min), faltantes ou sobrando frente ao `.env.example`, duplicadas e números de linha malformados.
   - Nunca devolve valor, prefixo nem tamanho.
   - O mediador reconhece comandos que **consomem** o arquivo sem exibi-lo (`docker compose --env-file`, `docker run --env-file`, `podman`, `uv run --env-file`, `dotenv run`). Eles valem como execução comum (`usa_env`).
   - Comandos que **imprimem** valores são sensíveis: `printenv`, `env`, `set`, `docker compose config`, `docker inspect`, `docker exec ... env`, `$env:`, `%VAR%`, `echo $VAR`, ou `.env` citado em qualquer outro comando.
6. **Conferência determinística de alegações** (`forja/conversa/alegacoes.py`). Nada é julgado por LLM.
   - "testes passaram" exige um comando de teste observado e concluído.
   - "rodei" exige alguma execução.
   - "criei/alterei `x`" exige escrita observada e o arquivo existente; "removi `x`" exige que ele não exista.
   - Um caminho relativo citado que não existe é sinalizado.
   - Frases negadas não contam. O resultado vira a mensagem "Verificação da Forja", a pendência `alegacoes_nao_verificadas` e o evento `kiro.alegacoes`. A resposta do agente fica intacta.

## Verificação real (kiro-cli 3.1.0, `.env` fictício)

| nível | ler `nota.txt` | ler `.env` | `type .env` | criar arquivo |
|---|---|---|---|---|
| restrito (`read-workspace`) | lido sem perguntar | negado (`deny fs_read`, agent-profile) | negado (`deny shell`) | pediu permissão (o mediador negou) |
| liberado (`edit-workspace`) | lido sem perguntar | negado | negado | criado sem perguntar |

- As ferramentas MCP da Forja (`@forja`) continuam disponíveis no modo `forja`.
- Pelo provedor completo, o protocolo da Forja ("não acesse segredos") já faz o modelo recusar antes de tentar. O perfil é a camada que não depende do modelo obedecer.

## Consequências e pendências

- Trocar de modo reduz o custo de ferramentas informado pelo Kiro (4938 → 4793 tokens). Por isso o sinal "MCP pronto", que espera esse número subir, pode não disparar. A execução espera então o teto (15 s) e segue: é seguro, porém mais lento. Falta reavaliar o sinal.
- Se o usuário editar `~/.kiro/agents/forja.json`, a Forja regrava o arquivo no próximo início. O Kiro pede confirmação para o agente escrever nessa pasta.
