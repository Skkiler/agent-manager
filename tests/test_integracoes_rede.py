"""Integracoes de rede (Jira, GitHub, agenda por URL): somente leitura, segredo so no ambiente, SSRF e allowlists."""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from forja.adapters.sqlite import tabelas as T
from forja.dominio.erros import ConflitoVersao, NaoEncontrado, ValidacaoDominio
from forja.integracoes import ambiente
from forja.integracoes.conectores import CONECTORES, Github, IcsUrl, Jira, _texto_adf
from forja.integracoes.config import ConfigIntegracao
from forja.integracoes.rede import ClienteSeguro, ErroRede, LimiteExcedido, RedeBloqueada, ip_publico, validar_base
from forja.orquestracao.integracao_servico import IntegracaoServico

IP_PUBLICO = "93.184.216.34"
TOKEN = "tok-secreto-do-teste-1234567890"
EMAIL = "pessoa@exemplo.com"
publico = lambda host, porta: [IP_PUBLICO]  # noqa: E731


def transporte(handler):
    visto: list[httpx.Request] = []

    def h(req: httpx.Request) -> httpx.Response:
        visto.append(req)
        return handler(req)

    return httpx.MockTransport(h), visto


def json_ok(corpo, status=200):
    return lambda req: httpx.Response(status, json=corpo)


# ---------------------------------------------------------------- ambiente (segredo so no ambiente)


def test_so_variaveis_com_prefixo_forja_int_sao_lidas(monkeypatch):
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "nao-pode-sair")
    monkeypatch.setenv("FORJA_INT_X_TOKEN", "valor")
    assert ambiente.ler("AWS_SECRET_ACCESS_KEY") is None and ambiente.ler("forja_int_x_token") is None
    assert ambiente.ler("FORJA_INT_X_TOKEN") == "valor" and ambiente.presente("FORJA_INT_X_TOKEN")
    assert not ambiente.nome_valido("FORJA_INT_") and not ambiente.nome_valido("FORJA_INT_A B")


def test_variavel_pode_vir_do_arquivo_env_e_o_processo_tem_prioridade(tmp_path, monkeypatch):
    arq = tmp_path / ".env"
    arq.write_text("FORJA_INT_A=do_arquivo\nFORJA_INT_B=arquivo_b\nOUTRA=x\n", encoding="utf-8")
    monkeypatch.delenv("FORJA_INT_A", raising=False)
    assert ambiente.ler("FORJA_INT_A", arq) == "do_arquivo"
    monkeypatch.setenv("FORJA_INT_A", "do_processo")
    assert ambiente.ler("FORJA_INT_A", arq) == "do_processo" and ambiente.ler("OUTRA", arq) is None
    assert ambiente.ler("FORJA_INT_NAO_EXISTE", tmp_path / "nao_existe.env") is None


# ---------------------------------------------------------------- configuracao nao aceita segredos


@pytest.mark.parametrize("campo,valor", [
    ("variavel_token", "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"),  # token colado no lugar do nome
    ("variavel_token", "ATATT3xFfGF0abcdef1234567890"),  # token cru de outro formato
    ("variavel_token", "AWS_SECRET_ACCESS_KEY"),  # variavel arbitraria (sem prefixo)
    ("variavel_usuario", "pessoa@exemplo.com"),
    ("itens_permitidos", ["Bearer abcdefghijklmnop"]),
])
def test_configuracao_recusa_segredo_ou_variavel_arbitraria(campo, valor):
    with pytest.raises(ValueError):
        ConfigIntegracao.model_validate({campo: valor})


def test_configuracao_nasce_desligada_e_proibe_campos_desconhecidos():
    assert ConfigIntegracao().ativo is False
    with pytest.raises(ValueError):
        ConfigIntegracao.model_validate({"token": "x"})


# ---------------------------------------------------------------- cliente seguro (SSRF, redirects, limites, vazamento)


@pytest.mark.parametrize("url", ["http://x.atlassian.net", "https://u:p@x.atlassian.net", "https://93.184.216.34",
                                 "https://x.atlassian.net?a=1", "https://x.atlassian.net#f", "ftp://x.com", "https://", ""])
def test_url_base_invalida_e_recusada(url):
    with pytest.raises(ValidacaoDominio):
        validar_base(url)


def test_url_base_valida_normaliza_host_porta_e_prefixo():
    assert validar_base("https://Jira.Exemplo.com:8443/jira/") == ("jira.exemplo.com", 8443, "/jira")


@pytest.mark.parametrize("ip,esperado", [
    ("93.184.216.34", True), ("8.8.8.8", True), ("127.0.0.1", False), ("10.1.2.3", False), ("172.16.0.1", False),
    ("192.168.0.10", False), ("169.254.169.254", False), ("100.64.0.1", False), ("0.0.0.0", False),  # noqa: S104 ("224.0.0.1", False),
    ("::1", False), ("fc00::1", False), ("fe80::1", False), ("::ffff:10.0.0.1", False), ("2606:4700:4700::1111", True)])
def test_ip_publico(ip, esperado):
    assert ip_publico(ip) is esperado


def cliente(handler, **kw):
    t, visto = transporte(handler)
    kw.setdefault("resolver", publico)
    return ClienteSeguro("https://jira.exemplo.com", transporte=t, **kw), visto


def test_conexao_fixa_o_ip_resolvido_e_valida_o_certificado_pelo_nome_do_host():
    c, visto = cliente(json_ok({"ok": 1}))
    c.get("/rest/api/3/myself", {"a": "b"})
    req = visto[0]
    assert req.url.host == IP_PUBLICO and req.url.path == "/rest/api/3/myself"  # IP fixado: DNS nao e consultado de novo
    assert req.headers["host"] == "jira.exemplo.com" and req.extensions["sni_hostname"] == "jira.exemplo.com"
    assert req.method == "GET" and req.url.scheme == "https"


def test_enderecos_nao_publicos_sao_bloqueados_inclusive_se_so_um_dos_registros_for_privado():
    for ips in (["127.0.0.1"], ["10.0.0.5"], ["169.254.169.254"], [IP_PUBLICO, "10.0.0.5"], ["::1"]):
        c, visto = cliente(json_ok({}), resolver=lambda h, p, ips=ips: ips)
        with pytest.raises(RedeBloqueada):
            c.get("/x")
        assert not visto  # nenhuma conexao foi aberta


def test_rede_privada_so_com_permissao_explicita():
    c, visto = cliente(json_ok({}), resolver=lambda h, p: ["10.0.0.5"], permitir_rede_privada=True)
    c.get("/x")
    assert visto[0].url.host == "10.0.0.5"


def test_dns_sem_resposta_falha_sem_conectar():
    c, visto = cliente(json_ok({}), resolver=lambda h, p: [])
    with pytest.raises(ErroRede):
        c.get("/x")
    assert not visto


def test_redirecionamento_nao_e_seguido_nem_expoe_o_destino():
    c, visto = cliente(lambda req: httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/meta-data"}))
    with pytest.raises(ErroRede) as e:
        c.get("/x")
    assert len(visto) == 1 and "169.254" not in e.value.mensagem


@pytest.mark.parametrize("status,tipo", [(401, ErroRede), (403, ErroRede), (404, ErroRede), (429, LimiteExcedido), (500, ErroRede), (503, ErroRede)])
def test_status_http_viram_erros_de_dominio_sem_vazar_o_corpo(status, tipo):
    c, _ = cliente(lambda req: httpx.Response(status, text=f"corpo com {TOKEN} e dados internos"))
    with pytest.raises(tipo) as e:
        c.get("/x")
    assert TOKEN not in e.value.mensagem and "dados internos" not in e.value.mensagem
    assert ("credencial" in e.value.mensagem) is (status in (401, 403))  # o operador precisa saber que o problema e a credencial


def test_resposta_acima_do_limite_e_abortada():
    c, _ = cliente(lambda req: httpx.Response(200, content=b"x" * 5000), max_bytes=1000)
    with pytest.raises(ErroRede, match="limite"):
        c.get("/x")


@pytest.mark.parametrize("excecao", [httpx.ConnectError("falha em 10.0.0.9"), httpx.ReadTimeout("lento"), httpx.ConnectTimeout("lento"),
                                    httpx.RemoteProtocolError("quebrou")])
def test_falhas_de_transporte_viram_erro_generico_sem_detalhes(excecao):
    def h(req):
        raise excecao

    c, _ = cliente(h)
    with pytest.raises(ErroRede) as e:
        c.get("/x")
    assert "10.0.0.9" not in e.value.mensagem and "jira.exemplo.com" not in e.value.mensagem


@pytest.mark.parametrize("caminho", ["rest/api", "//evil.com/x", "/a/../b", "/a\\b", "http://evil.com/x"])
def test_caminho_malicioso_e_recusado(caminho):
    c, visto = cliente(json_ok({}))
    with pytest.raises(ValidacaoDominio):
        c.get(caminho)
    assert not visto


def test_so_o_host_configurado_e_alcancavel_e_o_cabecalho_e_pedido_a_cada_chamada():
    chamadas = []
    c, visto = cliente(json_ok({}), cabecalhos=lambda: chamadas.append(1) or {"Authorization": f"Bearer {TOKEN}"})
    c.get("/a")
    c.get("/b")
    assert len(chamadas) == 2 and {r.headers["host"] for r in visto} == {"jira.exemplo.com"}
    assert visto[0].headers["authorization"] == f"Bearer {TOKEN}"


def test_query_na_url_e_params_juntos_sao_recusados():
    c, _ = cliente(json_ok({}))
    with pytest.raises(ValidacaoDominio):
        c.get("/x?a=1", {"b": 2})


def test_json_invalido_vira_erro_de_dominio():
    c, _ = cliente(lambda req: httpx.Response(200, text="<html>login</html>"))
    with pytest.raises(ErroRede):
        c.get("/x").json()


# ---------------------------------------------------------------- Jira


def cfg_jira(**kw) -> ConfigIntegracao:
    base = dict(ativo=True, base_url="https://jira.exemplo.com", versao_api="3", modo_auth="basic", variavel_usuario="FORJA_INT_JIRA_EMAIL",
                variavel_token="FORJA_INT_JIRA_TOKEN", itens_permitidos=["abc", "OPS"], limite_resultados=5)
    base.update(kw)
    return Jira().normalizar(ConfigIntegracao.model_validate(base))


ENV = {"FORJA_INT_JIRA_EMAIL": EMAIL, "FORJA_INT_JIRA_TOKEN": TOKEN}
jira_cliente = lambda cfg, handler, **kw: (lambda t, v: (Jira().cliente(cfg, ler=ENV.get, resolver=publico, transporte=t), v))(*transporte(handler))  # noqa: E731


def issue(chave, resumo="Resumo", status="Aberta", quem="Ana"):
    return {"key": chave, "fields": {"summary": resumo, "status": {"name": status}, "assignee": {"displayName": quem} if quem else None,
                                     "priority": {"name": "Alta"}, "issuetype": {"name": "Bug"}}}


def test_jira_normaliza_chaves_e_exige_projeto_e_variaveis():
    assert cfg_jira().itens_permitidos == ["ABC", "OPS"] and cfg_jira().host_permitido == "jira.exemplo.com"
    for ruim in (dict(itens_permitidos=[]), dict(itens_permitidos=["abc def"]), dict(variavel_token=""), dict(variavel_usuario=""),
                 dict(versao_api=""), dict(base_url="http://jira.exemplo.com")):
        with pytest.raises(ValidacaoDominio):
            cfg_jira(**ruim)
    assert cfg_jira(modo_auth="bearer", variavel_usuario="").modo_auth == "bearer"  # PAT nao precisa de e-mail


def test_jira_cloud_usa_o_endpoint_novo_e_restringe_o_jql_aos_projetos_permitidos():
    cfg = cfg_jira()
    c, visto = jira_cliente(cfg, json_ok({"issues": [issue("ABC-1")]}))
    Jira().buscar(c, cfg, "status = Open ORDER BY created DESC", limite=50)
    req = visto[0]
    assert req.url.path == "/rest/api/3/search/jql"
    p = dict(req.url.params)
    assert p["jql"] == "project in (ABC, OPS) AND (status = Open) ORDER BY created DESC"
    assert p["maxResults"] == "5"  # teto da integracao vence o pedido do agente
    assert "summary" in p["fields"] and "description" not in p["fields"]


def test_jira_server_usa_api_2_e_jql_vazio_vira_so_a_restricao():
    cfg = cfg_jira(versao_api="2", modo_auth="bearer")
    c, visto = jira_cliente(cfg, json_ok({"issues": []}))
    Jira().buscar(c, cfg, "")
    assert visto[0].url.path == "/rest/api/2/search" and dict(visto[0].url.params)["jql"] == "project in (ABC, OPS)"


def test_jql_malicioso_nao_escapa_da_restricao_de_projetos():
    cfg = cfg_jira()
    jql = Jira()._jql(cfg, "project = SECRETO OR 1=1")
    assert jql == "project in (ABC, OPS) AND (project = SECRETO OR 1=1)"  # o OR fica DENTRO dos parenteses
    assert Jira()._jql(cfg, "ORDER BY updated") == "project in (ABC, OPS) ORDER BY updated"


def test_resultados_de_projeto_nao_permitido_sao_descartados_mesmo_que_o_servidor_os_devolva():
    cfg = cfg_jira()
    c, _ = jira_cliente(cfg, json_ok({"issues": [issue("ABC-1"), issue("SECRETO-9", "dado interno"), {"key": "../x", "fields": {}}]}))
    r = Jira().buscar(c, cfg, "")
    assert "ABC-1" in r.resumo and "SECRETO" not in r.resumo + str(r.dados) and "dado interno" not in r.resumo
    assert r.dados["issues"] == ["ABC-1"] and any("NAO confiavel" in a for a in r.avisos)


def test_jira_obter_bloqueia_projeto_nao_permitido_antes_de_qualquer_chamada():
    cfg = cfg_jira()
    c, visto = jira_cliente(cfg, json_ok(issue("XYZ-1")))
    for chave in ("XYZ-1", "xyz-1", "ABC", "ABC-1/../../x", "ABC-1; DROP"):
        with pytest.raises(ValidacaoDominio):
            Jira().obter(c, cfg, chave)
    assert not visto


def test_jira_obter_achata_adf_comentarios_e_limita_tamanho():
    cfg = cfg_jira()
    adf = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Falha ao entrar."}]},
                                      {"type": "paragraph", "content": [{"type": "text", "text": " Passos: " + "x" * 3000}]}]}
    corpo = issue("ABC-7") | {}
    corpo["fields"]["description"] = adf
    corpo["fields"]["labels"] = ["urgente"]
    corpo["fields"]["comment"] = {"comments": [{"author": {"displayName": f"u{i}"}, "body": f"coment {i}"} for i in range(6)]}
    c, visto = jira_cliente(cfg, json_ok(corpo))
    r = Jira().obter(c, cfg, "abc-7")
    assert visto[0].url.path == "/rest/api/3/issue/ABC-7"
    assert "Falha ao entrar." in r.resumo and len(r.resumo) < 2600
    assert "coment 5" in r.resumo and "coment 2" not in r.resumo  # so os 3 ultimos
    assert "urgente" in r.resumo


def test_adf_vazio_ou_invalido_nao_quebra():
    assert _texto_adf(None) == "" and _texto_adf({"type": "doc"}) == "" and _texto_adf("texto solto") == ""


def test_jira_autenticacao_basic_e_bearer_e_o_segredo_nunca_aparece_na_saida():
    cfg = cfg_jira()
    c, visto = jira_cliente(cfg, json_ok({"issues": [issue("ABC-1")]}))
    r = Jira().buscar(c, cfg, "")
    esperado = "Basic " + base64.b64encode(f"{EMAIL}:{TOKEN}".encode()).decode()
    assert visto[0].headers["authorization"] == esperado
    saida = r.resumo + json.dumps(r.dados) + json.dumps(r.avisos)
    assert TOKEN not in saida and EMAIL not in saida
    cfg2 = cfg_jira(modo_auth="bearer", variavel_usuario="")
    c2, v2 = jira_cliente(cfg2, json_ok({"issues": []}))
    Jira().buscar(c2, cfg2, "")
    assert v2[0].headers["authorization"] == f"Bearer {TOKEN}"


def test_jira_projetos_filtra_pela_lista_permitida():
    cfg = cfg_jira()
    c, _ = jira_cliente(cfg, json_ok({"values": [{"key": "ABC", "name": "Alfa"}, {"key": "ZZZ", "name": "Outro"}]}))
    r = Jira().projetos(c, cfg)
    assert r.dados["projetos"] == ["ABC"] and "ZZZ" not in r.resumo


def test_ausencia_da_variavel_impede_o_cabecalho():
    cfg = cfg_jira()
    with pytest.raises(ValidacaoDominio, match="ausente"):
        Jira().cabecalhos(cfg, ler={}.get)


# ---------------------------------------------------------------- GitHub


def cfg_gh(**kw):
    base = dict(ativo=True, base_url="https://api.github.com", itens_permitidos=["dono/repo"], limite_resultados=3)
    base.update(kw)
    return Github().normalizar(ConfigIntegracao.model_validate(base))


def test_github_lista_issues_so_de_repositorios_permitidos_e_funciona_sem_token():
    cfg = cfg_gh()
    t, visto = transporte(json_ok([{"number": 1, "state": "open", "title": "Bug", "user": {"login": "ana"}},
                                   {"number": 2, "state": "open", "title": "PR", "user": {"login": "bia"}, "pull_request": {}}]))
    c = Github().cliente(cfg, ler={}.get, resolver=publico, transporte=t)
    r = Github().listar_issues(c, cfg, "dono/repo", "open", 50)
    assert "authorization" not in visto[0].headers and visto[0].url.path == "/repos/dono/repo/issues"
    assert dict(visto[0].url.params) == {"state": "open", "per_page": "3"} and "PR: PR" in r.resumo
    for ruim in ("outro/repo", "dono/repo/../x"):
        with pytest.raises(ValidacaoDominio):
            Github().listar_issues(c, cfg, ruim)
    with pytest.raises(ValidacaoDominio):
        Github().listar_issues(c, cfg, "dono/repo", "qualquer")
    assert len(visto) == 1


def test_github_com_token_usa_bearer_e_obtem_issue():
    cfg = cfg_gh(variavel_token="FORJA_INT_GH")
    t, visto = transporte(json_ok({"number": 5, "state": "open", "title": "T", "user": {"login": "x"}, "labels": [{"name": "bug"}],
                                   "comments": 2, "body": "texto " * 500}))
    c = Github().cliente(cfg, ler={"FORJA_INT_GH": TOKEN}.get, resolver=publico, transporte=t)
    r = Github().obter_issue(c, cfg, "dono/repo", 5)
    assert visto[0].headers["authorization"] == f"Bearer {TOKEN}" and TOKEN not in r.resumo and "bug" in r.resumo
    with pytest.raises(ValidacaoDominio):
        Github().cabecalhos(cfg, ler={}.get)  # token configurado mas ausente: falha em vez de ir anonimo


def test_github_exige_repositorio_valido():
    for ruim in ([], ["so-nome"], ["a/b/c"], ["a b/c"]):
        with pytest.raises(ValidacaoDominio):
            cfg_gh(itens_permitidos=ruim)


# ---------------------------------------------------------------- agenda por URL secreta


ICS = "BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:Reuniao\nDTSTART:20261201T100000\nEND:VEVENT\nEND:VCALENDAR\n"
URL_SECRETA = "https://calendar.google.com/calendar/ical/pessoa/private-SEGREDO123/basic.ics"


def cfg_ics(**kw):
    base = dict(ativo=True, variavel_url="FORJA_INT_AGENDA", host_permitido="Calendar.Google.com")
    base.update(kw)
    return IcsUrl().normalizar(ConfigIntegracao.model_validate(base))


def test_agenda_por_url_le_o_endereco_do_ambiente_e_nunca_o_devolve():
    cfg = cfg_ics()
    t, visto = transporte(lambda req: httpx.Response(200, text=ICS))
    ler = {"FORJA_INT_AGENDA": URL_SECRETA}.get
    c = IcsUrl().cliente(cfg, ler=ler, resolver=publico, transporte=t)
    r = IcsUrl().eventos(c, cfg)
    assert visto[0].url.path.endswith("/basic.ics") and "SEGREDO123" in visto[0].url.path
    assert "Reuniao" in r.resumo and "SEGREDO123" not in r.resumo + str(r.dados) and r.ferramenta == "agenda.ler_ics_url"
    IcsUrl().testar(c, cfg)
    with pytest.raises(ValidacaoDominio, match="calendario"):
        IcsUrl().testar(IcsUrl().cliente(cfg, ler=ler, resolver=publico, transporte=transporte(lambda req: httpx.Response(200, text="<html>"))[0]), cfg)


def test_agenda_por_url_recusa_servidor_diferente_do_permitido_e_variavel_ausente():
    cfg = cfg_ics()
    with pytest.raises(ValidacaoDominio, match="servidor permitido"):
        IcsUrl().cliente(cfg, ler={"FORJA_INT_AGENDA": "https://evil.com/x.ics"}.get)
    with pytest.raises(ValidacaoDominio, match="ausente"):
        IcsUrl().cliente(cfg, ler={}.get)
    with pytest.raises(ValidacaoDominio):
        cfg_ics(host_permitido="localhost")


# ---------------------------------------------------------------- servico: estado, prontidao, limites, auditoria


@pytest.fixture
def env():
    return {}


@pytest.fixture
def svc(repo, relogio, env):
    t, visto = transporte(json_ok({"issues": [issue("ABC-1")]}))
    s = IntegracaoServico(repo, relogio, ler=env.get, resolver=publico, transporte=t, agora=lambda: relogio.agora().timestamp())
    s.visto = visto  # type: ignore[attr-defined]
    return s


CFG_JIRA = dict(ativo=True, base_url="https://jira.exemplo.com", versao_api="3", modo_auth="basic", variavel_usuario="FORJA_INT_JIRA_EMAIL",
                variavel_token="FORJA_INT_JIRA_TOKEN", itens_permitidos=["ABC"], limite_por_minuto=3)


def test_tudo_nasce_desligado_e_nao_configurado(svc):
    for id_ in CONECTORES:
        e = svc.estado(id_)
        assert e["pronta"] is False and e["motivo"] == "desligada" and e["versao"] == 0 and e["variaveis"] == {}
        assert not svc.pronta(id_)
    with pytest.raises(NaoEncontrado):
        svc.estado("nao_existe")


def test_prontidao_exige_ativar_configurar_e_ter_as_variaveis_no_ambiente(svc, env):
    e = svc.salvar("jira", CFG_JIRA, 0)
    assert not e["pronta"] and "faltam variaveis" in e["motivo"] and e["variaveis"] == {
        "FORJA_INT_JIRA_TOKEN": False, "FORJA_INT_JIRA_EMAIL": False}
    env.update(ENV)
    e = svc.estado("jira")
    assert e["pronta"] and e["motivo"] == "pronta" and set(e["variaveis"].values()) == {True}
    desligada = svc.salvar("jira", {**CFG_JIRA, "ativo": False}, e["versao"])
    assert not desligada["pronta"] and desligada["motivo"] == "desligada"


def test_estado_e_banco_nunca_contem_o_valor_do_segredo(svc, env, repo):
    env.update(ENV)
    svc.salvar("jira", CFG_JIRA, 0)
    texto = json.dumps(svc.estado("jira"))
    with repo.leitura() as t:
        guardado = json.dumps(t.obter(T.Configuracao, "integracao.jira"))
    assert TOKEN not in texto + guardado and EMAIL not in texto + guardado
    assert "FORJA_INT_JIRA_TOKEN" in guardado  # so o NOME


def test_salvar_exige_a_versao_atual_e_valida_a_configuracao(svc):
    svc.salvar("jira", CFG_JIRA, 0)
    with pytest.raises(ConflitoVersao):
        svc.salvar("jira", CFG_JIRA, 0)
    with pytest.raises(ValidacaoDominio, match="variavel_token"):
        svc.salvar("jira", {**CFG_JIRA, "variavel_token": TOKEN}, 1)  # token colado no campo errado
    with pytest.raises(ValidacaoDominio):
        svc.salvar("jira", {**CFG_JIRA, "campo_extra": 1}, 1)
    with pytest.raises(NaoEncontrado):
        svc.salvar("gmail_api", {}, 0)


def test_executar_so_com_integracao_pronta_e_acao_valida(svc, env):
    with pytest.raises(ValidacaoDominio, match="indisponivel"):
        svc.executar("jira", "buscar", {"jql": ""})
    svc.salvar("jira", CFG_JIRA, 0)
    env.update(ENV)
    assert "ABC-1" in svc.executar("jira", "buscar", {"jql": ""}).resumo
    for acao in ("cliente", "testar", "normalizar", "_jql", "nao_existe", "cabecalhos"):
        with pytest.raises(NaoEncontrado):
            svc.executar("jira", acao, {})


def test_limite_de_chamadas_por_minuto_protege_contra_laco_de_agente(svc, env, relogio):
    svc.salvar("jira", CFG_JIRA, 0)
    env.update(ENV)
    for _ in range(3):
        svc.executar("jira", "buscar", {"jql": ""})
    with pytest.raises(LimiteExcedido):
        svc.executar("jira", "buscar", {"jql": ""})
    relogio.avancar(61)
    svc.executar("jira", "buscar", {"jql": ""})  # janela deslizante liberou


def test_auditoria_registra_so_metadados_nunca_parametros_ou_conteudo(svc, env, repo):
    svc.salvar("jira", CFG_JIRA, 0)
    env.update(ENV)
    svc.executar("jira", "buscar", {"jql": "text ~ 'dado confidencial'"})
    with repo.leitura() as t:
        eventos = [e for e in t.eventos_apos(0) if e["tipo"] == "integracao.chamada"]
    assert len(eventos) == 1 and set(eventos[0]["payload"]) == {"integracao", "acao", "ok", "ms"}
    assert "confidencial" not in json.dumps(eventos) and TOKEN not in json.dumps(eventos)


def test_falha_na_chamada_tambem_e_auditada(repo, relogio, env):
    t, _ = transporte(lambda req: httpx.Response(500))
    s = IntegracaoServico(repo, relogio, ler=env.get, resolver=publico, transporte=t)
    s.salvar("jira", CFG_JIRA, 0)
    env.update(ENV)
    with pytest.raises(ErroRede):
        s.executar("jira", "buscar", {"jql": ""})
    with repo.leitura() as tx:
        assert [e["payload"]["ok"] for e in tx.eventos_apos(0) if e["tipo"] == "integracao.chamada"] == [False]


def test_testar_conexao_devolve_ok_ou_motivo_sem_conteudo(repo, relogio, env):
    resposta = {"status": 200}
    t, visto = transporte(lambda req: httpx.Response(resposta["status"], json={"displayName": "Pessoa Secreta"}))
    s = IntegracaoServico(repo, relogio, ler=env.get, resolver=publico, transporte=t)
    s.salvar("jira", CFG_JIRA, 0)
    env.update(ENV)
    ok = s.testar("jira")
    assert ok["ok"] and visto[0].url.path == "/rest/api/3/myself" and "Pessoa" not in json.dumps(ok)
    resposta["status"] = 401
    ruim = s.testar("jira")
    assert not ruim["ok"] and ruim["codigo"] == "erro_rede" and TOKEN not in json.dumps(ruim)


def test_testar_relata_bloqueio_de_rede_privada(repo, relogio, env):
    s = IntegracaoServico(repo, relogio, ler=env.get, resolver=lambda h, p: ["10.0.0.9"], transporte=transporte(json_ok({}))[0])
    s.salvar("jira", CFG_JIRA, 0)
    env.update(ENV)
    r = s.testar("jira")
    assert not r["ok"] and r["codigo"] == "rede_bloqueada"
    s.salvar("jira", {**CFG_JIRA, "permitir_rede_privada": True}, 1)
    assert s.testar("jira")["ok"]


# ---------------------------------------------------------------- catalogo e API ponta a ponta

import shutil  # noqa: E402
from collections.abc import Iterator  # noqa: E402
from pathlib import Path  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from forja.adapters.agentes_mock.mock import AgenteMock  # noqa: E402
from forja.config import Configuracoes  # noqa: E402
from forja.servidor.app import criar_app  # noqa: E402

API_TOKEN = "token-de-teste-com-tamanho-suficiente"


@pytest.fixture
def cli(tmp_path: Path, _db_migrado: Path, env) -> Iterator[TestClient]:
    (tmp_path / "data").mkdir()
    shutil.copyfile(_db_migrado, tmp_path / "data" / "forja.sqlite3")
    cfg = Configuracoes(_env_file=None, app_data_dir=tmp_path / "data", app_log_dir=tmp_path / "logs",  # type: ignore[call-arg]
                        app_api_token=API_TOKEN, app_allowed_hosts="testserver")
    with TestClient(criar_app(cfg, AgenteMock()), headers={"Authorization": f"Bearer {API_TOKEN}"}) as c:
        t, _ = transporte(json_ok({"issues": [issue("ABC-1", "Falha no login")]}))
        svc = IntegracaoServico(c.app.state.servico.repo, ler=env.get, resolver=publico, transporte=t)
        c.app.state.integracoes = svc
        c.app.state.ferramentas.integracoes = svc
        yield c


def put(cli, id_, cfg, versao):
    return cli.put(f"/api/v1/integracoes/{id_}/configuracao", json={"expected_version": versao, "configuracao": cfg})


def test_api_registro_mostra_rede_desligada_e_nunca_segredos(cli, env):
    env.update(ENV)
    por = {c["id"]: c for c in cli.get("/api/v1/integracoes").json()}
    jira = por["jira"]
    assert jira["modo"] == "rede" and jira["configuravel"] and not jira["disponivel"] and jira["rede_estado"]["motivo"] == "desligada"
    assert {c["id"] for c in jira["rede_estado"]["campos"]} >= {"base_url", "variavel_token", "itens_permitidos"}
    assert por["email_mbox"]["rede_estado"] is None and por["gmail_api"]["estado"] == "planejado"
    assert TOKEN not in json.dumps(por) and EMAIL not in json.dumps(por)


def test_api_configurar_ativar_e_usar_a_ferramenta_ponta_a_ponta(cli, env):
    ferr = lambda: {f["id"]: f for f in cli.get("/api/v1/ferramentas").json()}  # noqa: E731
    assert not ferr()["jira.buscar"]["disponivel"]
    antes = cli.post("/api/v1/ferramentas/jira.buscar/executar", json={"entrada": {}})
    assert antes.status_code == 422 and "desligada" in antes.json()["mensagem"]

    r = put(cli, "jira", CFG_JIRA, 0)
    assert r.status_code == 200 and not r.json()["pronta"] and "faltam variaveis" in r.json()["motivo"]
    assert not ferr()["jira.buscar"]["disponivel"]  # configurada, mas sem token no ambiente

    env.update(ENV)  # o operador coloca o token no .env/ambiente
    assert cli.get("/api/v1/integracoes/jira").json()["pronta"] and ferr()["jira.buscar"]["disponivel"]
    assert cli.post("/api/v1/integracoes/jira/testar").json()["ok"] is True
    saida = cli.post("/api/v1/ferramentas/jira.buscar/executar", json={"entrada": {"jql": "status = Open"}}).json()
    assert "ABC-1" in saida["resumo"] and "Falha no login" in saida["resumo"] and saida["conteudo_nao_confiavel"]
    assert TOKEN not in json.dumps(saida) and saida["tokens_resumo"] < saida["tokens_origem"]

    bloqueada = cli.post("/api/v1/ferramentas/jira.obter_issue/executar", json={"entrada": {"chave": "OUTRO-1"}})
    assert bloqueada.status_code == 422 and "permitidos" in bloqueada.json()["mensagem"]


def test_api_recusa_token_no_campo_errado_e_trata_conflito_e_ids_invalidos(cli):
    ruim = put(cli, "jira", {**CFG_JIRA, "variavel_token": TOKEN}, 0)
    assert ruim.status_code == 422 and TOKEN not in ruim.text
    assert put(cli, "jira", {**CFG_JIRA, "base_url": "http://inseguro.exemplo.com"}, 0).status_code == 422
    assert put(cli, "jira", CFG_JIRA, 0).status_code == 200
    assert put(cli, "jira", CFG_JIRA, 0).status_code == 409
    assert put(cli, "gmail_api", {}, 0).status_code == 404
    assert cli.get("/api/v1/integracoes/..%2Fx").status_code in (404, 422)
    assert cli.put("/api/v1/integracoes/jira/configuracao", json={"configuracao": {}}).status_code == 422


def test_api_testar_integracao_desligada_e_422_e_exige_autenticacao(cli):
    assert cli.post("/api/v1/integracoes/jira/testar").status_code == 422
    sem = TestClient(cli.app, headers={"Host": "testserver"})
    for chamada in (sem.get("/api/v1/integracoes"), sem.get("/api/v1/integracoes/jira"), sem.post("/api/v1/integracoes/jira/testar"),
                    sem.put("/api/v1/integracoes/jira/configuracao", json={})):
        assert chamada.status_code in (401, 403)