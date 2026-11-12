"""Leitura e gravacao da configuracao do orquestrador (modelo, esforco e reservas por parte).

Precedencia por parte: o que o usuario SALVOU > APP_KIRO_MODEL (se definido) > padrao da Forja (dominio/configuracao.PADROES).
"""

from __future__ import annotations

from typing import Any

from forja.adapters.sqlite import tabelas as T
from forja.adapters.sqlite.repositorio import RepositorioSqlite
from forja.dominio.configuracao import PADROES, PARTES, ConfiguracaoSistema, ParteConfig, SalvarConfiguracaoIn
from forja.dominio.erros import ConflitoVersao
from forja.dominio.tempo import Relogio, RelogioSistema, iso

CHAVE = "sistema"


class ConfiguracaoServico:
    def __init__(self, repo: RepositorioSqlite, relogio: Relogio | None = None, modelo_padrao: str = "") -> None:
        self.repo = repo
        self.relogio = relogio or RelogioSistema()
        self.modelo_padrao = modelo_padrao  # APP_KIRO_MODEL: vale para as partes que o usuario nao configurou

    def _cfg(self) -> tuple[ConfiguracaoSistema, dict | None]:
        with self.repo.leitura() as t:
            linha = t.obter(T.Configuracao, CHAVE)
        return ConfiguracaoSistema.model_validate((linha or {}).get("valor") or {}), linha

    def _seguro(self) -> ConfiguracaoSistema:
        try:
            return self._cfg()[0]
        except Exception:  # noqa: BLE001 - valor corrompido nao pode impedir a execucao: cai nos padroes
            return ConfiguracaoSistema()

    def _resolver(self, cfg: ConfiguracaoSistema, parte: str) -> tuple[str, str, list[str], str]:
        """(modelo, esforco, alternativas, origem) efetivos da parte."""
        salvo = cfg.partes.get(parte) or ParteConfig()
        padrao = PADROES.get(parte) or ParteConfig()
        if salvo.modelo:
            modelo, origem = salvo.modelo, "usuario"
        elif self.modelo_padrao:
            modelo, origem = self.modelo_padrao, "ambiente"
        else:
            modelo, origem = padrao.modelo, "forja" if padrao.modelo else "conta"
        # esforco depende do modelo: o padrao so vale se o modelo efetivo for o padrao da parte
        esforco = salvo.esforco or (padrao.esforco if modelo == padrao.modelo else "")
        alternativas = list(salvo.alternativas) or (list(padrao.alternativas) if origem == "forja" else [])
        return modelo, esforco, alternativas, origem

    def obter(self) -> dict[str, Any]:
        """Configuracao efetiva: o salvo + padroes. `versao` 0 = nunca salvo."""
        cfg, linha = self._cfg()
        partes = []
        for p in PARTES:
            item: dict[str, Any] = {
                "id": p.id, "rotulo": p.rotulo, "descricao": p.descricao, "usa_modelo": p.usa_modelo, "papel": p.papel,
                "modelo": cfg.partes[p.id].modelo if p.id in cfg.partes else "",
                "esforco": cfg.partes[p.id].esforco if p.id in cfg.partes else "",
                "alternativas": list(cfg.partes[p.id].alternativas) if p.id in cfg.partes else [],
                "modelo_efetivo": None, "esforco_efetivo": None, "origem": None,
                "padrao": PADROES[p.id].model_dump() if p.id in PADROES else None,
            }
            if p.usa_modelo:
                m, e, _a, origem = self._resolver(cfg, p.id)
                item.update(modelo_efetivo=m or "(padrao da conta)", esforco_efetivo=e or "(padrao)", origem=origem)
            partes.append(item)
        return {"versao": (linha or {}).get("versao", 0), "atualizado_em": (linha or {}).get("atualizado_em"),
                "configuracao": cfg.model_dump(), "partes": partes}

    def modelo_para(self, parte: str) -> str:
        """Modelo a usar na parte; '' = padrao da conta. Nunca levanta: configuracao e otimizacao."""
        return self._resolver(self._seguro(), parte)[0]

    def esforco_para(self, parte: str) -> str:
        return self._resolver(self._seguro(), parte)[1]

    def alternativas_para(self, parte: str) -> list[str]:
        """Modelos de reserva, em ordem (vazio = sem fallback: falha fechada). Nunca levanta."""
        return self._resolver(self._seguro(), parte)[2]

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
