# Forja — pacote de orientação para Kiro

Este **não é** o programa concluído. É um **bootstrap de engenharia** para implementar o projeto com Kiro, incluindo orientação completa, prompt inicial, regras seguras, agentes de base, Skills, Steering e Workflow de investigação.

## Como iniciar

1. Verifique permissão do administrador para usar Kiro empresarial no seu projeto futuro open source.
2. Instale o Kiro IDE via https://kiro.dev/downloads/ e autentique usando **Your organization**.
3. Abra esta pasta como projeto no Kiro. Verifique a disponibilidade de Workflows. Não habilite autoaprovação universal.
4. Leia `ORIENTACAO_MESTRA_ECOSSISTEMA_KIRO.md` e cole o conteúdo de `PROMPT_INICIAL_KIRO.md` no chat do Kiro.
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

### Limites desta fase
O agente e um **mock** deterministico: as evidencias que ele produz sao **simuladas** e nao comprovam
funcionalidade real. Integracao Kiro (ACP), memoria/grafos, multiagentes e o painel pixel art chegam nas Fases 2+.
Estado verificado e proximos passos em `docs/STATUS_IMPLEMENTACAO.md`.
