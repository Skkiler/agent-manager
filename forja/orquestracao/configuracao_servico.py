"""Leitura e gravacao da configuracao do orquestrador (modelo por parte, nivel de detalhe)."""

from __future__ import annotations

from typing import Any

from forja.adapters.sqlite import tabelas as T
from forja.adapters.sqlite.repositorio import RepositorioSqlite
from forja.dominio.configuracao import PARTES, ConfiguracaoSistema, SalvarConfiguracaoIn
from forja.dominio.erros import ConflitoVersao
from forja.dominio.tempo import Relogio, RelogioSistema, iso

CHAVE = "sistema"


class ConfiguracaoServico:
    def __init__(self, repo: RepositorioSqlite, relogio: Relogio | None = None, modelo_padrao: str = "") -> None:
        self.repo = repo
        self.relogio = relogio or RelogioSistema()
        self.modelo_padrao = modelo_padrao  # APP_KIRO_MODEL: usado quando a parte nao define modelo

    def obter(self) -> dict[str, Any]:
        """Configuracao efetiva: o salvo + padroes. `versao` 0 = nunca salvo."""
        with self.repo.leitura() as t:
            linha = t.obter(T.Configuracao, CHAVE)
        cfg = ConfiguracaoSistema.model_validate((linha or {}).get("valor") or {})
        return {
            "versao": (linha or {}).get("versao", 0),
            "atualizado_em": (linha or {}).get("atualizado_em"),
            "configuracao": cfg.model_dump(),
            "partes": [
                {
                    "id": p.id, "rotulo": p.rotulo, "descricao": p.descricao, "usa_modelo": p.usa_modelo,
                    "modelo": cfg.partes[p.id].modelo if p.id in cfg.partes else "",
                    "esforco": cfg.partes[p.id].esforco if p.id in cfg.partes else "",
                    "modelo_efetivo": self._efetivo(cfg, p.id) if p.usa_modelo else None,
                }
                for p in PARTES
            ],
        }

    def _efetivo(self, cfg: ConfiguracaoSistema, parte: str) -> str:
        escolhido = cfg.partes[parte].modelo if parte in cfg.partes else ""
        return escolhido or self.modelo_padrao or "(padrao da conta)"

    def modelo_para(self, parte: str) -> str:
        """Modelo a usar na parte; '' = nao passar --model (padrao da conta). Nunca levanta: configuracao e otimizacao."""
        try:
            with self.repo.leitura() as t:
                linha = t.obter(T.Configuracao, CHAVE)
            cfg = ConfiguracaoSistema.model_validate((linha or {}).get("valor") or {})
        except Exception:  # noqa: BLE001 - valor corrompido nao pode impedir a execucao
            return self.modelo_padrao
        return (cfg.partes[parte].modelo if parte in cfg.partes else "") or self.modelo_padrao

    def esforco_para(self, parte: str) -> str:
        """Esforco (--effort) da parte; vazio = padrao. Nunca levanta."""
        try:
            with self.repo.leitura() as t:
                linha = t.obter(T.Configuracao, CHAVE)
            cfg = ConfiguracaoSistema.model_validate((linha or {}).get("valor") or {})
        except Exception:  # noqa: BLE001
            return ""
        return cfg.partes[parte].esforco if parte in cfg.partes else ""

    def salvar(self, d: SalvarConfiguracaoIn) -> dict[str, Any]:
        agora = iso(self.relogio.agora())
        with self.repo.escrita() as t:
            linha = t.obter(T.Configuracao, CHAVE)
            atual = linha["versao"] if linha else 0
            if d.expected_version != atual:
                raise ConflitoVersao(f"Configuracao mudou (versao {atual}); recarregue antes de salvar.")
            valor = d.configuracao.model_dump()
            if linha is None:
                t.inserir(T.Configuracao, id=CHAVE, valor=valor, versao=1, atualizado_em=agora)
            else:
                t.atualizar(T.Configuracao, CHAVE, valor=valor, versao=atual + 1, atualizado_em=agora)
            t.emitir_evento("configuracao.atualizada", agora, {"versao": atual + 1})
        return self.obter()
