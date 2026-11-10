"""Menu de configuracoes: registro (toda opcao e explicada), validacao, aplicacao imediata, politica de pastas e limite de requisicoes."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from forja.adapters.agentes_mock.mock import AgenteMock
from forja.adapters.sqlite import tabelas as T
from forja.config import Configuracoes
from forja.dominio.erros import ConflitoVersao, ValidacaoDominio
from forja.ferramentas.catalogo import Catalogo
from forja.preferencias.registro import CATEGORIAS, EDITAVEIS, POR_ID, PREFERENCIAS
from forja.preferencias.servico import PreferenciasServico, validar_valor
from forja.seguranca.pastas import PoliticaPastas, aplicar, definir_protegidas, proibido, protegido, validar_pasta
from forja.servidor.app import criar_app

TOKEN = "token-de-teste-com-tamanho-suficiente"


@pytest.fixture(autouse=True)
def _sem_protegidas_residuais():
    definir_protegidas([])
    yield
    definir_protegidas([])


# ---------------------------------------------------------------- registro: tudo explicado, nada exagerado


def test_toda_opcao_tem_explicacao_categoria_e_nivel_validos():
    ids = [p.id for p in PREFERENCIAS]
    assert len(ids) == len(set(ids))
    categorias = {c.id for c in CATEGORIAS}
    for p in PREFERENCIAS:
        assert p.categoria in categorias and p.nivel in ("geral", "avancado") and p.risco in ("baixo", "medio", "alto"), p.id
        assert len(p.explicacao) >= 40, f"{p.id}: explicacao curta demais"


def test_opcoes_editaveis_explicam_consequencias_e_numericas_dao_baixo_medio_alto():
    for p in PREFERENCIAS:
        if p.persistida and p.tipo in ("bool", "int", "pastas"):
            assert p.se_ligar and p.se_desligar, f"{p.id}: falta explicar o que muda ao ligar/desligar"
        if p.tipo == "int":
            assert len(p.exemplos) >= 3, f"{p.id}: dar exemplos baixo/medio/alto"
            assert all(p.minimo <= e.valor <= p.maximo for e in p.exemplos) and p.minimo <= p.padrao <= p.maximo
            assert [e.valor for e in p.exemplos] == sorted(e.valor for e in p.exemplos)
        if p.tipo == "selecao":
            assert p.padrao in {v for v, _ in p.opcoes} and len(p.exemplos) == len(p.opcoes)


def test_padroes_do_registro_sao_validos_e_seguros():
    for p in PREFERENCIAS:
        if p.persistida and p.tipo in ("bool", "int", "selecao"):
            assert validar_valor(p, p.padrao) == p.padrao, p.id
    assert POR_ID["ferramentas_arquivos_ativas"].padrao is False and POR_ID["ferramentas_arquivos_ativas"].risco == "alto"
    assert POR_ID["pastas_permitidas"].padrao == [] and POR_ID["mascarar_enderecos_email"].padrao is True
    assert POR_ID["contar_estaticos_no_limite"].padrao is False


def test_nao_ha_excesso_de_opcoes_gerais_e_nenhuma_opcao_guarda_segredo():
    for c in CATEGORIAS:
        gerais = [p for p in PREFERENCIAS if p.categoria == c.id and p.nivel == "geral"]
        assert 1 <= len(gerais) <= 4, f"{c.id}: {len(gerais)} opcoes gerais"
    proibidas = {"token", "secret", "senha", "password", "chave", "credencial"}  # palavra inteira: "tokens" de IA nao e credencial
    assert not [p.id for p in PREFERENCIAS if proibidas & set(p.id.split("_"))]


# ---------------------------------------------------------------- servico


@pytest.fixture
def prefs(repo, relogio) -> PreferenciasServico:
    return PreferenciasServico(repo, relogio)


def estado(prefs):
    return {i["id"]: i for c in prefs.estado()["categorias"] for i in c["itens"]}


def test_estado_traz_padroes_fonte_e_metadados_completos(prefs):
    e = estado(prefs)
    assert prefs.estado()["versao"] == 0 and e["nivel_detalhe"]["valor"] == "simples" and e["nivel_detalhe"]["fonte"] == "padrao"
    item = e["contexto_orcamento_tokens"]
    assert item["nivel"] == "avancado" and [x["valor"] for x in item["exemplos"]] == [500, 2000, 6000] and item["unidade"] == "tokens"
    assert e["modelos"]["valor"] is None and e["modelos"]["fonte"] is None  # nao persistida aqui


def test_atualizar_valida_persiste_incrementa_versao_e_sobrevive_a_reinicio(prefs, repo, relogio):
    r = prefs.atualizar({"tema": "escuro", "contexto_orcamento_tokens": 3000}, 0)
    assert r["versao"] == 1 and estado(prefs)["tema"]["fonte"] == "usuario" and estado(prefs)["oficina_pixel"]["fonte"] == "padrao"
    novo = PreferenciasServico(repo, relogio)  # "reinicio": le do banco
    assert novo.valor("tema") == "escuro" and novo.valor("contexto_orcamento_tokens") == 3000


@pytest.mark.parametrize("ruim", [
    {"tema": "roxo"}, {"oficina_pixel": "sim"}, {"oficina_pixel": 1}, {"contexto_orcamento_tokens": 50}, {"contexto_orcamento_tokens": 999999},
    {"contexto_orcamento_tokens": True}, {"contexto_orcamento_tokens": 2000.5}, {"limite_requisicoes_por_minuto": 5},
    {"inexistente": 1}, {"modelos": {"x": 1}}, {"protecoes_fixas": "x"}, {"pastas_permitidas": "C:\\x"}, {},
])
def test_valores_invalidos_sao_recusados_com_mensagem(prefs, ruim):
    with pytest.raises(ValidacaoDominio):
        prefs.atualizar(ruim, 0)
    assert prefs.estado()["versao"] == 0  # nada foi gravado


def test_conflito_de_versao_e_restaurar_padrao(prefs):
    prefs.atualizar({"tema": "claro"}, 0)
    with pytest.raises(ConflitoVersao):
        prefs.atualizar({"tema": "escuro"}, 0)
    r = prefs.restaurar(["tema"], 1)
    assert estado(prefs)["tema"]["valor"] == "auto" and r["versao"] == 2
    with pytest.raises(ValidacaoDominio):
        prefs.restaurar(["inexistente"], 2)


def test_aplicadores_rodam_na_mudanca_e_na_subida_e_falha_de_um_nao_derruba(prefs):
    visto: list = []
    prefs.registrar_aplicador("contexto_ativo", visto.append)
    prefs.registrar_aplicador("contexto_ativo", lambda v: 1 / 0)  # falha isolada
    prefs.registrar_aplicador("tema", lambda v: visto.append(("tema", v)))
    prefs.aplicar_todos()
    assert True in visto and ("tema", "auto") in visto
    prefs.atualizar({"contexto_ativo": False}, 0)
    assert visto[-1] is False
    prefs.restaurar(["contexto_ativo"], 1)
    assert visto[-1] is True


def test_evento_de_auditoria_leva_so_ids_nunca_valores(prefs, repo, tmp_path):
    pasta = tmp_path / "minhas-notas-secretas"
    pasta.mkdir()
    prefs.atualizar({"pastas_permitidas": [str(pasta)]}, 0)
    with repo.leitura() as t:
        ev = [e for e in t.eventos_apos(0) if e["tipo"] == "preferencias.atualizadas"]
    assert ev[0]["payload"] == {"ids": ["pastas_permitidas"], "versao": 1} and "secretas" not in str(ev)


def test_sementes_do_ambiente_valem_ate_o_usuario_salvar(repo, relogio, tmp_path):
    s = PreferenciasServico(repo, relogio, sementes={"ferramentas_arquivos_ativas": True, "pastas_permitidas": [str(tmp_path)]})
    e = estado(s)
    assert e["ferramentas_arquivos_ativas"]["valor"] is True and e["ferramentas_arquivos_ativas"]["fonte"] == "ambiente"
    s.atualizar({"ferramentas_arquivos_ativas": False}, 0)
    assert estado(s)["ferramentas_arquivos_ativas"]["valor"] is False and estado(s)["ferramentas_arquivos_ativas"]["fonte"] == "usuario"


def test_avisos_sobre_combinacoes_estranhas(prefs, tmp_path):
    a, b = tmp_path / "a", tmp_path / "a" / "privado"
    b.mkdir(parents=True)
    prefs.atualizar({"ferramentas_arquivos_ativas": True}, 0)
    assert any("nenhuma pasta permitida" in x for x in prefs.avisos())
    prefs.atualizar({"pastas_permitidas": [str(a)], "pastas_proibidas": [str(a)]}, 1)
    assert any("ficara inacessivel" in x for x in prefs.avisos())


# ---------------------------------------------------------------- pastas: validacao e protecao


def test_pasta_precisa_ser_absoluta_existente_e_nao_a_raiz_do_disco(tmp_path):
    for ruim in ("", "relativa/pasta", str(tmp_path / "nao-existe"), str(Path(tmp_path.anchor))):
        with pytest.raises(ValidacaoDominio):
            validar_pasta(ruim, "Pastas")
    (tmp_path / "arq.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValidacaoDominio):
        validar_pasta(str(tmp_path / "arq.txt"), "Pastas")
    assert validar_pasta(str(tmp_path), "Pastas") == tmp_path.resolve()
    assert validar_pasta(str(tmp_path / "ainda-nao"), "Proibidas", deve_existir=False)  # proibir nao exige existir


def test_dados_do_usuario_e_git_sao_protegidos_e_nunca_liberaveis(tmp_path, prefs):
    perfil = tmp_path / "perfis" / "eu"
    (perfil / "dados").mkdir(parents=True)
    definir_protegidas([perfil])
    assert protegido(perfil / "dados" / "forja.sqlite3") and protegido(tmp_path / "repo" / ".git" / "config")
    with pytest.raises(ValidacaoDominio, match="protegida"):
        prefs.atualizar({"pastas_permitidas": [str(perfil / "dados")]}, 0)
    with pytest.raises(ValidacaoDominio, match="protegida"):
        validar_pasta(str(tmp_path / "x" / ".git"), "Pastas", deve_existir=False)


def test_proibida_vence_permitida_em_qualquer_profundidade(tmp_path):
    (tmp_path / "ok" / "sub" / "fundo").mkdir(parents=True)
    pol = PoliticaPastas(True, (tmp_path / "ok",), (tmp_path / "ok" / "sub",))
    with aplicar(pol):
        assert proibido(tmp_path / "ok" / "sub") and proibido(tmp_path / "ok" / "sub" / "fundo" / "x.txt")
        assert not proibido(tmp_path / "ok" / "outra") and not proibido(tmp_path / "ok" / "subsub")  # prefixo textual nao engana
    assert not proibido(tmp_path / "ok" / "sub")  # fora de uma execucao de ferramenta, so protegidas valem


# ---------------------------------------------------------------- catalogo: a politica vale para toda ferramenta de arquivo


@pytest.fixture
def area(tmp_path: Path) -> Path:
    (tmp_path / "pub").mkdir()
    (tmp_path / "pub" / "a.py").write_text("def publico():\n    return 1\n", encoding="utf-8")
    (tmp_path / "pub" / "privado").mkdir()
    (tmp_path / "pub" / "privado" / "segredo.py").write_text("def interno():\n    return 'api_key = \"abcdefgh12345\"'\n", encoding="utf-8")
    (tmp_path / "pub" / "privado" / "nota.md").write_text("# Nota\n[[Outra]]\n", encoding="utf-8")
    return tmp_path


def catalogo(area, prefs) -> Catalogo:
    prefs.atualizar({"ferramentas_arquivos_ativas": True, "pastas_permitidas": [str(area / "pub")],
                     "pastas_proibidas": [str(area / "pub" / "privado")]}, prefs.estado()["versao"])
    return Catalogo((), None, politica=prefs.politica_pastas)


def test_padrao_do_codigo_e_desligado_e_ferramentas_de_arquivo_ficam_indisponiveis(prefs):
    cat = Catalogo((), None, politica=prefs.politica_pastas)
    disp = {f["id"]: f["disponivel"] for f in cat.listar()}
    assert not disp["codigo.outline"] and not disp["repo.mapa"] and disp["git.diff_analisar"]  # texto continua funcionando
    with pytest.raises(ValidacaoDominio, match="APP_TOOLS_ROOTS|desligadas"):
        cat.executar("codigo.outline", {"caminho": "a.py"})


def test_ligada_com_pasta_permitida_funciona_e_a_proibida_e_negada_sem_revelar_existencia(area, prefs):
    cat = catalogo(area, prefs)
    assert "publico" in cat.executar("codigo.outline", {"caminho": str(area / "pub" / "a.py")})["resumo"]
    erros = []
    for alvo in ("privado/segredo.py", "privado/nao-existe.py"):  # existente e inexistente dentro da proibida
        with pytest.raises(ValidacaoDominio) as e:
            cat.executar("texto.amostra", {"caminho": str(area / "pub" / alvo)})
        erros.append((type(e.value), e.value.mensagem))
    assert erros[0] == erros[1]


def test_percursos_pulam_a_pasta_proibida(area, prefs):
    cat = catalogo(area, prefs)
    mapa = cat.executar("repo.mapa", {"caminho": str(area / "pub")})
    assert mapa["dados"]["arquivos"] == 1 and "privado" not in str(mapa["dados"]["pastas"])
    seg = cat.executar("segredos.varrer", {"caminho": str(area / "pub")})
    assert seg["dados"]["achados"] == [] and seg["dados"]["arquivos_lidos"] == 1  # o api_key da pasta proibida nunca foi lido
    cofre = cat.executar("vault.indexar", {"caminho": str(area / "pub")})
    assert cofre["dados"]["notas"] == []  # nota.md esta na pasta proibida


def test_dados_do_usuario_continuam_protegidos_mesmo_com_pai_permitido(tmp_path, prefs):
    perfil = tmp_path / "perfil"
    (perfil / "credenciais").mkdir(parents=True)
    (perfil / "credenciais" / "api_token.txt").write_text("x", encoding="utf-8")
    (perfil / "notas.md").write_text("# nota", encoding="utf-8")
    definir_protegidas([perfil])
    prefs.atualizar({"ferramentas_arquivos_ativas": True, "pastas_permitidas": [str(tmp_path)]}, 0)
    cat = Catalogo((), None, politica=prefs.politica_pastas)
    for alvo in ("credenciais/api_token.txt", "notas.md"):
        with pytest.raises(ValidacaoDominio):
            cat.executar("texto.amostra", {"caminho": str(perfil / alvo)})
    assert cat.executar("repo.mapa", {"caminho": str(tmp_path)})["dados"]["arquivos"] == 0


def test_link_simbolico_para_pasta_proibida_e_recusado(area, prefs):
    cat = catalogo(area, prefs)
    try:
        (area / "pub" / "atalho").symlink_to(area / "pub" / "privado", target_is_directory=True)
    except OSError:
        pytest.skip("sem permissao para criar link simbolico")
    with pytest.raises(ValidacaoDominio):
        cat.executar("texto.amostra", {"caminho": str(area / "pub" / "atalho" / "segredo.py")})


def test_email_sempre_mascarado_quando_a_preferencia_esta_ligada(area, prefs):
    import mailbox
    from email.message import EmailMessage

    caixa = mailbox.mbox(str(area / "pub" / "c.mbox"))
    m = EmailMessage()
    m["From"], m["Subject"], m["Date"] = "ana.silva@exemplo.com", "oi", "Mon, 02 Nov 2026 10:00:00 +0000"
    m.set_content("corpo")
    caixa.add(mailbox.mboxMessage(m))
    caixa.flush()
    caixa.close()
    cat = catalogo(area, prefs)
    entrada = {"caminho": str(area / "pub" / "c.mbox"), "mascarar_enderecos": False}  # o agente tenta desmascarar
    assert "ana.silva@" not in cat.executar("email.ler_mbox", entrada)["resumo"]
    prefs.atualizar({"mascarar_enderecos_email": False}, prefs.estado()["versao"])
    assert "ana.silva@exemplo.com" in cat.executar("email.ler_mbox", entrada)["resumo"]


# ---------------------------------------------------------------- API ponta a ponta (inclui limite configuravel)


@pytest.fixture
def cli(tmp_path: Path, _db_migrado: Path) -> Iterator[TestClient]:
    (tmp_path / "data").mkdir()
    shutil.copyfile(_db_migrado, tmp_path / "data" / "forja.sqlite3")
    cfg = Configuracoes(_env_file=None, app_data_dir=tmp_path / "data", app_log_dir=tmp_path / "logs",  # type: ignore[call-arg]
                        app_api_token=TOKEN, app_allowed_hosts="testserver")
    with TestClient(criar_app(cfg, AgenteMock()), headers={"Authorization": f"Bearer {TOKEN}"}) as c:
        yield c


def put(cli, valores, versao=None):
    versao = cli.get("/api/v1/preferencias").json()["versao"] if versao is None else versao
    return cli.put("/api/v1/preferencias", json={"expected_version": versao, "valores": valores})


def test_api_lista_categorias_com_explicacoes_e_exige_autenticacao(cli):
    r = cli.get("/api/v1/preferencias").json()
    assert [c["id"] for c in r["categorias"]] == [c.id for c in CATEGORIAS]
    todos = {i["id"]: i for c in r["categorias"] for i in c["itens"]}
    assert todos["limite_requisicoes_por_minuto"]["exemplos"][0]["rotulo"] == "Baixo" and todos["ferramentas_arquivos_ativas"]["valor"] is False
    sem = TestClient(cli.app, headers={"Host": "testserver"})
    assert sem.get("/api/v1/preferencias").status_code in (401, 403) and sem.put("/api/v1/preferencias", json={}).status_code in (401, 403)
    assert sem.get("/api/v1/usuario/perfil").status_code in (401, 403)


def test_api_recusa_invalido_e_conflito(cli):
    assert put(cli, {"tema": "roxo"}).status_code == 422
    assert put(cli, {"tema": "claro"}).status_code == 200
    assert put(cli, {"tema": "escuro"}, versao=0).status_code == 409
    assert cli.put("/api/v1/preferencias", json={"expected_version": 1, "valores": {}}).status_code == 422
    assert cli.post("/api/v1/preferencias/restaurar", json={"expected_version": 1, "ids": ["tema"]}).json()["versao"] == 2


def test_limite_de_requisicoes_e_configuravel_e_estaticos_nao_gastam_a_cota(cli):
    assert put(cli, {"limite_requisicoes_por_minuto": 30}).status_code == 200
    assert cli.app.state.limitador.limite == 30  # aplicado na hora, sem reiniciar
    estaticos = [cli.get("/estatico/app.css").status_code for _ in range(60)]
    assert set(estaticos) == {200}  # 60 > 30, mas estaticos nao contam por padrao
    assert put(cli, {"contar_estaticos_no_limite": True}).status_code in (200, 429)
    contados = [cli.get("/estatico/app.css").status_code for _ in range(60)]
    assert 429 in contados  # agora contam


def test_api_limite_alto_por_preferencia_evita_429_em_rajada(cli):
    assert put(cli, {"limite_requisicoes_por_minuto": 5000}).status_code == 200
    assert all(cli.get("/api/v1/preferencias").status_code == 200 for _ in range(300))


def test_preferencias_chegam_aos_componentes_em_execucao(cli):
    s = cli.app.state.servico
    assert s.contexto_ativo is True
    put(cli, {"contexto_ativo": False, "aprovacao_timeout_segundos": 300, "contexto_orcamento_tokens": 4000})
    assert s.contexto_ativo is False and s.espera_aprovacao_s == 300.0 and s.construtor_contexto.orcamento == 4000


def test_ferramentas_de_arquivo_so_aparecem_depois_de_ligar_e_permitir_pela_tela(cli, tmp_path):
    pasta = tmp_path / "meus-arquivos"
    pasta.mkdir()
    (pasta / "x.py").write_text("def f():\n    pass\n", encoding="utf-8")
    ferr = lambda: {f["id"]: f["disponivel"] for f in cli.get("/api/v1/ferramentas").json()}  # noqa: E731
    assert not ferr()["codigo.outline"]
    assert put(cli, {"ferramentas_arquivos_ativas": True}).status_code == 200 and not ferr()["codigo.outline"]  # ligada, sem pasta
    assert put(cli, {"pastas_permitidas": [str(tmp_path / "nao-existe")]}).status_code == 422
    assert put(cli, {"pastas_permitidas": [str(pasta)]}).status_code == 200 and ferr()["codigo.outline"]
    ok = cli.post("/api/v1/ferramentas/codigo.outline/executar", json={"entrada": {"caminho": str(pasta / "x.py")}})
    assert ok.status_code == 200 and "f" in ok.json()["resumo"]
    assert put(cli, {"pastas_proibidas": [str(pasta)]}).status_code == 200
    assert cli.post("/api/v1/ferramentas/codigo.outline/executar", json={"entrada": {"caminho": str(pasta / "x.py")}}).status_code == 422
    assert put(cli, {"ferramentas_arquivos_ativas": False}).status_code == 200 and not ferr()["codigo.outline"]


def test_pasta_dos_dados_do_usuario_nao_pode_ser_liberada_pela_api(cli):
    assert put(cli, {"pastas_permitidas": [str(cli.app.state.perfil.raiz)]}).status_code == 422


def test_api_perfil_mostra_onde_ficam_os_dados_e_o_que_sobe_ao_git(cli):
    r = cli.get("/api/v1/usuario/perfil").json()
    assert set(r["pastas"]) >= {"credenciais", "dados", "notas", "ferramentas", "config"} and "memoria e segundo cerebro" in r["fica_so_aqui"]
    assert "codigo e logica" in r["sobe_ao_git"] and r["dentro_do_repositorio"] is False


def test_apis_de_ambiente_antigo_semeiam_as_preferencias(tmp_path, _db_migrado):
    (tmp_path / "data").mkdir()
    shutil.copyfile(_db_migrado, tmp_path / "data" / "forja.sqlite3")
    cfg = Configuracoes(_env_file=None, app_data_dir=tmp_path / "data", app_log_dir=tmp_path / "logs", app_api_token=TOKEN,  # type: ignore[call-arg]
                        app_allowed_hosts="testserver", app_tools_roots=str(tmp_path), app_rate_limit_per_minute=100)
    with TestClient(criar_app(cfg, AgenteMock()), headers={"Authorization": f"Bearer {TOKEN}"}) as c:
        itens = {i["id"]: i for cat in c.get("/api/v1/preferencias").json()["categorias"] for i in cat["itens"]}
        assert itens["ferramentas_arquivos_ativas"]["valor"] is True and itens["ferramentas_arquivos_ativas"]["fonte"] == "ambiente"
        assert itens["limite_requisicoes_por_minuto"]["valor"] == 100 and c.app.state.limitador.limite == 100


def test_preferencias_ficam_no_banco_do_usuario_nao_em_arquivo_do_projeto(cli):
    put(cli, {"tema": "escuro"})
    with cli.app.state.servico.repo.leitura() as t:
        assert t.obter(T.Configuracao, "preferencias")["valor"] == {"tema": "escuro"}


def test_editaveis_nao_incluem_itens_de_exibicao():
    assert "modelos" not in EDITAVEIS and "protecoes_fixas" not in EDITAVEIS and "tema" in EDITAVEIS
