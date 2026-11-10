"""4.20b: Trello, Notion, Google Agenda, Gmail e ESCRITA com aprovacao por acao (Jira, GitHub, Trello).

Tudo com transporte simulado e dados ficticios: nenhum servico real e contatado."""

from __future__ import annotations

import json
from datetime import timedelta
from urllib.parse import parse_qs

import httpx
import pytest

from forja.adapters.sqlite import tabelas as T
from forja.dominio.erros import Conflito, ConflitoVersao, NaoEncontrado, ValidacaoDominio
from forja.ferramentas.catalogo import Catalogo
from forja.integracoes.conectores import Github, Jira, texto_de_escrita
from forja.integracoes.produtividade import Gmail, GoogleAgenda, Notion, Trello, _Google, _mascarar
from forja.integracoes.rede import MAX_CORPO, ClienteSeguro
from forja.orquestracao.acoes_externas import AcoesExternasServico
from forja.orquestracao.integracao_servico import IntegracaoServico
from forja.orquestracao.quadro_servico import QuadroServico
from tests.test_integracoes_rede import IP_PUBLICO, publico, transporte

QUADRO = "5f2b1c3d4e5f60718293a4b5"
LISTA = "6a7b8c9d0e1f20314253a4b5"
BASE = "0123456789abcdef0123456789abcdef"
ENV = {"FORJA_INT_TRELLO_KEY": "chave-ficticia", "FORJA_INT_TRELLO_TOKEN": "token-ficticio-trello-123456",
       "FORJA_INT_NOTION_TOKEN": "secret_ficticio_notion", "FORJA_INT_G_ID": "id-ficticio", "FORJA_INT_G_SEGREDO": "segredo-ficticio",
       "FORJA_INT_G_REFRESH": "refresh-ficticio", "FORJA_INT_JIRA_EMAIL": "pessoa@exemplo.com", "FORJA_INT_JIRA_TOKEN": "tok-jira-ficticio-123",
       "FORJA_INT_GITHUB_TOKEN": "ghp_ficticio"}


def _servico(repo, handler, relogio=None):
    t, visto = transporte(handler)
    return IntegracaoServico(repo, relogio=relogio, ler=ENV.get, resolver=publico, transporte=t), visto


def _salvar(s, id_, **cfg):
    return s.salvar(id_, {"ativo": True, **cfg}, s.estado(id_)["versao"])


CFG = {
    "trello": dict(variavel_usuario="FORJA_INT_TRELLO_KEY", variavel_token="FORJA_INT_TRELLO_TOKEN", itens_permitidos=[QUADRO.upper()]),
    "notion": dict(variavel_token="FORJA_INT_NOTION_TOKEN", itens_permitidos=["01234567-89ab-cdef-0123-456789abcdef"]),
    "google_agenda": dict(variavel_usuario="FORJA_INT_G_ID", variavel_segredo="FORJA_INT_G_SEGREDO", variavel_token="FORJA_INT_G_REFRESH",
                          itens_permitidos=["primary"]),
    "gmail": dict(variavel_usuario="FORJA_INT_G_ID", variavel_segredo="FORJA_INT_G_SEGREDO", variavel_token="FORJA_INT_G_REFRESH",
                  itens_permitidos=["INBOX"], limite_resultados=50),
    "jira": dict(base_url="https://jira.exemplo.com", versao_api="3", modo_auth="basic", variavel_usuario="FORJA_INT_JIRA_EMAIL",
                 variavel_token="FORJA_INT_JIRA_TOKEN", itens_permitidos=["ABC"]),
    "github": dict(base_url="https://api.github.com", variavel_token="FORJA_INT_GITHUB_TOKEN", itens_permitidos=["dono/repo"]),
}


@pytest.fixture(autouse=True)
def _limpar_cache_google():
    _Google._cache.clear()
    yield
    _Google._cache.clear()


# ------------------------------------------------------------------ configuracao
def test_conectores_normalizam_hosts_fixos_e_ids(repo):
    s, _ = _servico(repo, lambda r: httpx.Response(200, json={}))
    assert _salvar(s, "trello", **CFG["trello"])["configuracao"]["itens_permitidos"] == [QUADRO]
    e = _salvar(s, "notion", **CFG["notion"])
    assert e["configuracao"]["itens_permitidos"] == [BASE] and e["configuracao"]["host_permitido"] == "api.notion.com"
    assert _salvar(s, "gmail", **CFG["gmail"])["configuracao"]["limite_resultados"] == 10  # cada mensagem custa 1 chamada
    assert _salvar(s, "google_agenda", **CFG["google_agenda"])["pronta"]


@pytest.mark.parametrize("id_,ruim", [("trello", dict(itens_permitidos=["nao-e-id"])), ("trello", dict(variavel_token="")),
                                      ("notion", dict(itens_permitidos=["curto"])), ("gmail", dict(variavel_segredo="")),
                                      ("google_agenda", dict(itens_permitidos=["javascript:alert(1)"])),
                                      ("gmail", dict(variavel_token="FORJA_INT_X", variavel_segredo="segredo literal"))])
def test_configuracao_invalida_e_recusada(repo, id_, ruim):
    s, _ = _servico(repo, lambda r: httpx.Response(200, json={}))
    with pytest.raises(ValidacaoDominio):
        _salvar(s, id_, **{**CFG[id_], **ruim})


def test_escrita_nasce_desligada(repo):
    s, _ = _servico(repo, lambda r: httpx.Response(200, json={}))
    assert _salvar(s, "jira", **CFG["jira"])["configuracao"]["permitir_escrita"] is False


# ------------------------------------------------------------------ leitura
def test_trello_lista_cartoes_com_autorizacao_no_cabecalho_e_nao_na_url(repo):
    def h(req):
        if req.url.path.endswith("/lists"):
            return httpx.Response(200, json=[{"id": "L1", "name": "A fazer"}])
        return httpx.Response(200, json=[{"name": "Cartao 1", "idList": "L1", "due": "2026-12-01T00:00:00Z"}, {"name": "x", "closed": True}])

    s, visto = _servico(repo, h)
    _salvar(s, "trello", **CFG["trello"])
    r = s.executar("trello", "listar_cartoes", {"quadro": QUADRO})
    assert "[A fazer] Cartao 1 (prazo 2026-12-01)" in r.resumo and "x" not in r.resumo.split("\n")[-1]
    assert all("token" not in str(v.url) for v in visto) and 'oauth_token="token-ficticio-trello-123456"' in visto[0].headers["Authorization"]
    assert {v.headers["host"] for v in visto} == {"api.trello.com"} and str(visto[0].url).startswith(f"https://{IP_PUBLICO}")
    with pytest.raises(ValidacaoDominio):
        s.executar("trello", "listar_cartoes", {"quadro": "f" * 24})


def test_notion_consulta_por_post_so_bases_permitidas(repo):
    s, visto = _servico(repo, lambda r: httpx.Response(200, json={"results": [
        {"properties": {"Nome": {"type": "title", "title": [{"plain_text": "Plano Q1"}]}}, "last_edited_time": "2026-10-01T10:00:00Z"}]}))
    _salvar(s, "notion", **CFG["notion"])
    r = s.executar("notion", "consultar_base", {"base": "01234567-89ab-cdef-0123-456789abcdef"})
    assert "Plano Q1 (editada 2026-10-01)" in r.resumo and visto[0].method == "POST" and visto[0].headers["Notion-Version"]
    with pytest.raises(ValidacaoDominio):
        s.executar("notion", "consultar_base", {"base": "f" * 32})


def _google(req):
    if req.url.path == "/token":
        corpo = parse_qs(req.content.decode())
        assert corpo["grant_type"] == ["refresh_token"] and req.headers["content-type"] == "application/x-www-form-urlencoded"
        return httpx.Response(200, json={"access_token": "acesso-ficticio", "expires_in": 3600})
    assert req.headers["Authorization"] == "Bearer acesso-ficticio"
    if "/calendar/" in req.url.path:
        return httpx.Response(200, json={"items": [{"summary": "Reuniao", "start": {"dateTime": "2026-11-20T14:00:00Z"},
                                                    "attendees": [{"email": "terceiro@exemplo.com"}], "description": "SEGREDO-DA-PAUTA"}]})
    if req.url.path.endswith("/messages"):
        return httpx.Response(200, json={"messages": [{"id": "18c0ffee"}, {"id": "../../x"}]})
    return httpx.Response(200, json={"snippet": "Oi, segue o relatorio", "payload": {"headers": [
        {"name": "From", "value": "Ana Silva <ana.silva@exemplo.com>"}, {"name": "Subject", "value": "Relatorio"}, {"name": "Date", "value": "Mon, 9 Nov 2026"}]}})


def test_google_agenda_troca_refresh_token_uma_vez_e_omite_dados_de_terceiros(repo):
    s, visto = _servico(repo, _google)
    _salvar(s, "google_agenda", **CFG["google_agenda"])
    r = s.executar("google_agenda", "eventos", {"calendario": "primary", "de": "2026-11-01"})
    s.executar("google_agenda", "eventos", {})
    assert "2026-11-20T14:00 Reuniao" in r.resumo and "terceiro@" not in r.resumo and "SEGREDO-DA-PAUTA" not in r.resumo
    assert [v.url.path for v in visto].count("/token") == 1  # token de acesso em cache (memoria)
    assert {v.headers["host"] for v in visto} == {"oauth2.googleapis.com", "www.googleapis.com"}
    with pytest.raises(ValidacaoDominio):
        s.executar("google_agenda", "eventos", {"calendario": "outro@exemplo.com"})
    with pytest.raises(ValidacaoDominio):
        s.executar("google_agenda", "eventos", {"de": "amanha"})


def test_gmail_mascara_remetente_e_ignora_id_malicioso(repo):
    s, visto = _servico(repo, _google)
    _salvar(s, "gmail", **CFG["gmail"])
    r = s.executar("gmail", "listar", {"rotulo": "INBOX"})
    assert "Ana Silva <a***@exemplo.com>" in r.resumo and "ana.silva@" not in r.resumo and "1 mensagem" in r.resumo
    assert not any(".." in v.url.path for v in visto)
    with pytest.raises(ValidacaoDominio):
        s.executar("gmail", "listar", {"rotulo": "SPAM"})


def test_refresh_token_revogado_vira_erro_de_dominio(repo):
    s, _ = _servico(repo, lambda r: httpx.Response(200, json={"error": "invalid_grant"}) if r.url.path == "/token" else httpx.Response(200, json={}))
    _salvar(s, "gmail", **CFG["gmail"])
    with pytest.raises(ValidacaoDominio, match="token de acesso"):
        s.executar("gmail", "listar", {})


def test_mascarar():
    assert _mascarar("Bob <bob@x.com>") == "Bob <b***@x.com>" and _mascarar("sem email") == "sem email"


# ------------------------------------------------------------------ escrita: nunca pelo caminho de leitura
@pytest.mark.parametrize("id_,acao", [("jira", "comentar"), ("jira", "transicionar"), ("github", "comentar"), ("trello", "criar_cartao")])
def test_escrita_nao_pode_ser_chamada_pelo_caminho_de_leitura(repo, id_, acao):
    s, visto = _servico(repo, lambda r: httpx.Response(200, json={}))
    _salvar(s, id_, **CFG[id_], permitir_escrita=True)
    with pytest.raises(NaoEncontrado):
        s.executar(id_, acao, {})
    for interno in ("preparar_escrita", "escritas", "cliente"):
        with pytest.raises(NaoEncontrado):
            s.executar(id_, interno, {})
    assert visto == []


def test_escrita_desligada_na_integracao_e_recusada(repo):
    s, _ = _servico(repo, lambda r: httpx.Response(200, json={}))
    _salvar(s, "jira", **CFG["jira"])
    with pytest.raises(ValidacaoDominio, match="desligada"):
        s.preparar_escrita("jira", "comentar", {"chave": "ABC-1", "texto": "oi"})


@pytest.mark.parametrize("texto", ["api_key = 'sk-abcdefghijklmnopqrstuvwx0123456789'", "x" * 4001, "   "])
def test_conteudo_que_sairia_da_maquina_e_barrado(texto):
    with pytest.raises(ValidacaoDominio):
        texto_de_escrita(texto)


def test_preparar_escrita_valida_alvos_sem_rede():
    from forja.integracoes.config import ConfigIntegracao

    j = Jira().normalizar(ConfigIntegracao.model_validate({**CFG["jira"], "ativo": True}))
    assert Jira().preparar_escrita(j, "comentar", {"chave": "abc-7", "texto": "Feito"}) == ({"chave": "ABC-7", "texto": "Feito"},
                                                                                         "Posso comentar na issue ABC-7 do Jira: «Feito»?")
    with pytest.raises(ValidacaoDominio):
        Jira().preparar_escrita(j, "comentar", {"chave": "OPS-1", "texto": "x"})  # projeto nao permitido
    with pytest.raises(ValidacaoDominio):
        Jira().preparar_escrita(j, "apagar", {"chave": "ABC-1"})


def test_corpo_de_escrita_limitado():
    c = ClienteSeguro("https://api.github.com", resolver=publico, transporte=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    with pytest.raises(ValidacaoDominio):
        c.enviar("POST", "/x", {"body": "x" * (MAX_CORPO + 1)})
    with pytest.raises(ValidacaoDominio):
        c.enviar("DELETE", "/x", {})


# ------------------------------------------------------------------ fluxo de aprovacao
def _fluxo(repo, handler, relogio=None, **cfg_extra):
    s, visto = _servico(repo, handler, relogio)
    for id_ in ("jira", "github", "trello"):
        _salvar(s, id_, **CFG[id_], permitir_escrita=True, **cfg_extra)
    q = QuadroServico(repo)
    return AcoesExternasServico(repo, s, q, relogio), s, q, visto


def _jira_ok(req):
    if req.url.path.endswith("/transitions") and req.method == "GET":
        return httpx.Response(200, json={"transitions": [{"id": "31", "name": "Concluir", "to": {"name": "Concluida"}}]})
    return httpx.Response(201, json={"id": "10001"})


def test_proposta_nao_envia_nada_ate_aprovar_e_avisa_o_operador(repo):
    a, _s, q, visto = _fluxo(repo, _jira_ok)
    acao, nova = a.propor("jira", "comentar", {"chave": "ABC-1", "texto": "Corrigido na versao 2"}, "agente:kiro", dedup_key="k1")
    assert nova and acao["estado"] == "pendente" and visto == []
    assert acao["descricao"] == "Posso comentar na issue ABC-1 do Jira: «Corrigido na versao 2»?"
    aviso = [m for m in q.listar() if m["destino"] == "operador"]
    assert len(aviso) == 1 and acao["id"] in json.dumps(aviso[0]["payload"])
    assert a.propor("jira", "comentar", {"chave": "ABC-1", "texto": "outro"}, "agente:kiro", dedup_key="k1")[0]["id"] == acao["id"]


def test_aprovar_executa_uma_vez_com_adendo_registrado(repo):
    a, _s, _q, visto = _fluxo(repo, _jira_ok)
    acao, _ = a.propor("jira", "comentar", {"chave": "ABC-1", "texto": "Feito"})
    r = a.decidir(acao["id"], True, acao["versao"], "operador-local", "pode enviar, mas sem marcar ninguem")
    assert r["estado"] == "executada" and "comentario criado em ABC-1" in r["resultado"] and r["adendo"].startswith("pode enviar")
    corpo = json.loads(visto[-1].content)
    assert visto[-1].method == "POST" and corpo["body"]["content"][0]["content"][0]["text"] == "Feito"  # ADF no Jira Cloud
    with pytest.raises(Conflito):
        a.decidir(acao["id"], True, r["versao"])  # nao executa de novo
    assert sum(1 for v in visto if v.method == "POST") == 1


def test_negar_nao_executa_e_versao_antiga_conflita(repo):
    a, _s, _q, visto = _fluxo(repo, _jira_ok)
    acao, _ = a.propor("github", "comentar", {"repo": "dono/repo", "numero": 3, "texto": "Obrigado"})
    with pytest.raises(ConflitoVersao):
        a.decidir(acao["id"], True, acao["versao"] + 5)
    assert a.decidir(acao["id"], False, acao["versao"], adendo="nao agora")["estado"] == "negada" and visto == []


def test_transicao_resolve_pelo_nome_e_falha_explicando_opcoes(repo):
    a, _s, _q, visto = _fluxo(repo, _jira_ok)
    ok, _ = a.propor("jira", "transicionar", {"chave": "ABC-2", "para": "concluida"})
    assert ok["risco"] == "alto"
    assert a.decidir(ok["id"], True, 1)["estado"] == "executada" and json.loads(visto[-1].content) == {"transition": {"id": "31"}}
    ruim, _ = a.propor("jira", "transicionar", {"chave": "ABC-2", "para": "Arquivar"})
    r = a.decidir(ruim["id"], True, 1)
    assert r["estado"] == "falhou" and "Concluir" in r["resultado"]


def test_trello_so_cria_cartao_em_lista_de_quadro_permitido(repo):
    def h(req):
        if req.url.path.startswith("/1/lists/"):
            return httpx.Response(200, json={"idBoard": "f" * 24})  # lista de OUTRO quadro
        return httpx.Response(200, json={"id": "c1"})

    a, _s, _q, visto = _fluxo(repo, h)
    acao, _ = a.propor("trello", "criar_cartao", {"lista": LISTA, "nome": "Revisar PR"})
    r = a.decidir(acao["id"], True, 1)
    assert r["estado"] == "falhou" and not any(v.method == "POST" for v in visto)


def test_escrita_desligada_depois_da_proposta_nao_executa(repo):
    a, s, _q, visto = _fluxo(repo, _jira_ok)
    acao, _ = a.propor("jira", "comentar", {"chave": "ABC-1", "texto": "Feito"})
    cfg = s.estado("jira")
    s.salvar("jira", {**cfg["configuracao"], "permitir_escrita": False}, cfg["versao"])
    assert a.decidir(acao["id"], True, 1)["estado"] == "falhou" and visto == []  # revalida na execucao


def test_falha_de_rede_vira_falhou_sem_vazar_detalhes(repo):
    a, *_ = _fluxo(repo, lambda r: httpx.Response(500, text="stack trace interno com token=abc"))
    acao, _ = a.propor("github", "comentar", {"repo": "dono/repo", "numero": 1, "texto": "oi"})
    r = a.decidir(acao["id"], True, 1)
    assert r["estado"] == "falhou" and "token=abc" not in r["resultado"]


def test_propostas_expiram_e_reinicio_nao_repete_execucao(repo, relogio):
    a, *_ = _fluxo(repo, _jira_ok, relogio)
    velha, _ = a.propor("jira", "comentar", {"chave": "ABC-1", "texto": "a"})
    relogio.avancar(timedelta(hours=25).total_seconds())
    assert a.listar("expirada")[0]["id"] == velha["id"]
    with pytest.raises(Conflito):
        a.decidir(velha["id"], True, 2)
    nova, _ = a.propor("jira", "comentar", {"chave": "ABC-1", "texto": "b"})
    with repo.escrita() as t:
        t.atualizar(T.AcaoExterna, nova["id"], estado="executando")
    assert a.recuperar() == 1 and a.obter(nova["id"])["estado"] == "falhou"


def test_limite_de_pendentes(repo, monkeypatch):
    import forja.orquestracao.acoes_externas as m

    monkeypatch.setattr(m, "MAX_PENDENTES", 2)
    a, *_ = _fluxo(repo, _jira_ok)
    a.propor("jira", "comentar", {"chave": "ABC-1", "texto": "1"})
    a.propor("jira", "comentar", {"chave": "ABC-1", "texto": "2"})
    with pytest.raises(Conflito):
        a.propor("jira", "comentar", {"chave": "ABC-1", "texto": "3"})


# ------------------------------------------------------------------ catalogo / API
def test_ferramentas_de_proposta_so_aparecem_com_escrita_ligada_e_nunca_escrevem(repo):
    a, s, _q, visto = _fluxo(repo, _jira_ok)
    cat = Catalogo((), s, a)
    disp = {f["id"]: f["disponivel"] for f in cat.listar()}
    assert disp["jira.propor_comentario"] and disp["trello.listar_cartoes"] and not disp["gmail.listar"]
    r = cat.executar("jira.propor_comentario", {"chave": "ABC-9", "texto": "Pronto para revisao"})
    assert "Aguardando aprovacao" in r["resumo"] and visto == []
    cfg = s.estado("jira")
    s.salvar("jira", {**cfg["configuracao"], "permitir_escrita": False}, cfg["versao"])
    assert not {f["id"]: f["disponivel"] for f in cat.listar()}["jira.propor_comentario"]
    assert not {f["id"]: f["disponivel"] for f in Catalogo((), s, None).listar()}["github.propor_comentario"]


def test_api_lista_propoe_e_decide(client):
    r = client.post("/api/v1/acoes-externas", json={"integracao": "jira", "acao": "comentar", "parametros": {"chave": "ABC-1", "texto": "x"}})
    assert r.status_code == 422  # integracao nao configurada/desligada: nada e criado
    assert client.get("/api/v1/acoes-externas").json() == []
    assert client.get("/api/v1/acoes-externas", params={"estado": "invalido"}).status_code == 422
    assert client.post("/api/v1/acoes-externas/ACX-x/decidir", json={"aprovar": True, "expected_version": 1}).status_code == 404
    assert client.post("/api/v1/acoes-externas", json={"integracao": "jira", "acao": "comentar", "extra": 1}).status_code == 422


def test_github_comentar_envia_corpo_simples():
    from forja.integracoes.config import ConfigIntegracao

    c = Github().normalizar(ConfigIntegracao.model_validate({**CFG["github"], "ativo": True}))
    visto = []
    cli = ClienteSeguro("https://api.github.com", resolver=publico,
                        transporte=httpx.MockTransport(lambda r: (visto.append(r), httpx.Response(201, json={"id": 9}))[1]))
    assert "dono/repo#4" in Github().comentar(cli, c, "dono/repo", 4, "ok") and json.loads(visto[0].content) == {"body": "ok"}
    with pytest.raises(ValidacaoDominio):
        Github().comentar(cli, c, "outro/repo", 4, "ok")


def test_registro_de_conectores_inclui_novos():
    from forja.integracoes.catalogo_conectores import CONECTORES

    assert {"trello", "notion", "google_agenda", "gmail"} <= set(CONECTORES)
    assert isinstance(CONECTORES["gmail"], Gmail) and isinstance(CONECTORES["google_agenda"], GoogleAgenda)
    assert isinstance(CONECTORES["notion"], Notion) and isinstance(CONECTORES["trello"], Trello)
