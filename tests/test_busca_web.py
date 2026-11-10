"""Busca web (Brave/SearXNG) e leitura de pagina: so URLs de busca recente ou dominios liberados. Transporte simulado."""

from __future__ import annotations

import httpx
import pytest

from forja.dominio.erros import ValidacaoDominio
from forja.integracoes.busca_web import BuscaWeb, consulta_segura, html_para_texto
from forja.integracoes.rede import ErroRede
from forja.orquestracao.integracao_servico import IntegracaoServico
from tests.test_integracoes_rede import publico, transporte

ENV = {"FORJA_INT_BRAVE_TOKEN": "chave-brave-ficticia"}
PAGINA = ("<html><head><title>Fila com prioridade</title><script>roubar()</script><style>x{}</style></head><body><nav>menu</nav>"
          "<h1>Fila</h1><p>Use <b>heapq</b> para prioridade.</p><pre>import heapq\nheapq.heappush(f, x)</pre><footer>rodape</footer></body></html>")


@pytest.fixture(autouse=True)
def _limpar():
    BuscaWeb._recentes.clear()
    yield
    BuscaWeb._recentes.clear()


def _handler(req: httpx.Request) -> httpx.Response:
    if req.url.path == "/res/v1/web/search":
        assert req.headers["X-Subscription-Token"] == "chave-brave-ficticia"
        return httpx.Response(200, json={"web": {"results": [
            {"title": "Python <strong>heapq</strong>", "url": "https://docs.python.org/3/library/heapq.html", "description": "Fila de <strong>prioridade</strong>"},
            {"title": "inseguro", "url": "http://exemplo.com/x", "description": "sem https"}]}})
    if req.url.path == "/search":
        return httpx.Response(200, json={"results": [{"title": "SX", "url": "https://a.example/b", "content": "c"}]})
    return httpx.Response(200, text=PAGINA, headers={"content-type": "text/html"})


def _servico(repo, **cfg):
    t, visto = transporte(_handler)
    s = IntegracaoServico(repo, ler=ENV.get, resolver=publico, transporte=t)
    s.salvar("busca_web", {"ativo": True, "provedor": "brave", "variavel_token": "FORJA_INT_BRAVE_TOKEN", **cfg}, 0)
    return s, visto


def test_buscar_devolve_so_https_sem_html_e_com_aviso(repo):
    s, visto = _servico(repo)
    r = s.executar("busca_web", "buscar", {"consulta": "fila de prioridade python"})
    assert "1 resultado(s)" in r.resumo and "Python heapq" in r.resumo and "<strong>" not in r.resumo and "http://exemplo" not in r.resumo
    assert any("NAO confiavel" in a for a in r.avisos) and visto[0].url.params["q"] == "fila de prioridade python"


def test_ler_pagina_so_depois_da_busca_e_extrai_texto_limpo(repo):
    s, visto = _servico(repo)
    url = "https://docs.python.org/3/library/heapq.html"
    with pytest.raises(ValidacaoDominio, match="busca recente"):
        s.executar("busca_web", "ler_pagina", {"url": url})
    s.executar("busca_web", "buscar", {"consulta": "heapq"})
    r = s.executar("busca_web", "ler_pagina", {"url": url})
    assert "Fila com prioridade" in r.resumo and "heapq.heappush" in r.resumo and "roubar" not in r.resumo and "menu" not in r.resumo
    assert visto[-1].headers["host"] == "docs.python.org" and "X-Subscription-Token" not in visto[-1].headers  # chave nunca vai a terceiros
    with pytest.raises(ValidacaoDominio):
        s.executar("busca_web", "ler_pagina", {"url": "https://docs.python.org/3/library/outra.html"})  # nao veio da busca


def test_dominio_liberado_le_direto_e_curinga(repo):
    s, _ = _servico(repo, itens_permitidos=["*.mozilla.org"])
    assert "Fila" in s.executar("busca_web", "ler_pagina", {"url": "https://developer.mozilla.org/pt-BR/docs/x"}).resumo
    with pytest.raises(ValidacaoDominio):
        s.executar("busca_web", "ler_pagina", {"url": "https://mozilla.org.evil.example/x"})


@pytest.mark.parametrize("url", ["http://docs.python.org/x", "https://user:senha@docs.python.org/x", "file:///etc/passwd", "javascript:1"])
def test_enderecos_invalidos(repo, url):
    s, _ = _servico(repo, itens_permitidos=["docs.python.org"])
    with pytest.raises(ValidacaoDominio):
        s.executar("busca_web", "ler_pagina", {"url": url})


def test_pagina_em_ip_privado_e_bloqueada_mesmo_liberada(repo):
    t, _ = transporte(_handler)
    s = IntegracaoServico(repo, ler=ENV.get, resolver=lambda h, p: ["10.0.0.5"] if h == "intranet.example" else ["93.184.216.34"], transporte=t)
    s.salvar("busca_web", {"ativo": True, "provedor": "brave", "variavel_token": "FORJA_INT_BRAVE_TOKEN", "itens_permitidos": ["intranet.example"]}, 0)
    with pytest.raises(Exception) as e:
        s.executar("busca_web", "ler_pagina", {"url": "https://intranet.example/segredos"})
    assert "nao e publico" in str(getattr(e.value, "mensagem", e.value))


def test_consulta_com_credencial_nao_sai():
    with pytest.raises(ValidacaoDominio):
        consulta_segura("erro com api_key = 'sk-abcdefghijklmnopqrstuvwx0123456789'")
    with pytest.raises(ValidacaoDominio):
        consulta_segura("x")


def test_searxng(repo):
    t, visto = transporte(_handler)
    s = IntegracaoServico(repo, ler=ENV.get, resolver=publico, transporte=t)
    s.salvar("busca_web", {"ativo": True, "provedor": "searxng", "base_url": "https://busca.minha.example"}, 0)
    assert s.estado("busca_web")["pronta"]
    r = s.executar("busca_web", "buscar", {"consulta": "fila"})
    assert "SX" in r.resumo and visto[0].url.params["format"] == "json"


def test_configuracao_invalida(repo):
    t, _ = transporte(_handler)
    s = IntegracaoServico(repo, ler=ENV.get, resolver=publico, transporte=t)
    for ruim in ({"provedor": ""}, {"provedor": "brave"}, {"provedor": "searxng", "base_url": "http://x.example"},
                 {"provedor": "brave", "variavel_token": "FORJA_INT_BRAVE_TOKEN", "itens_permitidos": ["https://x.com/a"]}):
        with pytest.raises(ValidacaoDominio):
            s.salvar("busca_web", {"ativo": True, **ruim}, 0)


def test_html_quebrado_e_limite():
    titulo, texto, cortado = html_para_texto("<p>" + "a " * 10000)
    assert cortado and len(texto) <= 8000
    assert html_para_texto("<title>T</title><p>x")[0] == "T"


def test_erro_do_provedor_vira_erro_de_dominio(repo):
    t, _ = transporte(lambda r: httpx.Response(401, json={}))
    s = IntegracaoServico(repo, ler=ENV.get, resolver=publico, transporte=t)
    s.salvar("busca_web", {"ativo": True, "provedor": "brave", "variavel_token": "FORJA_INT_BRAVE_TOKEN"}, 0)
    with pytest.raises(ErroRede):
        s.executar("busca_web", "buscar", {"consulta": "fila"})
