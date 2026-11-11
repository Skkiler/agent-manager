"""Validar e USAR um .env sem que o agente leia valores: ferramenta env.verificar e comandos que consomem o arquivo."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import forja.ferramentas.ambiente_env as amb
from forja.dominio.erros import ValidacaoDominio
from forja.ferramentas.catalogo import Catalogo
from forja.seguranca.acoes import descrever_acao
from forja.seguranca.pastas import PoliticaPastas

SEGREDO = "sk-valor-super-secreto-123456789"


@pytest.fixture
def projeto(tmp_path: Path) -> Path:
    (tmp_path / ".env").write_text(
        f"API_KEY={SEGREDO}\nDATABASE_URL=postgres://u:p@db:5432/x\nPORTA=80800\nDEBUG=true\nVAZIA=\n# comentario\nlinha quebrada\nDEBUG=false\n",
        encoding="utf-8")
    (tmp_path / ".env.example").write_text("API_KEY=\nDATABASE_URL=\nREDIS_URL=\nVAZIA=\n", encoding="utf-8")
    return tmp_path


@pytest.fixture(autouse=True)
def _limpar():
    amb._comparacoes.clear()
    yield
    amb._comparacoes.clear()


def _cat(raiz: Path) -> Catalogo:
    return Catalogo((), politica=lambda: PoliticaPastas(ativa=True, permitidas=(raiz,)))


def _rodar(raiz: Path, **entrada):
    return _cat(raiz).executar("env.verificar", {"caminho": str(raiz / ".env"), **entrada})


def test_responde_fatos_sem_nunca_devolver_valores(projeto):
    r = _rodar(projeto, chaves=["API_KEY", "REDIS_URL", "VAZIA"], formatos={"DATABASE_URL": "url", "PORTA": "porta", "DEBUG": "booleano"})
    tudo = json.dumps(r, ensure_ascii=False)
    for valor in (SEGREDO, "postgres://", "80800", "u:p@db"):
        assert valor not in tudo
    v = r["dados"]["verificacoes"]
    assert v["API_KEY"] == {"existe": True, "vazia": False} and v["REDIS_URL"] == {"existe": False} and v["VAZIA"]["vazia"] is True
    assert v["DATABASE_URL"]["formato_url"] is True and v["PORTA"]["formato_porta"] is False and v["DEBUG"]["formato_booleano"] is True
    assert r["dados"]["faltando_em_relacao_ao_exemplo"] == ["REDIS_URL"] and r["dados"]["vazias_que_o_exemplo_espera"] == ["VAZIA"]
    assert r["dados"]["linhas_mal_formadas"] == [7] and r["dados"]["chaves_duplicadas"] == ["DEBUG"]


def test_igualdade_tem_limite_de_tentativas(projeto):
    assert _rodar(projeto, comparar={"API_KEY": SEGREDO})["dados"]["verificacoes"]["API_KEY"]["igual_ao_informado"] is True
    assert _rodar(projeto, comparar={"API_KEY": "chute"})["dados"]["verificacoes"]["API_KEY"]["igual_ao_informado"] is False
    _rodar(projeto, comparar={"API_KEY": "chute2"})
    bloqueado = _rodar(projeto, comparar={"API_KEY": SEGREDO})["dados"]["verificacoes"]["API_KEY"]["igual_ao_informado"]
    assert isinstance(bloqueado, str) and "limite" in bloqueado  # nem a resposta certa e confirmada depois do limite


def test_janela_de_comparacao_expira():
    arq = Path("x/.env")
    assert all(amb._pode_comparar(arq, "K", 0.0) for _ in range(3)) and not amb._pode_comparar(arq, "K", 1.0)
    assert amb._pode_comparar(arq, "K", amb.JANELA_S + 1)


@pytest.mark.parametrize("entrada", [{"chaves": ["1INVALIDA"]}, {"formatos": {"X": "regex"}}, {"caminho": "segredos.pem"}, {"caminho": "config.txt"}])
def test_entradas_que_vazariam_ou_fogem_do_escopo_sao_recusadas(projeto, entrada):
    (projeto / "config.txt").write_text("A=1", encoding="utf-8")
    with pytest.raises(Exception):  # noqa: B017 - validacao do contrato (422) ou de dominio, conforme o campo
        _cat(projeto).executar("env.verificar", {**entrada} if "caminho" in entrada and "/" in entrada["caminho"] else {"caminho": str(projeto / entrada.get("caminho", ".env")), **{k: v for k, v in entrada.items() if k != "caminho"}})


def test_fora_das_pastas_permitidas_ou_leitura_desligada(projeto, tmp_path_factory):
    outra = tmp_path_factory.mktemp("outra")
    (outra / ".env").write_text("A=1", encoding="utf-8")
    with pytest.raises(ValidacaoDominio):
        _cat(projeto).executar("env.verificar", {"caminho": str(outra / ".env")})
    with pytest.raises(ValidacaoDominio):
        Catalogo(()).executar("env.verificar", {"caminho": str(projeto / ".env")})


def test_env_do_perfil_da_forja_continua_protegido(projeto):
    from forja.seguranca.pastas import definir_protegidas

    definir_protegidas([projeto])
    try:
        with pytest.raises(ValidacaoDominio):
            _rodar(projeto)
    finally:
        definir_protegidas([])


# ------------------------------------------------------------------ comandos que USAM o .env
@pytest.mark.parametrize("cmd", ["docker compose --env-file .env up -d", "docker run --env-file=.env img", "docker-compose --env-file ./.env up",
                                 "uv run --env-file .env pytest", "podman-compose --env-file .env up"])
def test_consumir_env_e_permitido_como_comando_comum(cmd):
    r = descrever_acao({"kind": "execute", "rawInput": {"command": cmd}})
    assert r["sensivel"] is False and r["usa_env"] is True and r["categoria"] == "executar_comando" and "sem exibi-lo" in r["descricao"]


@pytest.mark.parametrize("cmd", ["cat .env", "type .env", "docker compose --env-file .env config", "docker compose config", "printenv", "env",
                                 "set", "docker inspect app", "docker exec app printenv", "echo $env:API_KEY", "echo %API_KEY%",
                                 "Get-ChildItem env:", "docker compose --env-file .env up && cat .env", "python -c open('.env')"])
def test_imprimir_variaveis_continua_sendo_leitura_de_segredo(cmd):
    assert descrever_acao({"kind": "execute", "rawInput": {"command": cmd}})["sensivel"] is True, cmd
