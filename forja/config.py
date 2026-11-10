"""Configuracao via variaveis de ambiente (ver .env.example). Sem segredos em codigo."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from forja.usuario.layout import PerfilUsuario, nome_do_perfil, resolver_perfil

LOOPBACK = {"127.0.0.1", "localhost", "::1"}


class Configuracoes(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_env: str = "development"
    app_bind_host: str = "127.0.0.1"
    app_port: int = 8787
    app_log_level: str = "INFO"
    # Dados do USUARIO (credenciais, banco, memoria, notas...) ficam FORA do repositorio: ver forja/usuario/layout.py.
    app_user_home: Path | None = None  # base dos dados do usuario (padrao: pasta de dados do sistema)
    app_profile: str = ""  # perfil (padrao: usuario do sistema); cada perfil tem seus proprios dados
    app_data_dir: Path | None = None  # sobrescreve a pasta de dados (testes/uso avancado)
    app_log_dir: Path | None = None
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
    # Memoria: namespaces que o operador desta instancia pode ler/escrever.
    # 'empresa/*' e 'terceiros' exigem inclusao explicita.
    app_memory_allowed_namespaces: str = "publico,pessoal"
    # Raizes de disco autorizadas para ingestao via API (separadas por ';'). Vazio = ingestao via API DESLIGADA.
    app_memory_ingest_roots: str = ""
    # Contexto no prompt: a memoria so e injetada se houver acerto RELEVANTE (senao, zero tokens). Como o prompt vai ao
    # provedor (Kiro), so entram namespaces liberados AQUI de forma explicita (padrao: apenas 'publico').
    # Raizes de disco que as ferramentas de arquivo (outline, mapa, varredura de segredos...) podem ler, separadas por ';'.
    # Vazio = ferramentas de arquivo DESLIGADAS (as que recebem texto continuam disponiveis).
    app_tools_roots: str = ""
    app_context_enabled: bool = True
    app_context_namespaces: str = "publico"
    app_context_budget_tokens: int = 2000
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
        if not 100 <= self.app_context_budget_tokens <= 20_000:
            raise ValueError("APP_CONTEXT_BUDGET_TOKENS deve estar entre 100 e 20000.")
        if not set(self.contexto_namespaces) <= set(self.memoria_namespaces):
            raise ValueError("APP_CONTEXT_NAMESPACES deve ser subconjunto de APP_MEMORY_ALLOWED_NAMESPACES.")
        if self.app_kiro_prompt_timeout_seconds < 10:
            raise ValueError("APP_KIRO_PROMPT_TIMEOUT_SECONDS deve ser >= 10.")
        if self.app_resource_profile not in {"auto", "essencial", "equilibrado", "ampliado"}:
            raise ValueError("APP_RESOURCE_PROFILE invalido.")
        if self.app_max_parallel_cpu_tools < 1:
            raise ValueError("APP_MAX_PARALLEL_CPU_TOOLS deve ser >= 1.")
        return self

    def perfil_usuario(self) -> PerfilUsuario:
        """Perfil efetivo. Se APP_DATA_DIR foi dado, ele e a pasta de dados (e de credenciais) e o resto deriva dele."""
        if self.app_data_dir is not None:
            return PerfilUsuario(Path(self.app_data_dir), nome_do_perfil(self.app_profile), legado=True)
        env = {k: v for k, v in (("APP_USER_HOME", str(self.app_user_home or "")), ("APP_PROFILE", self.app_profile)) if v}
        return resolver_perfil(env or None)

    @property
    def dados_dir(self) -> Path:
        return Path(self.app_data_dir) if self.app_data_dir is not None else self.perfil_usuario().dados

    @property
    def credenciais_dir(self) -> Path:
        return Path(self.app_data_dir) if self.app_data_dir is not None else self.perfil_usuario().credenciais

    @property
    def logs_dir(self) -> Path:
        return Path(self.app_log_dir) if self.app_log_dir is not None else self.perfil_usuario().logs

    @property
    def db_path(self) -> Path:
        return self.dados_dir / "forja.sqlite3"

    @property
    def memoria_namespaces(self) -> frozenset[str]:
        from forja.memoria.modelo import validar_namespace

        brutos = self.app_memory_allowed_namespaces.split(",")
        return frozenset(validar_namespace(n.strip()) for n in brutos if n.strip())

    @property
    def contexto_namespaces(self) -> list[str]:
        from forja.memoria.modelo import validar_namespace

        return [validar_namespace(n.strip()) for n in self.app_context_namespaces.split(",") if n.strip()]

    @property
    def memoria_raizes(self) -> list[Path]:
        return [Path(r.strip()) for r in self.app_memory_ingest_roots.split(";") if r.strip()]

    @property
    def ferramentas_raizes(self) -> tuple[Path, ...]:
        return tuple(Path(r.strip()) for r in self.app_tools_roots.split(";") if r.strip())

    @property
    def kiro_workspace_dir(self) -> Path:
        return self.app_kiro_workspace or (self.perfil_usuario().pasta("workspace") if self.app_data_dir is None else self.dados_dir / "kiro-workspace")

    @property
    def artefatos_dir(self) -> Path:
        return self.dados_dir / "artefatos" if self.app_data_dir is not None else self.perfil_usuario().pasta("artefatos")


@lru_cache
def obter_configuracoes() -> Configuracoes:
    # .env do repositorio (legado/desenvolvimento) e depois o .env do USUARIO, que fica fora do Git e tem prioridade
    return Configuracoes(_env_file=(".env", resolver_perfil().arquivo_env))
