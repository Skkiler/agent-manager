# Forja — pacote de orientação para Kiro

Este **não é** o programa concluído. É um **bootstrap de engenharia** para implementar o projeto com Kiro, incluindo orientação completa, prompt inicial, regras seguras, agentes de base, Skills, Steering e Workflow de investigação.

## Como iniciar

1. Verifique permissão do administrador para usar Kiro empresarial no seu projeto futuro open source.
2. Instale o Kiro IDE via https://kiro.dev/downloads/ e autentique usando **Your organization**.
3. Abra esta pasta como projeto no Kiro. Verifique a disponibilidade de Workflows. Não habilite autoaprovação universal.
4. (Opcional, arquivos locais que nao sobem ao Git) Leia `ORIENTACAO_MESTRA_ECOSSISTEMA_KIRO.md` e cole `PROMPT_INICIAL_KIRO.md` no chat do Kiro.
5. O agente iniciará pelas fases 0 e 1, criando código e testes reais antes de avançar. As integrações ACP/MCP dependem da versão, conta e políticas efetivamente disponíveis.

## Proteção de dados

Mantenha dados privados em pastas ignoradas; não importe arquivos empresariais. Modelos, bancos, logs, credenciais e referências visuais privadas ficam fora do Git. As imagens enviadas como inspiração **não são redistribuídas neste pacote**, e devem permanecer fora do repositório público até confirmação de licença.

## Nucleo Fase 1 — executar no Windows

Pre-requisito: Python 3.12+ (testado em 3.13). Nao exige Kiro CLI nem modelo local.

```powershell
# 1. ambiente virtual (recomendado) e dependencias
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

# 2. configuracao local (opcional; ha defaults seguros)
Copy-Item .env.example .env   # ajuste se desejar; nunca commite .env

# 3. testes reais (unitarios + integracao)
python -m pytest -q
python -m ruff check forja tests

# 4. subir o servidor (loopback 127.0.0.1:8787 por padrao)
python -m forja
```

Na primeira execucao e gerado um token em `data\api_token.txt` (ignorado no Git). Abra
`http://127.0.0.1:8787`, cole o token no painel e crie uma tarefa de exemplo (agente **mock**, dados sinteticos).

Smoke test ponta a ponta contra o servidor em execucao:

```powershell
python scripts\smoke.py            # le o token de data\api_token.txt
# ou: python scripts\smoke.py --base http://127.0.0.1:8787 --token <TOKEN>
```

### Acesso pelo notebook (LAN)
Recomendado: tunel SSH a partir do notebook, mantendo o servidor em loopback:

```powershell
ssh -N -L 8787:127.0.0.1:8787 usuario@IP_PRIVADO_DESKTOP
```

Depois abra `http://127.0.0.1:8787` no notebook. Bind direto em LAN exige aprovacao explicita
(`APP_ALLOW_LAN_BIND=true` + `APP_REQUIRE_AUTH=true`) e, de preferencia, HTTPS/reverse proxy autenticado.

### Kiro real via ACP (Fase 2, opcional)
Desligado por padrao (usa o mock). Para usar o Kiro CLI:

```powershell
python scripts\diagnostico_kiro.py     # versao, login sim/nao, handshake ACP (sem consumir creditos)
kiro-cli login                         # acao sua (SSO); a Forja nunca le nem guarda o token
$env:APP_KIRO_ACP_ENABLED = "true"     # ou no .env (nunca commitado)
python -m forja
```
O Kiro recebe um workspace vazio e isolado (`data\kiro-workspace`), permissoes de ferramenta sao negadas por padrao
e apenas tarefas de `analise`/`documentacao` sao aceitas. Sem login, a tarefa fica `bloqueada` com
`reautenticacao_necessaria` e pode ser retomada. Detalhes em `docs/adr/0004-kiro-acp-adaptador.md`.

### Aprovações por ação (não por comando)
Quando o Kiro pede para usar ferramentas, a Forja traduz o pedido em uma pergunta de ação
("Posso excluir forçadamente `build`?"), **agrupa** pedidos simultâneos em uma só decisão e deixa você aprovar
todos, alguns ou nenhum, com um **adendo** livre e a opção "lembrar nesta execução". O painel tem a seção
"Aprovações pendentes"; via API: `POST /api/v1/aprovacoes/{id}/decidir` e `POST /api/v1/aprovacoes/decidir-lote`.
Ações que envolvem segredos (`.env`, chaves, tokens) são negadas automaticamente. Sem resposta no prazo
(`APP_APPROVAL_TIMEOUT_SECONDS`), o pedido é **negado**. Detalhes em `docs/adr/0006-aprovacao-por-acao-agrupada.md`.

### Memória / segundo cérebro (Fase 3)
Busca exata (SQLite FTS5) em **memórias** (com proveniência, estados `candidato → … → validado` e histórico) e em
**código/documentos indexados** (símbolos Python via AST, apontando para a linha da definição). Tudo isolado por
*namespace* (`publico`, `pessoal`, `terceiros`, `empresa/<id>`); por padrão esta instância só enxerga `publico` e `pessoal`.

```powershell
# habilitar ingestao de um repositorio (raizes autorizadas separadas por ';'; vazio = desligado)
$env:APP_MEMORY_INGEST_ROOTS = "C:\caminho\do\repositorio-publico"
# POST /api/v1/memorias/ingerir {"namespace":"publico","raiz":"...","repositorio":"demo"}   (incremental, por SHA-256)
# GET  /api/v1/memorias/buscar?q=ClienteAcp&namespace=publico            (painel: seção "Memória e código")
```
O conteúdo da memória fica em `data\forja.sqlite3` (**ignorado pelo Git**); PII e segredos são redigidos antes de gravar;
resultados são sempre *dados não confiáveis* (nunca instruções). Evidências simuladas (mock) não validam memória.
Detalhes e limites em `docs/adr/0007-memoria-fts5-namespaces-acl.md`.

### Integracoes de rede (Jira, GitHub, agenda por URL)
Disponiveis, mas **desligadas e sem configuracao**. Em *Integracoes* escolha o conector, informe o endereco, os projetos/repositorios
permitidos e os **nomes** das variaveis (`FORJA_INT_*`); o **valor** do token fica so no `.env` ou no ambiente (veja `.env.example`) e a
tela mostra apenas "presente/ausente". Sao somente leitura, HTTPS, restritas ao host configurado, com limite por minuto e auditoria.
Detalhes e riscos em `docs/adr/0013-integracoes-de-rede-configuraveis.md`.

### Painel (interface estilo IDE)
Abra `http://127.0.0.1:8787/` com o servidor local rodando. Areas: **Tarefas** (Kanban), **Quadro** (comunicacao entre master, operador
e agentes), **Memoria** (grafo do segundo cerebro com busca, leitura/edicao e backlinks, estilo Obsidian), **Ferramentas**,
**Integracoes** e **Config** (modelo e esforco de IA por parte do sistema, nivel de detalhe e pedido de revisao do esquema).
Atalhos: Ctrl+B (lateral), Ctrl+Shift+B (conversa), Ctrl+J (painel inferior). Para ver o painel com dados ficticios:
`python scripts\semear_demo.py` (servidor local) e, opcionalmente, `python scripts\inspecionar_painel.py --interagir`
(requer `pip install playwright`; confere erros de console/CSP e fluxos de usuario num navegador real).

### Contexto economico e conversa com o desenvolvedor (Fase 4)
Com `APP_CONTEXT_ENABLED=true`, a Forja anexa ao prompt **so** memorias relevantes (portoes de relevancia, cobertura e
orcamento de `APP_CONTEXT_BUDGET_TOKENS`) dos namespaces em `APP_CONTEXT_NAMESPACES` (padrao `publico`). O agente responde em
secoes e agrupa decisoes; voce responde uma vez em `POST /api/v1/tarefas/{id}/conversa` e a execucao retoma com prompt compacto.
Tokens exibidos sao **estimados**. Ver `docs/adr/0008`, `0009` e `0010`.

Indexar uma pasta **local** (banco proprio, nunca versionado) e consultar:

```powershell
python scripts\memoria_ingerir.py --raiz "C:\minha\pasta" --namespace pessoal --repositorio minha-pasta `
  --db data\segundo-cerebro.sqlite3 --extensoes .py .md --consultar "conexao com banco" --mostrar-trechos
```

### Ferramentas dos agentes, quadro e segundo cerebro (Fase 4)
- `GET /api/v1/ferramentas` lista as ferramentas N0 (outline, resumo de pytest/diff/logs, mapa do repositorio, varredura de segredos,
  esquema SQLite, conversor, orcamento de tokens); `POST /api/v1/ferramentas/{id}/executar` as executa. Ferramentas de arquivo so leem
  as pastas **permitidas** no menu Configuracoes > Privacidade (desligado por padrao; `APP_TOOLS_ROOTS` e apenas uma semente legada). Economia medida: `python scripts\medir_ferramentas.py`.
- Quadro de comunicacao entre master, operador e agentes: `POST/GET /api/v1/quadro`, `POST /api/v1/quadro/retirar`, `POST /api/v1/quadro/{id}/resolver`;
  visao do master em `GET /api/v1/controle/painel`.
- `POST /api/v1/tarefas/{id}/propor-memoria` gera uma memoria **candidata** a partir de uma tarefa concluida (nunca validada sozinha).
Detalhes em `docs/adr/0011-catalogo-de-ferramentas-quadro-e-propostas.md`.
### Seus dados ficam fora do Git e o menu de configuracoes
- Memoria, notas, credenciais, integracoes, preferencias, tarefas e logs vivem no **perfil do usuario**, fora do repositorio:
  `%LOCALAPPDATA%\Forja\perfis\<usuario>\` (mude com `APP_USER_HOME` / `APP_PROFILE`). So codigo, logica e configuracao padrao sobem ao Git.
- Quem ja tem `./data` continua funcionando (modo legado, com aviso). Para migrar sem apagar nada: `python scripts\migrar_dados_usuario.py` (simulacao) e depois `--executar`.
- **Configuracoes** (tela): categorias Aparencia, Eficiencia, Consumo, Privacidade, Seguranca e Manutencao, cada uma com abas Gerais/Avancadas;
  toda opcao traz explicacao, exemplos (baixo/medio/alto) e consequencias. API: `GET/PUT /api/v1/preferencias`. Detalhes no ADR-014.

### Ferramentas da Forja dentro do Kiro (MCP) e escrita com aprovacao
- Em Configuracoes > Eficiencia > Avancadas: `Dar ao Kiro as ferramentas da Forja (MCP)` (desligado por padrao) anexa `python -m forja.mcp` (stdio, sem porta) a cada sessao.
- Retomadas reabrem a conversa do Kiro (`session/load`) quando ele anuncia o recurso; senao, usam um resumo.
- Jira, GitHub e Trello aceitam escrita SO como proposta: ligue `permitir escrita` na integracao; cada acao aparece em Integracoes > Acoes aguardando voce.
- Memoria > Avaliar a busca: rotule perguntas reais e veja recall/MRR/nDCG no seu corpus (rotulos ficam no seu perfil). Detalhes no ADR-015.

### Como abrir (app local instalavel)
- `python -m forja --abrir` sobe o servidor em loopback e abre a interface. No Edge/Chrome use "Instalar Forja" para ter janela e icone de aplicativo.
- Configuracoes > Agentes: nivel de autonomia (restrito/liberado/total), metodos como tags (ex.: Cauteloso + Orientado a testes) e observacoes guia.
- Integracoes > Busca web: Brave Search API (chave no .env) ou SearXNG proprio; o agente le so paginas que vieram da busca.
- Avaliar a busca no seu codigo: `python scripts\avaliar_busca_codigo.py --raiz <pasta> [--embeddings]` (copia temporaria, so numeros na saida). Detalhes no ADR-016.

### Limites desta fase
O agente e um **mock** deterministico: as evidencias que ele produz sao **simuladas** e nao comprovam
funcionalidade real. Integracao Kiro (ACP), memoria/grafos, multiagentes e o painel pixel art chegam nas Fases 2+.
Estado verificado e proximos passos em `docs/STATUS_IMPLEMENTACAO.md`.
