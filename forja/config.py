"""Configuracao via variaveis de ambiente (ver .env.example). Sem segredos em codigo."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOOPBACK = {"127.0.0.1", "localhost", "::1"}


class Configuracoes(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_env: str = "development"
    app_bind_host: str = "127.0.0.1"
    app_port: int = 8787
    app_log_level: str = "INFO"
    app_data_dir: Path = Path("./data")
    app_log_dir: Path = Path("./logs")
    app_session_ttl_minutes: int = 60
    app_enable_local_llm: bool = False
    app_resource_profile: str = "auto"
    app_reserve_free_ram_gb: float = 4.0
    app_max_active_llm_sessions: int = 1
    app_max_parallel_cpu_tools: int = 2
    app_kiro_acp_enabled: bool = False
    # Caminho/nome do executavel (sem shell). Vazio = procurar 'kiro-cli' no PATH e no local padrao do Windows.
    app_kiro_cli_path: str = ""
    # Workspace entregue ao Kiro: por padrao um diretorio VAZIO e isolado (nao o repositorio).
    app_kiro_workspace: Path | None = None
    app_kiro_agent: str = ""  # nome de agente Kiro opcional (vazio = padrao)
    app_kiro_model: str = ""  # id de modelo opcional (vazio = padrao da conta/politica)
    app_kiro_prompt_timeout_seconds: int = 300
    # Tempo maximo que um pedido de aprovacao aguarda o operador; expirado => negado (nunca aprova por omissao).
    app_approval_timeout_seconds: int = 900
    app_require_auth: bool = True
    app_allow_lan_bind: bool = False
    # Opcional: token fixo vindo do ambiente/secret store. Se ausente, gera-se um em data/.
    app_api_token: SecretStr | None = None
    app_allowed_hosts: str = ""  # hosts extras (separados por virgula) quando LAN/HTTPS for aprovado
    app_rate_limit_per_minute: int = 240
    app_lock_lease_seconds: int = 900

    @model_validator(mode="after")
    def _validar(self) -> Configuracoes:
        if self.app_bind_host not in LOOPBACK and not self.app_allow_lan_bind:
            raise ValueError("APP_BIND_HOST nao-loopback exige APP_ALLOW_LAN_BIND=true (aprovacao explicita).")
        if self.app_bind_host not in LOOPBACK and not self.app_require_auth:
            raise ValueError("Bind fora de loopback exige APP_REQUIRE_AUTH=true.")
        if self.app_enable_local_llm:
            raise ValueError("LLM local nao e suportado na Fase 1 (APP_ENABLE_LOCAL_LLM deve ser false).")
        if self.app_kiro_prompt_timeout_seconds < 10:
            raise ValueError("APP_KIRO_PROMPT_TIMEOUT_SECONDS deve ser >= 10.")
        if self.app_resource_profile not in {"auto", "essencial", "equilibrado", "ampliado"}:
            raise ValueError("APP_RESOURCE_PROFILE invalido.")
        if self.app_max_parallel_cpu_tools < 1:
            raise ValueError("APP_MAX_PARALLEL_CPU_TOOLS deve ser >= 1.")
        return self

    @property
    def db_path(self) -> Path:
        return self.app_data_dir / "forja.sqlite3"

    @property
    def kiro_workspace_dir(self) -> Path:
        return self.app_kiro_workspace or (self.app_data_dir / "kiro-workspace")

    @property
    def artefatos_dir(self) -> Path:
        return self.app_data_dir / "artefatos"


@lru_cache
def obter_configuracoes() -> Configuracoes:
    return Configuracoes()
