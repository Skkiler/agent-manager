"""Contas do painel: primeiro acesso, login por usuario e senha, sessoes e troca de senha.

Protecoes:
- senha so como hash scrypt; usuario inexistente custa o mesmo tempo e devolve a MESMA mensagem (nao revela quem existe);
- bloqueio progressivo por conta (5 erros seguidos: 30 s, dobrando ate 15 min) e por endereco (10 erros em 15 min: 15 min);
- sessao = token aleatorio de 256 bits entregue uma vez; no banco fica so o sha256. Expira por inatividade (APP_SESSION_TTL_MINUTES)
  e no maximo em 12 h; sair revoga; trocar a senha revoga as outras sessoes;
- o token da API (scripts, MCP) continua valendo para chamadas programaticas.
Nada aqui registra senha, token ou nome digitado errado.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select

from forja.adapters.sqlite import tabelas as T
from forja.adapters.sqlite.repositorio import RepositorioSqlite, novo_id
from forja.dominio.erros import AcessoBloqueado, Conflito, CredenciaisInvalidas
from forja.dominio.tempo import Relogio, RelogioSistema, iso
from forja.seguranca import senhas

MSG_INVALIDA = "Usuário ou senha incorretos."
FALHAS_ANTES_DE_BLOQUEAR = 5
BLOQUEIO_BASE_S, BLOQUEIO_MAX_S = 30, 900
FALHAS_POR_ENDERECO, JANELA_ENDERECO_S = 10, 900
DURACAO_MAXIMA_H = 12


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class ContasServico:
    def __init__(self, repo: RepositorioSqlite, inatividade_min: int = 60, relogio: Relogio | None = None) -> None:
        self.repo = repo
        self.inatividade = timedelta(minutes=max(5, int(inatividade_min)))
        self.relogio = relogio or RelogioSistema()
        self._enderecos: dict[str, list[datetime]] = {}  # falhas recentes por endereco (memoria; reiniciar zera)
        self._mu = threading.Lock()

    def _agora(self) -> datetime:
        return self.relogio.agora()

    # ------------------------------------------------------------------ estado
    def existe_conta(self) -> bool:
        with self.repo.leitura() as t:
            return bool(t.s.scalar(select(func.count()).select_from(T.Usuario)))

    def _emitir(self, tipo: str, payload: dict[str, Any]) -> None:
        with self.repo.escrita() as t:
            t.emitir_evento(tipo, iso(self._agora()), payload)

    # ------------------------------------------------------------------ contas
    def criar(self, nome: str, senha: str, ator: str = "operador") -> dict[str, Any]:
        nome = senhas.normalizar_nome(nome)
        senhas.validar_senha(senha, nome)
        agora = iso(self._agora())
        with self.repo.escrita() as t:
            if t.listar(T.Usuario, nome=nome, limite=1):
                raise Conflito("Já existe uma conta com esse usuário.")
            u = t.inserir(T.Usuario, id=novo_id("U"), nome=nome, senha_hash=senhas.gerar_hash(senha), falhas=0,
                          bloqueado_ate=None, ultimo_acesso=None, criado_em=agora, atualizado_em=agora)
            t.emitir_evento("auth.conta_criada", agora, {"usuario_id": u["id"], "ator": ator[:60]})
        return {"id": u["id"], "usuario": nome}

    def configurar_primeira(self, nome: str, senha: str) -> dict[str, Any]:
        """Primeiro acesso: so enquanto NAO existe conta (a rota tambem exige loopback ou o token da API)."""
        with self._mu:
            if self.existe_conta():
                raise Conflito("O acesso já foi configurado. Entre com seu usuário e senha.")
            conta = self.criar(nome, senha, "primeiro_acesso")
        return self._abrir_sessao(conta["id"], conta["usuario"])

    # ------------------------------------------------------------------ login
    def _bloqueio_endereco(self, endereco: str) -> int:
        limite = self._agora() - timedelta(seconds=JANELA_ENDERECO_S)
        with self._mu:
            recentes = [x for x in self._enderecos.get(endereco, []) if x > limite]
            self._enderecos[endereco] = recentes
            if len(recentes) >= FALHAS_POR_ENDERECO:
                return max(1, int((recentes[0] + timedelta(seconds=JANELA_ENDERECO_S) - self._agora()).total_seconds()))
        return 0

    def _falhou_endereco(self, endereco: str) -> None:
        with self._mu:
            self._enderecos.setdefault(endereco, []).append(self._agora())
            if len(self._enderecos) > 5000:  # memoria limitada
                self._enderecos = dict(list(self._enderecos.items())[-1000:])

    def entrar(self, nome: str, senha: str, endereco: str = "desconhecido") -> dict[str, Any]:
        espera = self._bloqueio_endereco(endereco)
        if espera:
            raise AcessoBloqueado(f"Muitas tentativas deste computador. Tente de novo em {espera} s.", espera)
        try:
            nome = senhas.normalizar_nome(nome)
        except Exception:  # noqa: BLE001 - nome fora do formato: mesma resposta (e mesmo custo) de senha errada
            nome = ""
        with self.repo.leitura() as t:
            achados = t.listar(T.Usuario, nome=nome, limite=1) if nome else []
        u = achados[0] if achados else None
        agora = self._agora()
        if u and u["bloqueado_ate"] and u["bloqueado_ate"] > iso(agora):
            senhas.conferir(senha or "", senhas.HASH_FICTICIO)  # tempo igual ao de uma tentativa normal
            espera = max(1, int((datetime.fromisoformat(u["bloqueado_ate"]) - agora).total_seconds()))
            raise AcessoBloqueado(f"Conta bloqueada por tentativas erradas. Tente de novo em {espera} s.", espera)
        ok = senhas.conferir(senha or "", u["senha_hash"] if u else senhas.HASH_FICTICIO)
        if not (u and ok):
            self._falhou_endereco(endereco)
            if u:
                falhas = u["falhas"] + 1
                bloqueio = None
                if falhas >= FALHAS_ANTES_DE_BLOQUEAR:
                    s = min(BLOQUEIO_MAX_S, BLOQUEIO_BASE_S * 2 ** (falhas - FALHAS_ANTES_DE_BLOQUEAR))
                    bloqueio = iso(agora + timedelta(seconds=s))
                with self.repo.escrita() as t:
                    t.atualizar(T.Usuario, u["id"], falhas=falhas, bloqueado_ate=bloqueio)
            self._emitir("auth.falhou", {"conta_existe": None})  # nunca o nome digitado nem se a conta existe
            restantes = FALHAS_ANTES_DE_BLOQUEAR - (u["falhas"] + 1) if u else None
            raise CredenciaisInvalidas(MSG_INVALIDA + (f" Restam {restantes} tentativa(s) antes de um bloqueio temporário."
                                                       if restantes is not None and 0 < restantes <= 2 else ""))
        with self.repo.escrita() as t:
            t.atualizar(T.Usuario, u["id"], falhas=0, bloqueado_ate=None, ultimo_acesso=iso(agora))
        return self._abrir_sessao(u["id"], u["nome"])

    def _abrir_sessao(self, usuario_id: str, nome: str) -> dict[str, Any]:
        token = secrets.token_urlsafe(32)
        agora = self._agora()
        expira = agora + timedelta(hours=DURACAO_MAXIMA_H)
        with self.repo.escrita() as t:
            t.s.execute(delete(T.Sessao).where(T.Sessao.expira_em <= iso(agora)))  # limpeza barata
            t.inserir(T.Sessao, id=_sha(token), usuario_id=usuario_id, criado_em=iso(agora), ultimo_uso=iso(agora), expira_em=iso(expira))
            t.emitir_evento("auth.entrou", iso(agora), {"usuario_id": usuario_id})
        return {"token": token, "usuario": nome, "expira_em": iso(expira), "inatividade_min": int(self.inatividade.total_seconds() // 60)}

    # ------------------------------------------------------------------ sessao
    def sessao(self, token: str | None) -> dict[str, Any] | None:
        """Sessao valida para o token (renova a inatividade) ou None. Nunca levanta."""
        if not token or len(token) > 256:
            return None
        agora = self._agora()
        try:
            with self.repo.escrita() as t:
                s = t.obter(T.Sessao, _sha(token))
                if s is None:
                    return None
                ocioso = datetime.fromisoformat(s["ultimo_uso"]) + self.inatividade
                if s["expira_em"] <= iso(agora) or ocioso <= agora:
                    t.s.execute(delete(T.Sessao).where(T.Sessao.id == s["id"]))
                    return None
                u = t.obter(T.Usuario, s["usuario_id"])
                if u is None:
                    return None
                if (agora - datetime.fromisoformat(s["ultimo_uso"])).total_seconds() > 30:  # menos escrita por requisicao
                    t.atualizar(T.Sessao, s["id"], ultimo_uso=iso(agora))
                return {"usuario_id": u["id"], "usuario": u["nome"], "expira_em": s["expira_em"]}
        except Exception:  # noqa: BLE001 - na duvida, sem sessao (falha fechada)
            return None

    def sair(self, token: str | None) -> None:
        if token:
            with self.repo.escrita() as t:
                t.s.execute(delete(T.Sessao).where(T.Sessao.id == _sha(token)))
                t.emitir_evento("auth.saiu", iso(self._agora()), {})

    def trocar_senha(self, token: str, atual: str, nova: str) -> dict[str, Any]:
        s = self.sessao(token)
        if s is None:
            raise CredenciaisInvalidas("Sessão expirada; entre de novo.")
        with self.repo.leitura() as t:
            u = t.obter(T.Usuario, s["usuario_id"])
        if not senhas.conferir(atual or "", u["senha_hash"]):
            raise CredenciaisInvalidas("Senha atual incorreta.")
        senhas.validar_senha(nova, u["nome"])
        if nova == atual:
            raise Conflito("A nova senha deve ser diferente da atual.")
        with self.repo.escrita() as t:
            t.atualizar(T.Usuario, u["id"], senha_hash=senhas.gerar_hash(nova), atualizado_em=iso(self._agora()))
            t.s.execute(delete(T.Sessao).where(T.Sessao.usuario_id == u["id"], T.Sessao.id != _sha(token)))  # derruba as outras
            t.emitir_evento("auth.senha_trocada", iso(self._agora()), {"usuario_id": u["id"]})
        return {"ok": True}
