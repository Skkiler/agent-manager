# Forja em conteiner: demonstracao/servidor local com o agente SIMULADO (o Kiro CLI nao existe dentro do conteiner).
# Seguranca: usuario sem privilegios, sistema de arquivos somente leitura (ver compose.yaml), dados num volume proprio.
# Dentro do conteiner o servidor escuta em 0.0.0.0 (obrigatorio para o Docker encaminhar a porta), MAS o compose publica a
# porta SO no loopback do host (127.0.0.1) e o token da API e obrigatorio. Nada fica exposto na rede.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# git: pastas isoladas (git worktree) para tarefas em paralelo
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY pyproject.toml README.md ./
COPY forja ./forja
COPY scripts ./scripts

RUN useradd --create-home --uid 10001 forja && mkdir -p /dados && chown forja:forja /dados
USER forja

ENV APP_BIND_HOST=0.0.0.0 \
    APP_ALLOW_LAN_BIND=true \
    APP_REQUIRE_AUTH=true \
    APP_PORT=8787 \
    APP_DATA_DIR=/dados/data \
    APP_LOG_DIR=/dados/logs \
    APP_KIRO_ACP_ENABLED=false

EXPOSE 8787
HEALTHCHECK --interval=15s --timeout=4s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/v1/saude', timeout=3)"
CMD ["python", "-m", "forja"]
