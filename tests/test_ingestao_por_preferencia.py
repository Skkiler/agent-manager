"""Pastas permitidas na tela tambem liberam a ingestao do segundo cerebro; pastas proibidas valem tambem para ela."""

from __future__ import annotations


def _prefs(client, **valores):
    v = client.get("/api/v1/preferencias").json()["versao"]
    r = client.put("/api/v1/preferencias", json={"expected_version": v, "valores": valores})
    assert r.status_code == 200, r.text


def test_pasta_permitida_libera_ingestao_e_proibida_e_respeitada(client, tmp_path):
    raiz = tmp_path / "codigos"
    (raiz / "app").mkdir(parents=True)
    (raiz / "segredo").mkdir()
    (raiz / "app" / "fila.py").write_text("def enfileirar(x):\n    '''Fila FIFO.'''\n    return x\n", encoding="utf-8")
    (raiz / "segredo" / "nota.md").write_text("# Diario\nconteudo privado", encoding="utf-8")
    corpo = {"namespace": "publico", "raiz": str(raiz), "repositorio": "codigos"}
    assert client.post("/api/v1/memorias/ingerir", json=corpo).status_code == 403  # nada liberado ainda
    _prefs(client, ferramentas_arquivos_ativas=True, pastas_permitidas=[str(raiz)], pastas_proibidas=[str(raiz / "segredo")])
    r = client.post("/api/v1/memorias/ingerir", json=corpo)
    assert r.status_code == 200, r.text
    assert r.json()["novos"] == 1  # so fila.py: a pasta proibida nem e percorrida
    busca = lambda q: client.get("/api/v1/memorias/buscar", params={"q": q, "fonte": "codigo"}).json()["resultados"]  # noqa: E731
    assert busca("enfileirar") and not busca("Diario privado")
    _prefs(client, ferramentas_arquivos_ativas=False)
    assert client.post("/api/v1/memorias/ingerir", json=corpo).status_code == 403  # desligar revoga na hora
