"""Hospedagem local: iniciador --abrir, PWA instalavel (manifesto/icones servidos) e CSP sem relaxar o resto."""

from __future__ import annotations

import json

from forja.__main__ import abrir_quando_pronto, endereco_local


def test_endereco_local_sempre_loopback():
    assert endereco_local("127.0.0.1", 8787) == "http://127.0.0.1:8787/"
    assert endereco_local("0.0.0.0", 8787) == "http://127.0.0.1:8787/"  # mesmo com bind LAN, o navegador local usa loopback  # noqa: S104
    assert endereco_local("::1", 9) == "http://[::1]:9/"


def test_abrir_desiste_sem_servidor_e_nao_abre_nada():
    abertos = []
    assert abrir_quando_pronto("http://127.0.0.1:9/", tentativas=2, intervalo=0.01, abrir=abertos.append) is False and abertos == []


def test_manifesto_icones_e_csp(client):
    m = client.get("/estatico/manifest.webmanifest")
    assert m.status_code == 200
    dados = json.loads(m.content)
    assert dados["display"] == "standalone" and dados["start_url"] == "/" and {i["sizes"] for i in dados["icons"]} >= {"192x192", "512x512"}
    for i in dados["icons"]:
        assert client.get(i["src"]).status_code == 200
    html = client.get("/").text
    assert 'rel="manifest"' in html and "manifest-src 'self'" in html and "object-src 'none'" in html and "unsafe-inline" not in html
    assert client.get("/estatico/tema.css").status_code == 200
