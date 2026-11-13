"""Login do painel por usuario e senha: primeiro acesso, sessao, bloqueio, troca de senha, CLI e convivencia com o token da API."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from forja.dominio.erros import AcessoBloqueado, Conflito, CredenciaisInvalidas, ValidacaoDominio
from forja.orquestracao.contas_servico import ContasServico
from forja.seguranca import senhas

API = "/api/v1"
SENHA = "uma frase longa e boa"


def test_hash_de_senha_com_sal_e_politica():
    h1, h2 = senhas.gerar_hash(SENHA), senhas.gerar_hash(SENHA)
    assert h1 != h2 and h1.startswith("scrypt$") and SENHA not in h1  # sal aleatorio; nunca o texto
    assert senhas.conferir(SENHA, h1) and not senhas.conferir(SENHA + "x", h1) and not senhas.conferir(SENHA, "lixo")
    for ruim in ("curta", "12345678", "aaaaaaaaaa", "ana-segura-123"):
        with pytest.raises(ValidacaoDominio):
            senhas.validar_senha(ruim, "ana")
    assert senhas.normalizar_nome("  Ana.Silva ") == "ana.silva"
    assert senhas.normalizar_nome("Ana.Silva+forja@Exemplo.com") == "ana.silva+forja@exemplo.com"  # e-mail como usuario
    for ruim in ("a", "com espaco", "x" * 70, "-comeca"):
        with pytest.raises(ValidacaoDominio):
            senhas.normalizar_nome(ruim)


def test_sessao_bloqueio_progressivo_e_troca_de_senha(repo, relogio):
    c = ContasServico(repo, 60, relogio)
    assert not c.existe_conta()
    s = c.configurar_primeira("ana", SENHA)
    assert c.sessao(s["token"])["usuario"] == "ana" and len(s["token"]) >= 40
    with pytest.raises(Conflito):
        c.configurar_primeira("outra", SENHA)  # primeiro acesso so uma vez
    with pytest.raises(CredenciaisInvalidas) as e1:
        c.entrar("ana", "errada-123", "1.2.3.4")
    with pytest.raises(CredenciaisInvalidas) as e2:
        c.entrar("ninguem", "errada-123", "1.2.3.4")
    assert e1.value.mensagem.split(" Restam")[0] == e2.value.mensagem  # nao revela se a conta existe
    for _ in range(4):
        with pytest.raises(CredenciaisInvalidas):
            c.entrar("ana", "errada-123", f"10.0.0.{_}")
    with pytest.raises(AcessoBloqueado) as b:
        c.entrar("ana", SENHA, "10.0.0.9")  # 5 erros: conta bloqueada mesmo com a senha certa
    assert 1 <= b.value.tentar_em_s <= 30
    relogio.avancar(31)
    s2 = c.entrar("ANA", SENHA, "10.0.0.9")  # nome normalizado; bloqueio venceu; falhas zeram
    relogio.avancar(59 * 60)
    assert c.sessao(s2["token"]) is not None  # uso renova a inatividade
    relogio.avancar(61 * 60)
    assert c.sessao(s2["token"]) is None  # inativa > 60 min: expirou
    s3, s4 = c.entrar("ana", SENHA), c.entrar("ana", SENHA)
    with pytest.raises(CredenciaisInvalidas):
        c.trocar_senha(s3["token"], "errada", "outra frase longa e boa")
    c.trocar_senha(s3["token"], SENHA, "outra frase longa e boa")
    assert c.sessao(s3["token"]) is not None and c.sessao(s4["token"]) is None  # as OUTRAS sessoes caem
    c.sair(s3["token"])
    assert c.sessao(s3["token"]) is None and c.sessao("x" * 300) is None and c.sessao(None) is None


def test_bloqueio_por_endereco(repo, relogio):
    c = ContasServico(repo, 60, relogio)
    for i in range(10):
        with pytest.raises(CredenciaisInvalidas):
            c.entrar(f"tentativa{i}", "qualquer-coisa", "6.6.6.6")
    with pytest.raises(AcessoBloqueado):
        c.entrar("outra", "qualquer-coisa", "6.6.6.6")
    with pytest.raises(CredenciaisInvalidas):  # outro endereco nao e afetado
        c.entrar("outra", "qualquer-coisa", "7.7.7.7")


def test_fluxo_http_do_painel(config):
    from forja.adapters.agentes_mock.mock import AgenteMock
    from forja.servidor.app import criar_app

    with TestClient(criar_app(config, AgenteMock())) as c:  # sem token: e o navegador de quem abre o painel
        assert c.get(f"{API}/kanban").status_code == 401
        e = c.get(f"{API}/auth/estado").json()
        assert e == {"exige_login": True, "configurado": False, "pode_configurar": False, "conectado": False, "usuario": None}
        # TestClient nao e loopback: o primeiro acesso exige o token da API (prova de acesso ao computador do servidor)
        assert c.post(f"{API}/auth/configurar", json={"usuario": "ana", "senha": SENHA}).status_code == 401
        tok_api = {"Authorization": f"Bearer {config.app_api_token.get_secret_value()}"}
        assert c.get(f"{API}/auth/estado", headers=tok_api).json()["pode_configurar"] is True
        r = c.post(f"{API}/auth/configurar", json={"usuario": "ana", "senha": SENHA}, headers=tok_api)
        assert r.status_code == 201 and r.json()["usuario"] == "ana"
        assert c.get(f"{API}/auth/estado").json()["configurado"] is True
        ruim = c.post(f"{API}/auth/entrar", json={"usuario": "ana", "senha": "errada-123"})
        assert ruim.status_code == 401 and ruim.json()["erro"] == "credenciais_invalidas" and "incorretos" in ruim.json()["mensagem"]
        ok = c.post(f"{API}/auth/entrar", json={"usuario": "ana", "senha": SENHA})
        assert ok.status_code == 200 and "senha" not in ok.text
        sess = {"Authorization": f"Bearer {ok.json()['token']}"}
        assert c.get(f"{API}/kanban", headers=sess).status_code == 200  # sessao vale para a API do painel
        assert c.get(f"{API}/auth/estado", headers=sess).json()["usuario"] == "ana"
        assert c.get(f"{API}/kanban", headers=tok_api).status_code == 200  # token da API continua (scripts, MCP)
        with c.stream("GET", f"{API}/eventos/stream", params={"token": ok.json()["token"], "follow": "false"}) as s:
            assert s.status_code == 200  # SSE aceita a sessao
        assert c.post(f"{API}/auth/senha", json={"senha_atual": "errada", "nova_senha": "nova frase longa"}, headers=sess).status_code == 401
        assert c.post(f"{API}/auth/senha", json={"senha_atual": SENHA, "nova_senha": "nova frase longa"}, headers=sess).status_code == 200
        assert c.post(f"{API}/auth/sair", headers=sess).status_code == 204
        assert c.get(f"{API}/kanban", headers=sess).status_code == 401
        tentativas = [c.post(f"{API}/auth/entrar", json={"usuario": "ana", "senha": "errada-123"}).status_code for _ in range(5)]
        bloq = c.post(f"{API}/auth/entrar", json={"usuario": "ana", "senha": "errada-123"})
        assert tentativas == [401] * 5, tentativas  # 5 erros seguidos: a proxima tentativa ja encontra a conta bloqueada
        assert bloq.status_code == 429, bloq.text and bloq.json()["tentar_em_s"] >= 1 and bloq.headers["Retry-After"]
        assert c.post(f"{API}/auth/entrar", json={"usuario": "ana", "senha": "x", "extra": 1}).status_code == 422


def test_sem_exigir_login_o_painel_abre_direto(tmp_path, _db_migrado):
    import shutil

    from forja.adapters.agentes_mock.mock import AgenteMock
    from forja.config import Configuracoes
    from forja.servidor.app import criar_app

    (tmp_path / "data").mkdir()
    shutil.copyfile(_db_migrado, tmp_path / "data" / "forja.sqlite3")
    cfg = Configuracoes(_env_file=None, app_data_dir=tmp_path / "data", app_log_dir=tmp_path / "logs", app_require_auth=False,
                        app_allowed_hosts="testserver")  # type: ignore[call-arg]
    with TestClient(criar_app(cfg, AgenteMock())) as c:
        assert c.get(f"{API}/auth/estado").json()["exige_login"] is False


def test_cli_cria_lista_e_redefine(config, monkeypatch, capsys):
    from forja.usuario import contas_cli

    monkeypatch.setenv("APP_DATA_DIR", str(config.app_data_dir))
    monkeypatch.setenv("APP_LOG_DIR", str(config.app_log_dir))
    from forja import config as modulo_config

    if hasattr(modulo_config.obter_configuracoes, "cache_clear"):
        modulo_config.obter_configuracoes.cache_clear()
    monkeypatch.setattr("sys.stdin", io.StringIO(SENHA + "\n"))
    assert contas_cli.main(["criar", "--usuario", "bia", "--senha-stdin"]) == 0
    assert contas_cli.main(["listar"]) == 0 and "bia" in capsys.readouterr().out
    monkeypatch.setattr("sys.stdin", io.StringIO("nova frase longa\n"))
    assert contas_cli.main(["redefinir", "--usuario", "bia", "--senha-stdin"]) == 0
    monkeypatch.setattr("sys.stdin", io.StringIO("123\n"))
    assert contas_cli.main(["criar", "--usuario", "cid", "--senha-stdin"]) == 2  # senha fraca: erro claro, nada criado
    if hasattr(modulo_config.obter_configuracoes, "cache_clear"):
        modulo_config.obter_configuracoes.cache_clear()
