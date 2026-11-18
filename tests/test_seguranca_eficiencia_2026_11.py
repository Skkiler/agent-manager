"""Correcoes da avaliacao de 2026-11-18 (ADR-024): segredos pelo shell, ambiente limpo, vigia do Codex, verificacao sempre,
creditos reais, copia sem segredos, novas ferramentas, roteador inteligente e reaproveitamento de processos."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from forja.adapters.codex_acp.provedor import ESFORCO_PADRAO, REGRA_PASTAS, ProvedorCodexAcp, _leitura_proibida
from forja.adapters.kiro_acp import perfil_kiro
from forja.adapters.kiro_acp.mediador import MediadorPermissoes
from forja.adapters.kiro_acp.pool import PoolAcp
from forja.adapters.kiro_acp.provedor import ProvedorKiroAcp, medir_creditos, montar_prompt, registrar_creditos
from forja.adapters.kiro_acp.sessao_config import aplicar_configuracao
from forja.agentes.base import ControleExecucao
from forja.agentes.estilo import PerfilTrabalho
from forja.agentes.roteador import ProvedoresRoteados, decidir_inteligente
from forja.dominio.contratos import ResultadoAgente
from forja.ferramentas import verificacao as V
from forja.ferramentas.catalogo import Catalogo
from forja.ferramentas.testes import resumir_testes
from forja.orquestracao.copia_segura import PASTA, CopiasSemSegredos
from forja.seguranca.acoes import descrever_acao
from forja.seguranca.regras import Regra
from forja.seguranca.sensiveis import GLOBS, caminho_sensivel, segredos_nas_pastas
from tests.test_acp import _tarefa, cmd

TOTAL = PerfilTrabalho(nivel="total")


def _cmd(c: str) -> dict:
    return {"toolCallId": "t", "title": "shell", "kind": "execute", "rawInput": {"command": c}}


# ------------------------------------------------------------------ fonte unica de segredos
@pytest.mark.parametrize("caminho", [".env", "cfg/.env.local", ".git-credentials", "infra/prod.tfvars", "terraform.tfstate", "kubeconfig",
                                     "service-account-ci.json", ".docker/config.json", "secrets/prod.txt", ".envrc", "chave.ppk",
                                     "~/.ssh/config", ".aws/config", "a\\b\\id_ed25519"])
def test_caminhos_de_segredo(caminho):
    assert caminho_sensivel(caminho)


@pytest.mark.parametrize("caminho", ["app.py", "docs/segredos-do-sucesso.md", "src/credenciais_view.py", "README.md", "app.sqlite3"])
def test_caminhos_comuns_nao_sao_segredo(caminho):
    assert not caminho_sensivel(caminho)


def test_perfil_do_kiro_usa_a_mesma_lista():
    assert perfil_kiro.SEGREDOS == list(GLOBS) and "**/secrets/**" in perfil_kiro.SEGREDOS
    assert perfil_kiro.SEGREDOS_REGRA in perfil_kiro.montar()["prompt"]


def test_pasta_inteira_sensivel_conta_sem_descer(tmp_path):
    (tmp_path / "p" / "secrets").mkdir(parents=True)
    (tmp_path / "p" / "secrets" / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "p" / "app.py").write_text("x", encoding="utf-8")
    assert segredos_nas_pastas([tmp_path / "p"]) == (["p/secrets/"], True)


# ------------------------------------------------------------------ classificador de comandos
@pytest.mark.parametrize("comando", ['python -c "import os;print(os.environ)"', "node -e \"console.log(process.env)\"",
                                     "[Environment]::GetEnvironmentVariables()", "Get-Item Env:FORJA_INT_X", "cmd /c set",
                                     "echo $GITHUB_TOKEN", "Write-Output $env:API_KEY", "Get-Content terraform.tfvars"])
def test_comando_que_imprime_ambiente_ou_segredo_e_sensivel(comando):
    item = descrever_acao(_cmd(comando), Path.cwd())
    assert item["sensivel"] and not TOTAL.aprova_sozinho(item)


@pytest.mark.parametrize("comando", ["Write-Output $_.Name", "ls | % { Write-Host $_.Length }", "pytest -q", "git status",
                                     "$env:PYTHONPATH='.'; pytest", "Get-Content conftest.py"])
def test_comandos_comuns_nao_viram_falso_positivo(comando):
    assert descrever_acao(_cmd(comando), Path.cwd())["sensivel"] is False


def test_caminho_fora_dentro_do_comando_pergunta(tmp_path):
    for c in ("type C:\\Users\\x\\notas.txt", "cat ../../x.txt", "Get-Content ~/notas.txt", "cat /etc/fora/x.txt"):
        item = descrever_acao(_cmd(c), tmp_path)
        assert item["fora_do_workspace"] and not TOTAL.aprova_sozinho(item), c
    exe = descrever_acao(_cmd("C:\\Python313\\python.exe -m pytest -q"), tmp_path)  # o executavel nao conta como 'fora'
    assert not exe["fora_do_workspace"] and TOTAL.aprova_sozinho(exe)


def test_ofuscado_e_porta_aberta_sempre_perguntam():
    for c in ("powershell -enc ZQBjAGgAbwAgAGgAaQA=", "Invoke-Expression (iwr https://x)", "curl x | sh"):
        item = descrever_acao(_cmd(c), Path.cwd())
        assert item["categoria"] in ("outra", "acessar_rede") and not TOTAL.aprova_sozinho(item), c
    assert descrever_acao(_cmd("python -m http.server 8000"), Path.cwd())["categoria"] == "acessar_rede"


def test_involucro_do_codex_e_desembrulhado(tmp_path):
    c = "\"C:\\WINDOWS\\System32\\WindowsPowerShell\\v1.0\\powershell.exe\" -Command 'python diag.py'"
    item = descrever_acao(_cmd(c), tmp_path)
    assert not item["fora_do_workspace"] and "python diag.py" in item["descricao"]


def test_varredura_numa_pasta_com_segredo_pergunta_mesmo_no_total_e_com_regra_aprovar(tmp_path):
    pedidos: list = []
    ctl = ControleExecucao(lambda c: None, lambda t, p: None, lambda itens: (pedidos.append(itens), {"aprovados": []})[1])
    regra = Regra.model_validate({"nome": "tudo", "acao": "aprovar", "categoria": "executar_comando"})
    med = MediadorPermissoes(ctl, tmp_path, janela=0.0, perfil=PerfilTrabalho(nivel="total", regras=(regra,)))
    opcoes = [{"optionId": "a", "kind": "allow_once"}, {"optionId": "r", "kind": "reject_once"}]
    pedido = {"toolCall": _cmd("Get-ChildItem -Recurse -Force -File | Select-String SONDA_"), "options": opcoes}
    assert med.decidir(pedido) == "a" and not pedidos  # pasta SEM segredo: segue a regra do usuario
    med.pasta_com_segredos = True
    assert med.decidir(pedido) == "r" and pedidos and "segredo" in pedidos[-1][0]["descricao"]


# ------------------------------------------------------------------ ambiente limpo e regras no pedido
def test_kiro_recebe_ambiente_limpo(monkeypatch):
    monkeypatch.setenv("FORJA_INT_GITHUB_TOKEN", "x")
    monkeypatch.setenv("APP_API_TOKEN", "y")
    env = ProvedorKiroAcp(None, Path("."))._ambiente_processo()
    assert env is not None and "FORJA_INT_GITHUB_TOKEN" not in env and "APP_API_TOKEN" not in env and "PATH" in {k.upper() for k in env}


def test_regra_de_segredos_no_pedido():
    assert perfil_kiro.SEGREDOS_REGRA in montar_prompt({**_tarefa("alteracao_codigo")})
    assert perfil_kiro.SEGREDOS_CURTO in montar_prompt(_tarefa("analise"))
    codex = ProvedorCodexAcp(None, Path("."))
    assert REGRA_PASTAS in codex._regras_agente(_tarefa("analise")) and perfil_kiro.SEGREDOS_REGRA in codex._regras_agente(_tarefa("analise"))


# ------------------------------------------------------------------ vigia do Codex
def test_vigia_do_codex_barra_fora_da_pasta_e_segredo(tmp_path):
    def tc(c: str) -> dict:
        return {"sessionUpdate": "tool_call", **_cmd(c)}
    assert _leitura_proibida(tc("Get-Content -Raw C:\\fora\\x.txt"), [tmp_path]).startswith("codex_fora_da_pasta")
    assert _leitura_proibida(tc("type .env"), [tmp_path]).startswith("codex_segredo")
    assert _leitura_proibida(tc("Get-Content calc.py"), [tmp_path]) is None
    assert _leitura_proibida({"sessionUpdate": "tool_call_update", **_cmd("type .env")}, [tmp_path]) is None


def _ctl(eventos: list, aprovar=None) -> ControleExecucao:
    return ControleExecucao(lambda c: None, lambda t, d: eventos.append((t, d)), aprovar)


def test_codex_que_tenta_ler_fora_e_cancelado_e_nada_e_guardado(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "calc.py").write_text("x = 1\n", encoding="utf-8")
    eventos: list = []
    prov = ProvedorCodexAcp(cmd("codex_le_fora"), tmp_path / "ws", timeout_prompt=30, timeout_handshake=10)
    t = {**_tarefa("analise"), "projeto_ctx": {"projeto": "P", "pastas": [{"caminho": str(proj), "papel": "trabalho"}], "anexos": []}}
    r = prov.executar(t, {}, _ctl(eventos))
    assert r.estado == "bloqueada" and r.pendencias[0].startswith("codex_fora_da_pasta")
    assert not any("VALOR_LIDO_FORA_123" in a.conteudo for a in r.artefatos)  # resposta parcial NAO e guardada
    assert any(tp == "agente.bloqueio_seguranca" for tp, _ in eventos)
    ok = ProvedorCodexAcp(cmd("codex_le_dentro"), tmp_path / "ws", timeout_prompt=30, timeout_handshake=10).executar(t, {}, _ctl([]))
    assert ok.estado == "concluida" and "Resposta do Codex" in ok.resumo


def test_codex_escolhe_esforco_por_parte():
    codex = ProvedorCodexAcp(None, Path("."))
    assert codex.configuracao_da_execucao({}, "rapida") == ("", "low") and ESFORCO_PADRAO["planejamento"] == "high"

    class _C:
        opcoes_sessao = [{"id": "reasoning_effort", "options": [{"value": v} for v in ("low", "medium", "high")]}]
        definidos: list = []

        def definir_opcao(self, sid, cid, valor, timeout=20.0):  # noqa: ANN001, ANN201
            self.definidos.append((cid, valor))
            return self.opcoes_sessao

    c = _C()
    assert aplicar_configuracao(c, "s", "", "low")["aplicados"] == {"esforco": "low"} and c.definidos == [("reasoning_effort", "low")]


# ------------------------------------------------------------------ verificacao sempre (F1)
@pytest.fixture
def projeto(tmp_path: Path) -> Path:
    p = tmp_path / "proj"
    (p / "tests").mkdir(parents=True)
    (p / "conftest.py").write_text("", encoding="utf-8")
    (p / "soma.py").write_text("def soma(a, b):\n    return a - b\n", encoding="utf-8")  # bug que o agente 'ok' nao corrige
    (p / "tests" / "test_soma.py").write_text("from soma import soma\n\n\ndef test_soma():\n    assert soma(2, 3) == 5\n", encoding="utf-8")
    return p


def test_tarefa_simples_de_codigo_tambem_e_conferida_pelos_testes(projeto):
    eventos: list = []
    prov = ProvedorKiroAcp(cmd("ok"), projeto.parent / "ws", timeout_prompt=60, timeout_handshake=10,
                           perfil_de=lambda: PerfilTrabalho(nivel="total", testes_timeout_s=120))
    t = {**_tarefa("alteracao_codigo"), "criterios_aceite": ["testes passam"], "politicas": {"complexidade": "simples"},
         "projeto_ctx": {"projeto": "P", "pastas": [{"caminho": str(projeto), "papel": "trabalho"}], "anexos": []}}
    r = prov.executar(t, {}, _ctl(eventos))
    testes = [p for tp, p in eventos if tp == "kiro.testes_forja"]
    assert testes and testes[-1]["ok"] is False  # rodou de verdade
    assert r.estado == "bloqueada" and r.consumo.chamadas_modelo == 1  # simples: sem turno de correcao, mas nao 'concluida'


def test_criterio_de_testes_sem_prova_nao_conclui(tmp_path):
    p = tmp_path / "semtestes"
    p.mkdir()
    prov = ProvedorKiroAcp(cmd("ok"), tmp_path / "ws", timeout_prompt=60, timeout_handshake=10, perfil_de=lambda: TOTAL)
    t = {**_tarefa("alteracao_codigo"), "criterios_aceite": ["testes passam"],
         "projeto_ctx": {"projeto": "P", "pastas": [{"caminho": str(p), "papel": "trabalho"}], "anexos": []}}
    r = prov.executar(t, {}, _ctl([]))
    assert r.estado == "bloqueada" and any(x.startswith("testes_sem_prova") for x in r.pendencias)


def test_python_da_venv_acima_e_lint_declarado(tmp_path):
    (tmp_path / ".venv" / "Scripts").mkdir(parents=True)
    exe = tmp_path / ".venv" / "Scripts" / "python.exe"
    exe.write_text("", encoding="utf-8")
    copia = tmp_path / PASTA / "x"
    copia.mkdir(parents=True)
    assert V._python_do_projeto(copia) == str(exe)
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n", encoding="utf-8")
    lint = V.detectar_lint(tmp_path)
    if lint is not None:  # ruff instalado (dev): so os .py alterados
        assert V.lint_dos_alterados(lint, ["a.py", "b.md"]).args[-1] == "a.py" and V.lint_dos_alterados(lint, ["b.md"]) is None


# ------------------------------------------------------------------ creditos reais (E2)
def test_creditos_acumulados_por_sessao():
    med: dict = {"sessoes": {}, "base": {}}
    for v in (0.001, 0.002, 0.003):
        registrar_creditos(med, "s1", {"_meta": {"kiro": {"kind": "session_usage", "credits": [{"usage": v, "unit": "credit"}]}}})
    registrar_creditos(med, "s2", {"_meta": {"kiro": {"kind": "session_usage", "credits": [{"usage": 0.005, "unit": "credit"}]}}})
    registrar_creditos(med, "s1", {"_meta": {"kiro": {"kind": "context_usage"}}})
    med["base"]["s2"] = 0.001  # sessao reaberta: o que ja havia nao conta
    assert medir_creditos(med) == pytest.approx(0.007) and medir_creditos({"sessoes": {}}) is None


def test_execucao_traz_creditos_medidos_e_processo_e_reaproveitado(tmp_path):
    pool = PoolAcp()
    eventos: list = []
    prov = ProvedorKiroAcp(cmd("creditos"), tmp_path / "ws", timeout_prompt=30, timeout_handshake=10)
    prov.pool = pool
    r1 = prov.executar(_tarefa(), {}, _ctl(eventos))
    r2 = prov.executar(_tarefa(), {}, _ctl(eventos))
    assert r1.consumo.creditos == pytest.approx(0.01)
    assert r2.consumo.creditos == pytest.approx(0.01)  # 2a execucao no MESMO processo, sessao nova: so o consumo dela
    conectados = [p for tp, p in eventos if tp == "kiro.conectado"]
    assert [c["reaproveitado"] for c in conectados] == [False, True] and pool.estatisticas["reaproveitados"] == 1
    pool.encerrar_todos()
    assert pool.ociosos() == 0


def test_pool_descarta_processo_com_falha(tmp_path):
    pool = PoolAcp()
    c = pool.obter(cmd("ok"), None, str(tmp_path), lambda p: None, None, None, 10)
    pool.devolver(c, saudavel=False)
    assert pool.ociosos() == 0 and not c.vivo()
    c2 = pool.obter(cmd("ok"), None, str(tmp_path), lambda p: None, None, None, 10)
    pool.devolver(c2, saudavel=True)
    assert pool.ociosos() == 1
    c3 = pool.obter(cmd("ok"), {**os.environ, "OUTRO": "1"}, str(tmp_path), lambda p: None, None, None, 10)  # outro ambiente: outro processo
    assert c3 is not c2
    pool.devolver(c3, saudavel=True)
    pool.encerrar_todos()


def test_custos_usam_creditos_medidos(servico, relogio):
    from forja.adapters.sqlite import tabelas as T
    from forja.adapters.sqlite.repositorio import novo_id
    from forja.dominio.contratos import ObjetivoIn, ProjetoIn, TarefaIn
    from forja.dominio.tempo import iso
    from forja.orquestracao.custos import CustosServico

    p, _ = servico.criar_projeto(ProjetoIn(nome="custo"))
    o, _ = servico.criar_objetivo(ObjetivoIn(projeto_id=p["id"], titulo="o"))
    ta, _ = servico.criar_tarefa(TarefaIn(objetivo_id=o["id"], titulo="t", criterios_aceite=["a"]))
    with servico.repo.escrita() as t:
        t.inserir(T.Execucao, id=novo_id("EX"), tarefa_id=ta["id"], estado="concluida", agente_id="kiro.acp.v3", tentativa=1, checkpoint={},
                  correlation_id=ta["correlation_id"], criado_em=iso(relogio.agora()),
                  resultado={"consumo": {"chamadas_modelo": 2, "creditos": 0.0123}, "mock": False})
    painel = CustosServico(servico.repo, relogio=relogio).painel(7)
    assert painel["total"]["creditos_medidos"] == pytest.approx(0.0123) and painel["total"]["execucoes_medidas"] == 1
    assert painel["estimativa"] is False and painel["cobertura_medida"] == 1.0


# ------------------------------------------------------------------ copia sem segredos
def _projeto_com_env(tmp_path: Path) -> Path:
    p = tmp_path / "proj"
    (p / "src").mkdir(parents=True)
    (p / "node_modules" / "lib").mkdir(parents=True)
    (p / ".env").write_text("TOKEN=valor_ficticio\n", encoding="utf-8")
    (p / "secrets").mkdir()
    (p / "secrets" / "k.txt").write_text("x", encoding="utf-8")
    (p / "src" / "a.py").write_text("a = 1\n", encoding="utf-8")
    (p / "src" / "b.py").write_text("b = 1\n", encoding="utf-8")
    (p / "src" / "c.py").write_text("c = 1\n", encoding="utf-8")
    (p / "node_modules" / "lib" / "i.js").write_text("x", encoding="utf-8")
    return p


def test_copia_sem_segredos_e_devolucao(tmp_path):
    p = _projeto_com_env(tmp_path)
    cs = CopiasSemSegredos()
    assert cs.precisa("total", "alteracao_codigo", p) and not cs.precisa("restrito", "alteracao_codigo", p)
    assert not cs.precisa("total", "analise", p)
    c = cs.criar("EX-1", p)
    assert c is not None and c.destino.parent.name == PASTA
    assert not (c.destino / ".env").exists() and not (c.destino / "secrets").exists() and not (c.destino / "node_modules").exists()
    assert (c.destino / "src" / "a.py").is_file()
    (c.destino / "src" / "a.py").write_text("a = 2\n", encoding="utf-8")  # alterado pelo agente
    (c.destino / "src" / "novo.py").write_text("n = 1\n", encoding="utf-8")  # criado
    (c.destino / "src" / "c.py").unlink()  # apagado
    (c.destino / ".env").write_text("X=1\n", encoding="utf-8")  # segredo criado pelo agente: nao volta
    (p / "src" / "b.py").write_text("b = voce\n", encoding="utf-8")  # voce mexeu no original...
    (c.destino / "src" / "b.py").write_text("b = agente\n", encoding="utf-8")  # ...e o agente tambem: conflito
    r = cs.sincronizar("EX-1")[0]
    assert r["aplicados"] == ["src/a.py"] and r["criados"] == ["src/novo.py"] and r["removidos"] == ["src/c.py"]
    assert r["conflitos"] == ["src/b.py"] and r["segredos_ignorados"] == 1 and r["copia_mantida"]
    assert (p / "src" / "a.py").read_text(encoding="utf-8") == "a = 2\n" and (p / "src" / "b.py").read_text(encoding="utf-8") == "b = voce\n"
    assert (p / ".env").read_text(encoding="utf-8") == "TOKEN=valor_ficticio\n" and not (p / "src" / "c.py").exists()


def test_servico_roda_o_agente_na_copia(tmp_path, servico):
    """Integracao: o agente ve a copia (sem .env) e o que ele escreve chega a pasta original."""
    p = _projeto_com_env(tmp_path)
    vistos: dict = {}

    class _Agente:
        id, mock = "teste.copia", False

        def executar(self, tarefa, checkpoint, ctl):  # noqa: ANN001, ANN201
            pasta = Path(tarefa["projeto_ctx"]["pastas"][0]["caminho"])
            vistos["pasta"], vistos["env"] = pasta, (pasta / ".env").exists()
            (pasta / "src" / "feito.py").write_text("ok = 1\n", encoding="utf-8")
            return ResultadoAgente(estado="falhou", resumo="fim", agente_id=self.id)

    s = servico
    s.provedor = _Agente()
    s.copias = CopiasSemSegredos()
    s.perfil_de = lambda: TOTAL
    tarefa = {"id": "T-1", "modo": "alteracao_codigo", "projeto_ctx": {"pastas": [{"caminho": str(p), "papel": "trabalho"}]}}
    assert s._preparar_pastas("EX-9", tarefa) is None
    res = s.provedor.executar(tarefa, {}, None)
    res = s._devolver_copias("EX-9", res)
    assert vistos["env"] is False and PASTA in str(vistos["pasta"])
    assert (p / "src" / "feito.py").is_file() and not (p / PASTA).exists()
    assert any("cópia" in m.conteudo for m in res.mensagens)


# ------------------------------------------------------------------ novas ferramentas
@pytest.fixture
def repo_git(tmp_path: Path) -> Path:
    r = tmp_path / "r"
    r.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}

    def git(*a: str) -> None:
        subprocess.run(["git", *a], cwd=r, env=env, check=True, capture_output=True)

    git("init", "-q")
    (r / "app.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (r / ".env").write_text("TOKEN=valor_ficticio_versionado\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "inicio")
    (r / "app.py").write_text("def f():\n    return 2  # TODO\n", encoding="utf-8")
    (r / ".env").write_text("TOKEN=outro_valor_ficticio\n", encoding="utf-8")
    return r


def test_codigo_buscar_pula_segredos(repo_git):
    cat = Catalogo(raizes=(repo_git,))
    r = cat.executar("codigo.buscar", {"padrao": "TODO|TOKEN", "regex": True})
    assert [o["arquivo"] for o in r["dados"]["ocorrencias"]] == ["app.py"] and "valor_ficticio" not in r["resumo"]
    assert r["dados"]["segredos_pulados"] == 1
    with pytest.raises(Exception, match="aninhado"):
        cat.executar("codigo.buscar", {"padrao": "(a+)+", "regex": True})
    with pytest.raises(Exception, match="fora da raiz"):
        cat.executar("codigo.buscar", {"padrao": "x", "caminho": "../"})


def test_git_ler_nunca_mostra_segredo(repo_git):
    cat = Catalogo(raizes=(repo_git,))
    st = cat.executar("git.ler", {"operacao": "status"})
    assert [i["arquivo"] for i in st["dados"]["alterados"]] == ["app.py"] and "segredo" in st["avisos"][0]
    d = cat.executar("git.ler", {"operacao": "diff"})
    assert "return 2" in d["resumo"] and "valor_ficticio" not in d["resumo"] and ".env" not in d["resumo"]
    assert cat.executar("git.ler", {"operacao": "log"})["dados"]["commits"][0]["assunto"] == "inicio"
    with pytest.raises(Exception, match="ref invalido"):
        cat.executar("git.ler", {"operacao": "show", "ref": "HEAD:.env"})
    with pytest.raises(Exception, match="sensivel"):
        cat.executar("git.ler", {"operacao": "blame", "arquivo": ".env"})


def test_resumo_de_testes_de_outros_executores():
    assert resumir_testes("Tests:       1 failed, 3 passed, 4 total\n").dados["veredito"] == "REPROVADO"
    assert resumir_testes("--- FAIL: TestSoma (0.00s)\nFAIL\texemplo/calc\t0.01s\n").dados["falhas"][0]["id"] == "TestSoma"
    assert resumir_testes("running 1 test\ntest result: ok. 1 passed; 0 failed; 0 ignored\n").dados["veredito"] == "APROVADO"
    assert resumir_testes(" Test Files  1 passed (1)\n      Tests  2 passed (2)\n").dados["formato"] == "vitest"


def test_fallback_de_estrutura_para_mapa_funciona(tmp_path):
    (tmp_path / "vazia").mkdir()
    (tmp_path / "vazia" / "dados.bin").write_bytes(b"\x00\x01")
    r = Catalogo(raizes=(tmp_path,)).executar("codigo.estrutura", {"caminho": "vazia", "operacao": "mapa", "limite": 5})
    assert r["fallback_de"] == "codigo.estrutura" and r["ferramenta"] == "repo.mapa"


# ------------------------------------------------------------------ roteador inteligente
@pytest.mark.parametrize(("tarefa", "esperado"), [
    ({"titulo": "Explique como funciona o login", "modo": "analise"}, "codex"),
    ({"titulo": "Refatore o modulo de pagamentos", "modo": "alteracao_codigo"}, "kiro"),
    ({"titulo": "Adicione validacao de email", "modo": "alteracao_codigo"}, "kiro"),
    ({"titulo": "Rodar e diagnosticar os testes", "modo": "verificacao"}, "codex"),
    ({"titulo": "Estudar a pasta", "modo": "estudo"}, "kiro"),
    ({"titulo": "Revisar", "modo": "analise", "entrada": {"revisao": {"autor": "kiro.acp.v3"}}}, "codex"),
    ({"titulo": "Revisar", "modo": "analise", "entrada": {"revisao": {"autor": "codex.acp"}}}, "kiro"),
    ({"titulo": "Turno", "modo": "analise", "entrada": {"coordenacao": {"prompt": "x"}}}, "kiro"),
    ({"titulo": "Ajustar a interface do painel", "modo": "alteracao_codigo"}, "kiro"),
])
def test_decisao_inteligente(tarefa, esperado):
    assert decidir_inteligente({"criterios_aceite": ["ok"], **tarefa})[0] == esperado


def test_roteador_inteligente_registra_o_motivo_e_respeita_segredos(tmp_path):
    class _Ag:
        def __init__(self, i: str) -> None:
            self.id, self.mock, self.comando, self.n = i, False, ["x"], 0

        def executar(self, tarefa, checkpoint, ctl):  # noqa: ANN001, ANN201
            self.n += 1
            return ResultadoAgente(estado="concluida", resumo="ok", agente_id=self.id)

    k, c = _Ag("kiro.acp.v3"), _Ag("codex.acp")
    r = ProvedoresRoteados(k, c)
    eventos: list = []
    simples = {"id": "T", "titulo": "Explique como funciona o login", "modo": "analise", "criterios_aceite": ["ok"]}
    assert r.executar(simples, {}, _ctl(eventos)).agente_id == "codex.acp"
    assert "simples" in next(p for tp, p in eventos if tp == "provedor.escolhido")["motivo"]
    p = tmp_path / "p"
    p.mkdir()
    (p / ".env").write_text("A=1\n", encoding="utf-8")
    com_segredo = {**simples, "projeto_ctx": {"pastas": [{"caminho": str(p), "papel": "trabalho"}]}}
    eventos.clear()
    assert r.executar(com_segredo, {}, _ctl(eventos)).agente_id == "kiro.acp.v3"
    assert "segredo" in next(p for tp, p in eventos if tp == "provedor.escolhido")["motivo"]

