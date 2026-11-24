"""Inspeciona o painel num navegador real (Playwright + Edge/Chromium): erros de console/CSP, elementos-chave e capturas.

Opcional: Playwright NAO e dependencia do projeto (pip install playwright). Uso:
  python scripts/inspecionar_painel.py [--porta 8787] [--saida pasta] [--token TOKEN]
Use com um servidor semeado por scripts/semear_demo.py (dados sinteticos).
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import traceback
from pathlib import Path

PROIBIDA = str(Path(tempfile.gettempdir()) / "pasta-ficticia-proibida")  # absoluta em qualquer SO (Windows e CI Linux)
INEXISTENTE = str(Path(tempfile.gettempdir()) / "nao-existe-xyz-forja")
NO_CI = bool(os.environ.get("GITHUB_ACTIONS"))
ultimo_passo = ["(inicio)"]  # para dizer DEPOIS de qual passo um erro HTTP aconteceu


def anotar(titulo: str, msg: str) -> None:
    """No GitHub Actions, falhas viram anotacoes legiveis sem login."""
    if NO_CI:
        print(f"::error title={titulo[:80]}::{' '.join(msg.split())[:300]}")

VISTAS = {
    "master": ".master-grade .arvore-coord",
    "tarefas": ".kanban .coluna",
    "quadro": ".faixas .faixa",
    "memoria": ".grafo-caixa svg .no",
    "ferramentas": ".lista-notas button",
    "integracoes": ".grade .card",
    "custos": ".custos .metricas",
    "config": "#janela-config .opcao",
    "inicio": ".boas-vindas .bv-grade",
    "explorador": "#lateral-corpo .arvore",
    "chat": ".chat-grade .chat-fios",
    "agentes": ".escritorio canvas.escritorio-cena",
    "http": ".http-grade .barra-url",
    "comandos": ".catalogo-grade .lista-catalogo",
    "aprender": ".grade-conhecimento form",
    "organizar": ".conhecimento-aba .metricas-saude",
    "pastas": ".grade-pastas .arvore-pastas",
    "revisao": ".conhecimento-aba .revisao",
}


def login(nav, base: str, saida: Path, a11y: bool) -> int:
    """Tela de acesso num servidor COM login (servidor novo, sem conta): primeiro acesso, erros, sucesso, sair, bloqueio."""
    from playwright.sync_api import expect

    falhas = 0

    def passo(nome: str, condicao: bool) -> None:
        nonlocal falhas
        print(f"  [{'OK' if condicao else 'FALHA'}] login: {nome}")
        falhas += 0 if condicao else 1
        if not condicao:
            anotar("tela de login", nome)

    ctx = nav.new_context(viewport={"width": 1280, "height": 860})
    pg = ctx.new_page()
    erros: list[str] = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(base)
    tela = pg.locator("#tela-login")
    expect(tela).to_be_visible(timeout=8000)
    passo("servidor sem conta abre o primeiro acesso (por cima do painel inerte)",
          "Primeiro acesso" in tela.inner_text() and pg.evaluate("document.querySelector('#area').inert"))
    pg.screenshot(path=str(saida / "login-primeiro-acesso.png"))
    pg.get_by_label("Usuário").fill("ana")
    pg.locator("#login-senha").fill("uma frase longa e boa")
    pg.locator("#login-senha2").fill("outra frase diferente")
    pg.get_by_role("button", name="Criar acesso e entrar").click()
    passo("senhas diferentes: aviso claro sem enviar", "não conferem" in pg.locator(".login-erro").inner_text())
    pg.locator("#login-senha").fill("12345678")
    pg.locator("#login-senha2").fill("12345678")
    pg.get_by_role("button", name="Criar acesso e entrar").click()
    expect(pg.locator(".login-erro")).to_contain_text("fácil", timeout=6000)
    passo("senha comum: o servidor recusa e a tela explica", True)
    pg.locator("#login-senha").fill("uma frase longa e boa")
    passo("medidor de forca da senha reage", pg.locator(".forca meter").get_attribute("value") not in (None, "0"))
    pg.locator("#login-senha2").fill("uma frase longa e boa")
    pg.get_by_role("button", name="Mostrar senha").click()
    passo("mostrar/esconder senha", pg.locator("#login-senha").get_attribute("type") == "text")
    pg.get_by_role("button", name="Criar acesso e entrar").click()
    expect(tela).to_contain_text("Bem-vindo, ana", timeout=6000)
    pg.screenshot(path=str(saida / "login-sucesso.png"))
    expect(tela).to_be_hidden(timeout=6000)
    expect(pg.locator(".boas-vindas .bv-grade").first).to_be_visible(timeout=8000)  # tela inicial: Boas-vindas da bancada
    passo("primeiro acesso cria a conta, mostra sucesso e abre o painel", pg.locator("#usuario-atual").inner_text() == "ana")
    pg.locator("#usuario-atual").click()
    pg.get_by_role("button", name="Sair da conta").click()
    expect(tela).to_be_visible(timeout=8000)
    passo("sair volta para a tela 'Entrar'", "Entrar" in tela.locator("h1").inner_text())
    pg.get_by_label("Usuário").fill("ana")
    pg.locator("#login-senha").fill("senha-errada-1")
    pg.get_by_role("button", name="Entrar", exact=True).click()
    expect(pg.locator(".login-erro")).to_contain_text("incorretos", timeout=6000)
    passo("senha errada: erro visivel (role=alert) e o painel continua fechado", pg.locator(".login-erro").get_attribute("role") == "alert"
          and tela.is_visible())
    pg.screenshot(path=str(saida / "login-erro.png"))
    if a11y:
        from axe_playwright_python.sync_playwright import Axe

        ctx2 = nav.new_context(viewport={"width": 1280, "height": 860}, bypass_csp=True)
        p2 = ctx2.new_page()
        p2.goto(base)
        p2.locator("#tela-login").wait_for(state="visible")
        p2.wait_for_timeout(700)  # o cartao entra com animacao de opacidade: no meio dela o contraste medido cai
        r = Axe().run(p2, options={"runOnly": {"type": "tag", "values": ["wcag2a", "wcag2aa", "wcag21aa"]}})
        graves = [v for v in r.response.get("violations", []) if v.get("impact") in ("critical", "serious")]
        print(f"  [a11y] login        violacoes={len(r.response.get('violations', []))} graves={len(graves)}")
        for v in graves:
            alvos = [str(n.get("target")) for n in v.get("nodes", [])[:3]]
            print(f"      {v.get('impact')}: {v.get('id')} {alvos}")
            anotar("acessibilidade da tela de login", f"{v.get('impact')}: {v.get('id')} em {alvos}")
        falhas += len(graves)
        ctx2.close()
    pg.locator("#login-senha").fill("uma frase longa e boa")
    pg.get_by_role("button", name="Entrar", exact=True).click()
    expect(tela).to_be_hidden(timeout=8000)
    passo("senha certa entra no painel", pg.locator("#usuario-atual").inner_text() == "ana")
    pg.evaluate("sessionStorage.setItem('forja_token', 'sessao-que-nao-existe-mais')")
    pg.reload()
    expect(tela).to_be_visible(timeout=8000)
    passo("sessao invalida/expirada volta para o login", "Entrar" in tela.locator("h1").inner_text())
    for _ in range(5):
        pg.get_by_label("Usuário").fill("ana")
        pg.locator("#login-senha").fill("senha-errada-2")
        pg.get_by_role("button", name="Entrar", exact=True).click()
        pg.wait_for_timeout(250)
    pg.locator("#login-senha").fill("senha-errada-2")
    pg.locator(".login-botao").click()
    expect(pg.locator(".login-botao")).to_contain_text("Aguarde", timeout=6000)
    passo("bloqueio apos erros seguidos mostra contagem regressiva e desativa o botao", pg.locator(".login-botao").is_disabled())
    pg.screenshot(path=str(saida / "login-bloqueio.png"))
    passo("sem erro de JavaScript", not erros)
    ctx.close()
    return falhas


def melhorias(pagina, base: str, saida: Path, expect, passo) -> None:
    """9.x: desfazer por tarefa, copias isoladas, painel de custo, fila de revisao do segundo cerebro, regras e oficina."""
    pagina.goto(base + "#/tarefas")
    pagina.reload()
    pagina.wait_for_selector(".cartao")
    fechar_menu(pagina)
    cartao = pagina.locator(".cartao", has_text="Gerar arquivo de notas")
    passo("demo de desfazer semeada (cartao com 'Desfazer alteracoes')", cartao.get_by_role("button", name="Desfazer alterações").count() == 1)
    if cartao.get_by_role("button", name="Desfazer alterações").count():
        cartao.get_by_role("button", name="Desfazer alterações").click()
        expect(pagina.locator("#dlg-geral")).to_contain_text("Criados (serão apagados) (1)", timeout=6000)
        pagina.screenshot(path=str(saida / "desfazer.png"))
        pagina.locator("#dlg-geral").get_by_role("button", name="Desfazer esta execução").click()
        expect(pagina.locator("#dlg-geral")).to_contain_text("desfeito", timeout=6000)
        passo("desfazer remove o arquivo criado pela tarefa e marca o ponto como desfeito", True)
        pagina.locator("#dlg-geral").get_by_role("button", name="Fechar", exact=True).click()
        expect(cartao.get_by_role("button", name="Desfazer alterações")).to_have_count(0, timeout=6000)
        passo("cartao perde 'Desfazer' depois de desfeito", True)
    abrir_menu(pagina)
    pagina.get_by_role("button", name="Cópias isoladas…").click()
    expect(pagina.locator("#dlg-geral")).to_contain_text("Nenhuma cópia isolada ativa", timeout=6000)
    passo("copias isoladas (git worktree) listadas pela tela", True)
    pagina.locator("#dlg-geral").get_by_role("button", name="Fechar", exact=True).click()
    fechar_menu(pagina)

    pagina.goto(base + "#/custos")
    pagina.reload()
    pagina.wait_for_selector(".custos .metricas .metrica")
    passo("painel de custo mostra totais estimados e a nota de estimativa", "Estimativa" in pagina.locator(".custos").inner_text())
    pagina.get_by_label("Período").select_option("7")
    expect(pagina.locator(".custos .barras, .custos-corpo")).not_to_have_count(0, timeout=6000)
    passo("trocar o periodo recarrega o painel", pagina.locator(".custos h2", has_text="Por modelo").count() == 1)
    passo("roteamento aprendido aparece no painel de custo", pagina.locator(".custos", has_text="Roteamento que aprende").count() == 1)
    pagina.screenshot(path=str(saida / "custos.png"))

    pagina.goto(base + "#/memoria")
    pagina.reload()
    pagina.wait_for_selector(".grafo-caixa svg .no")
    expect(pagina.locator("#botao-revisao")).to_contain_text("Revisão (", timeout=6000)
    passo("botao 'Revisao (N)' mostra o tamanho da fila", True)
    pagina.locator("#botao-revisao").click()
    janela_rev = pagina.locator("dialog.janela[open]", has_text="Revisão do segundo cérebro")
    janela_rev.get_by_role("button", name="Organizar agora").click()
    pagina.wait_for_selector(".toast.ok", timeout=8000)
    pagina.wait_for_timeout(500)
    dups = janela_rev.locator(".sugestao", has_text="Duplicata").count()
    passo("organizar agora sugere unir a duplicata semeada (sem alterar nada sozinho)", dups >= 1)
    pagina.screenshot(path=str(saida / "revisao.png"))
    if dups:
        janela_rev.locator(".sugestao", has_text="Duplicata").first.get_by_role("button", name="Unir").click()
        expect(janela_rev.locator(".sugestao", has_text="Duplicata")).to_have_count(dups - 1, timeout=6000)  # sugestoes da nota unida somem junto
        passo("aceitar a duplicata une as notas (a outra vira 'substituida')", True)
    cands = janela_rev.locator(".candidata").count()
    passo("notas candidatas aparecem na fila de revisao", cands >= 1)
    if cands:
        janela_rev.locator(".candidata").first.get_by_role("button", name="Promover (observada)").click()
        expect(janela_rev.locator(".candidata")).to_have_count(cands - 1, timeout=6000)
        passo("promover nota candidata a tira da fila", True)
    janela_rev.get_by_role("button", name="Fechar janela").click()

    pagina.goto(base + "#/config")
    pagina.reload()
    pagina.wait_for_selector(".opcao")
    pagina.get_by_role("button", name="Segurança", exact=True).click()
    regras = pagina.locator('[data-pref="regras_controle"]')
    regras.get_by_role("button", name="+ Regra").click()
    regras.get_by_label("Nome da regra 1").fill("proteger migracoes")
    regras.get_by_label("Tipo de ação da regra 1").select_option("modificar_arquivos")
    regras.get_by_label("Caminho da regra 1").fill("*migrations*")
    regras.get_by_label("Decisão da regra 1").select_option("perguntar")
    pagina.get_by_role("button", name="Salvar alterações").click()
    pagina.wait_for_selector(".toast.ok", timeout=6000)
    passo("regra de controle criada e salva pela tela", regras.get_by_label("Nome da regra 1").input_value() == "proteger migracoes")
    pagina.screenshot(path=str(saida / "config-regras.png"))
    regras.get_by_role("button", name="Remover regra 1").click()
    pagina.get_by_role("button", name="Salvar alterações").click()
    expect(regras).to_contain_text("Nenhuma regra", timeout=6000)
    passo("remover regra", True)
    pagina.get_by_role("button", name="Agentes", exact=True).click()
    pagina.get_by_role("tab", name="Avançadas", exact=False).click()
    passo("preferencias novas (desfazer, worktree, subagentes, retomada, isolamento) aparecem em Agentes > Avancadas",
          all(pagina.locator(f'[data-pref="{p}"]').count() == 1 for p in
              ("pontos_restauracao", "isolar_paralelas", "subagentes", "roteamento_aprende", "retomar_apos_queda", "isolamento_testes")))
    pagina.get_by_role("button", name="Eficiência", exact=True).click()
    pagina.get_by_role("tab", name="Avançadas", exact=False).click()
    pacote = pagina.locator('[data-pref="pacotes_conhecimento"] input[type=checkbox][value="fastapi"]')
    passo("pacotes de conhecimento opcionais listados (FastAPI)", pacote.count() == 1
          and pagina.locator('[data-pref="organizacao_memoria"] select').count() == 1)
    pacote.check()
    pagina.get_by_role("button", name="Salvar alterações").click()
    pagina.wait_for_selector(".toast.ok", timeout=8000)
    passo("instalar pacote pela tela", pacote.is_checked())
    pacote.uncheck()
    pagina.get_by_role("button", name="Salvar alterações").click()
    pagina.get_by_role("button", name="Manutenção", exact=True).click()
    pagina.get_by_role("tab", name="Avançadas", exact=False).click()
    passo("telemetria OpenTelemetry configuravel (desligada por padrao)",
          pagina.locator('[data-pref="telemetria"] select').input_value() == "desligada")
    pagina.get_by_role("button", name="Ver o que seria reciclado").click()
    expect(pagina.locator('[data-pref="reciclagem_agora"] .mudo, [data-pref="reciclagem_agora"] .lista-reciclagem').first).to_be_visible(timeout=6000)
    passo("reciclagem de sessoes antigas mostra a previa antes de reciclar", True)
    # Editor (ADR-027): assistentes ligaveis, servidores de linguagem com instalacao e catalogo por ramos
    pagina.get_by_role("button", name="Editor", exact=True).click()
    pagina.get_by_role("tab", name="Gerais", exact=False).click()
    lsp = pagina.locator('[data-pref="lsp_servidores"]')
    expect(lsp.locator(".linha-lsp", has_text="Pyright")).to_be_visible(timeout=6000)
    passo("servidores de linguagem listados com estado e botao de instalar (Python, JS/TS, HTML, CSS, C#)",
          lsp.locator(".linha-lsp").count() == 5)
    passo("assistentes de autocompletar e do terminal sao ligaveis", pagina.locator('[data-pref="autocompletar_codigo"] input[type=checkbox]').is_checked()
          and pagina.locator('[data-pref="terminal_assistente"] input[type=checkbox]').count() == 1)
    pagina.get_by_role("tab", name="Avançadas", exact=False).click()
    cat = pagina.locator('[data-pref="catalogo_codigo"]')
    expect(cat.locator("tbody tr").first).to_be_visible(timeout=6000)
    passo("catalogo de autocompletar por ramo (inclui pandas, LINQ, DOM, CSS)", all(cat.locator("tbody", has_text=t).count() == 1
                                                                                 for t in ("pandas", "LINQ", "DOM", "Propriedades")))
    passo("fontes das sugestoes configuraveis (LSP, catalogo, trechos, palavras)",
          pagina.locator('[data-pref="autocompletar_fontes"] input[type=checkbox]').count() == 4)
    pagina.screenshot(path=str(saida / "config-editor.png"))
    pagina.keyboard.press("Escape")

    pagina.goto(base + "#/tarefas")
    pagina.reload()
    pagina.wait_for_selector(".cartao")
    fechar_menu(pagina)
    pagina.keyboard.press("Control+j")
    expect(pagina.locator("#inferior")).to_be_visible(timeout=3000)
    pagina.get_by_role("tab", name="Oficina").click()
    pagina.wait_for_selector(".oficina .of-agente", timeout=8000)
    passo("oficina mostra um personagem por execucao ativa, com papel e barra de orcamento",
          pagina.locator(".oficina .of-agente meter.orcamento").count() >= 1 and pagina.locator('.oficina .of-agente[class*="papel-"]').count() >= 1)
    passo("descricao em texto para leitores de tela (aria-live)", "agente" in pagina.locator(".oficina-raiz [aria-live]").first.inner_text().lower())
    pagina.screenshot(path=str(saida / "oficina.png"))
    pagina.locator(".oficina .of-corpo").first.focus()
    pagina.keyboard.press("End")
    passo("setas/Home/End navegam entre os personagens", pagina.evaluate("document.activeElement.classList.contains('of-corpo')"))
    pagina.locator(".oficina .of-agente").first.get_by_role("button", name="Replay", exact=False).click()
    pagina.wait_for_selector(".replay .replay-legenda", timeout=6000)
    pagina.get_by_label("Velocidade").select_option("8")
    pagina.locator(".replay").get_by_role("button", name="Próximo quadro").click()
    passo("replay da execucao com reproduzir/pausar, passos e velocidade", pagina.locator(".replay-legenda").inner_text().strip() != "")
    pagina.screenshot(path=str(saida / "oficina-replay.png"))
    pagina.get_by_role("button", name="Fechar replay").click()
    balao = pagina.locator(".oficina .balao.clicavel").first
    passo("balao 'aguardando voce' aparece na tarefa que espera decisao", balao.count() == 1)
    if balao.count():
        balao.click()
        expect(pagina.locator("#direita")).to_be_visible(timeout=4000)
        passo("clicar no balao abre as decisoes da tarefa", pagina.get_by_role("tab", name="Decisões", exact=False).get_attribute("aria-selected") == "true")
    pagina.keyboard.press("Control+j")


def _contexto(nav, a, **kw):
    ctx = nav.new_context(**kw)
    if a.token:
        ctx.add_init_script(f"sessionStorage.setItem('forja_token', {a.token!r})")
    return ctx


def auditar_a11y(nav, base: str, a, saida: Path) -> int:
    """axe-core (WCAG 2.1 A/AA) em cada vista. Falha so em impacto critico/serio; o resto vira relatorio. CSP e contornada SO aqui
    (o axe e injetado pelo teste); a pagina real continua com a CSP inteira. Nao substitui teste com leitor de tela de verdade."""
    from axe_playwright_python.sync_playwright import Axe  # import tardio: dependencia de requirements-ui.txt

    ctx = _contexto(nav, a, viewport={"width": a.largura, "height": a.altura}, bypass_csp=True)
    pagina, axe, falhas, linhas = ctx.new_page(), Axe(), 0, []
    for vista, seletor in VISTAS.items():
        pagina.goto(f"{base}#/{vista}")
        pagina.reload()
        pagina.wait_for_selector(seletor, timeout=8000)
        pagina.wait_for_timeout(400)
        r = axe.run(pagina, options={"runOnly": {"type": "tag", "values": ["wcag2a", "wcag2aa", "wcag21aa"]}})
        violacoes = r.response.get("violations", [])
        graves = [v for v in violacoes if v.get("impact") in ("critical", "serious")]
        falhas += len(graves)
        print(f"  [a11y] {vista:<12} violacoes={len(violacoes)} graves={len(graves)}")
        for v in violacoes:
            alvos = [str(n.get("target")) for n in v.get("nodes", [])[:3]]
            linhas.append(f"{vista}\t{v.get('impact')}\t{v.get('id')}\t{len(v.get('nodes', []))}\t{'; '.join(alvos)}")
            if v in graves:
                print(f"      {v.get('impact')}: {v.get('id')} ({len(v.get('nodes', []))}) {alvos[:2]}")
    (saida / "a11y.tsv").write_text("vista\timpacto\tregra\tnos\talvos\n" + "\n".join(linhas), encoding="utf-8")
    ctx.close()
    return falhas


def estreito(nav, base: str, a, saida: Path) -> int:
    """Layout estreito (celular/janela dividida): nada pode estourar a largura da tela."""
    ctx = _contexto(nav, a, viewport={"width": 420, "height": 860})
    pagina, falhas = ctx.new_page(), 0
    for vista, seletor in VISTAS.items():
        pagina.goto(f"{base}#/{vista}")
        pagina.reload()
        pagina.wait_for_selector(seletor, timeout=8000, state="attached")  # na tela estreita a lateral pode estar recolhida
        pagina.wait_for_timeout(300)
        excesso = pagina.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        ok = excesso <= 2
        falhas += not ok
        print(f"  [{'OK' if ok else 'FALHA'}] estreito {vista}: estouro horizontal {excesso}px")
        pagina.screenshot(path=str(saida / f"estreito-{vista}.png"))
    ctx.close()
    return falhas


def integracoes(pagina, base: str, saida: Path, expect, passo) -> int:
    """Configura integracoes de rede pela tela. O Jira usa dados ficticios (host .example nunca resolve); o GitHub faz UMA
    chamada real de leitura (GET /rate_limit em api.github.com, sem token e sem enviar dados) para validar TLS e o fixador de IP."""
    pagina.goto(base + "#/integracoes")
    pagina.reload()
    pagina.wait_for_selector(".card")
    fechar_menu(pagina)
    jira = pagina.locator(".card", has_text="Jira (leitura de issues)")
    passo("integracoes de rede nascem desligadas", "desligada" in jira.inner_text() and jira.get_by_role("button", name="Testar conexão").is_disabled())
    jira.get_by_role("button", name="Configurar").click()
    passo("formulario avisa que segredo nunca e digitado", "Segredos nunca sao digitados" in pagina.locator("#dlg-geral").inner_text())
    pagina.get_by_label("Endereco do Jira", exact=True).fill("https://jira.forja-teste.example")
    pagina.get_by_label("Projetos permitidos", exact=True).fill("abc\nOPS")
    pagina.get_by_label("Variavel do token", exact=True).fill("ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8")  # token colado no lugar do nome
    pagina.get_by_label("Variavel do e-mail (so Cloud)").fill("FORJA_INT_JIRA_EMAIL")
    pagina.get_by_role("button", name="Salvar").click()
    campo = pagina.get_by_label("Variavel do token", exact=True)
    passo("token colado no campo do NOME e barrado pelo formulario (so FORJA_INT_*) antes de sair do navegador",
          campo.evaluate("el => el.validity.patternMismatch") and pagina.locator("#dlg-geral").is_visible())
    pagina.get_by_label("Variavel do token", exact=True).fill("FORJA_INT_JIRA_TOKEN")
    pagina.get_by_label("Ativar esta integracao").check()
    pagina.get_by_role("button", name="Salvar").click()
    expect(pagina.locator(".toast.ok").first).to_contain_text("Integracao salva", timeout=5000)
    pagina.wait_for_selector(".card:has-text('Jira (leitura de issues)') .tag")
    estado = pagina.locator(".card", has_text="Jira (leitura de issues)").inner_text()
    passo("sem as variaveis no ambiente a integracao fica nao pronta e diz o motivo", "faltam variaveis" in estado or "pronta" in estado)
    pagina.screenshot(path=str(saida / "integracoes.png"))

    gh = pagina.locator(".card", has_text="GitHub (issues e pull requests, leitura)")
    gh.get_by_role("button", name="Configurar").click()
    pagina.get_by_label("Repositorios permitidos", exact=True).fill("octocat/Hello-World")
    pagina.get_by_label("Ativar esta integracao").check()
    pagina.get_by_role("button", name="Salvar").click()
    expect(pagina.locator(".toast.ok").first).to_contain_text("Integracao salva", timeout=5000)
    gh = pagina.locator(".card", has_text="GitHub (issues e pull requests, leitura)")
    expect(gh.locator(".tag", has_text="pronta")).to_be_visible(timeout=5000)
    gh.get_by_role("button", name="Testar conexão").click()
    expect(pagina.locator(".toast", has_text="conexao e credencial validas").first).to_be_visible(timeout=20000)
    passo("teste real contra api.github.com valida TLS e IP fixado", True)
    return 0


def abrir_menu(pagina) -> None:
    """A barra lateral (estilo VS Code) EMPURRA o conteudo; o botao da barra de titulo (Ctrl+B) abre e recolhe."""
    if pagina.locator("#area").get_attribute("data-lateral") != "on":
        pagina.locator("#alternar-lateral").click()
    pagina.locator("#lateral").wait_for(state="visible")


def fechar_menu(pagina) -> None:
    from playwright.sync_api import expect

    expect(pagina.locator("dialog[open]")).to_have_count(0, timeout=8000)  # com janela aberta, o clique e da janela
    if pagina.locator("#area").get_attribute("data-lateral") == "on":
        pagina.locator("#alternar-lateral").click()
    pagina.locator("#lateral").wait_for(state="hidden")


def fluxo_master(pagina, base: str, saida: Path, expect, passo) -> None:
    """Conversa com o master (agente simulado): pedido -> tarefa criada e executada -> retorno -> consolidacao; abrir a tarefa."""
    pagina.goto(base + "#/master")
    pagina.reload()
    pagina.wait_for_selector(".master-grade .arvore-coord", timeout=8000)
    pagina.wait_for_timeout(300)
    antes = pagina.locator(".msg-coord.master").count()
    pagina.get_by_label("Seu pedido ao master").fill("Revise o projeto demo-master e diga o que achou")
    pagina.get_by_role("button", name="Enviar").click()
    expect(pagina.locator(".msg-coord.master")).to_have_count(antes + 2, timeout=20000)  # resposta + consolidacao do lote
    conversa = pagina.locator(".conversa-master").inner_text()
    passo("master responde, cria a tarefa e consolida quando ela termina", "Lote concluído" in conversa and "Concluída" in conversa)
    passo("a arvore mostra a tarefa criada pelo master", pagina.locator(".tarefas-coord li").count() >= 1)
    pagina.screenshot(path=str(saida / "master.png"))
    pagina.locator(".msg-coord .criadas button").first.click()
    expect(pagina.locator("#direita-corpo")).to_contain_text("Tarefa T-", timeout=8000)
    passo("clicar na tarefa criada abre a conversa dela", pagina.locator("#direita").is_visible())
    pagina.keyboard.press("Escape")


def bancada(pagina, base: str, saida: Path, expect, passo) -> None:
    """Bancada estilo VS Code: explorador (segredo visivel e marcado), editor (realce, autocompletar, salvar, conflito), problemas,
    previa, paleta, terminal com assistente (explica, completa, aponta erro e pergunta no perigoso), Git (preparar, commit, diff
    lado a lado), Requisicoes HTTP, Comandos/receitas, atalhos e as visualizacoes Chat e Agentes. Pasta temporaria ficticia."""
    import subprocess

    pasta = Path(tempfile.mkdtemp(prefix="forja-bancada-"))
    (pasta / "src").mkdir()
    (pasta / "src" / "app.py").write_text("def soma(a, b):\n    return a + b\n", encoding="utf-8")
    (pasta / "notas.md").write_text("# Notas da bancada\n\nTexto **fictício**.\n", encoding="utf-8")
    (pasta / "ruim.json").write_text('{"a": 1,,}\n', encoding="utf-8")
    (pasta / ".env").write_text("SEGREDO=ficticio\n", encoding="utf-8")
    (pasta / "lixo").mkdir()
    nome = f"Bancada {pasta.name}"
    proj = pagina.request.post(base + "api/v1/projetos", data={"nome": nome}).json()
    pagina.request.put(base + f"api/v1/projetos/{proj['id']}/pastas", data={"expected_version": proj.get("versao", 1),
                                                                            "pastas": [{"caminho": str(pasta), "papel": "trabalho"}]})
    # menu agrupado (ADR-028): 6 grupos + conta e configuracoes; membros viram abas
    pagina.goto(base + "#/memoria")
    pagina.reload()
    expect(pagina.locator("#vista .grupo-abas [role=tab]").first).to_be_visible(timeout=8000)
    # 6 grupos de navegacao (no maximo 7) em secoes; o rodape tem os atalhos (novo projeto, ajustes rapidos, conta, configuracoes)
    passo("barra de atividades: no maximo 7 grupos de navegacao, atalhos e conta no rodape",
          pagina.locator("#atividades .ativ-secao:not(.rodape) button").count() <= 7
          and pagina.locator("#atividades .ativ-secao.rodape button").count() <= 4)
    passo("Conhecimento junta grafo, aprender, pastas, organizar, revisao e ferramentas em abas",
          pagina.locator("#vista .grupo-abas [role=tab]").count() == 6 and pagina.locator("#atividades button[data-id=conhecimento][aria-current=page]").count() == 1)
    pagina.locator("#vista .grupo-abas [role=tab]", has_text="Organizar").click()
    expect(pagina.locator(".metricas-saude .medidor")).to_be_visible(timeout=8000)
    passo("organizar mostra a modularidade do grafo (nota 0-100, repeticao, orfas)", "modularidade" in pagina.locator(".medidor").inner_text())
    pagina.screenshot(path=str(saida / "conhecimento-organizar.png"))
    pagina.locator("#vista .grupo-abas [role=tab][aria-selected=true]").press("ArrowLeft")
    expect(pagina.locator(".grade-pastas .arvore-pastas")).to_be_visible(timeout=6000)
    passo("aba Pastas mostra a arvore de pastas do segundo cerebro com contagem (ADR-029)",
          pagina.locator(".arvore-pastas [role=treeitem]", has_text="pessoal").count() >= 1)
    pagina.screenshot(path=str(saida / "conhecimento-pastas.png"))
    pagina.locator("#vista .grupo-abas [role=tab][aria-selected=true]").press("ArrowLeft")
    expect(pagina.locator(".grade-conhecimento form")).to_be_visible(timeout=6000)
    passo("setas trocam a aba do grupo (Buscar e aprender com o formulario de estudo)", pagina.locator(".aba-editor").filter(has_text="Buscar e aprender").count() == 1)
    pagina.goto(base + "#/explorador")
    pagina.reload()
    expect(pagina.locator("#lateral .grupo-abas [role=tab]").first).to_be_visible(timeout=8000)
    passo("grupo Arquivos mostra Explorador e Buscar como abas na barra lateral", pagina.locator("#lateral .grupo-abas [role=tab]").count() == 2)
    raiz = pagina.locator(".raiz-projeto", has_text=nome)
    raiz.locator(".no-arvore.pasta").first.click()
    expect(raiz.locator(".no-arvore.arquivo", has_text="notas.md")).to_be_visible(timeout=6000)
    passo("explorador mostra o .env ao usuario, marcado como segredo", raiz.locator(".no-arvore.segredo", has_text=".env").count() == 1)
    raiz.locator(".no-arvore.segredo", has_text=".env").click()
    expect(pagina.locator(".faixa-segredo")).to_be_visible(timeout=6000)
    passo("abrir .env avisa que nao vai para os agentes nem para o log", "nunca o envia" in pagina.locator(".faixa-segredo").inner_text())
    raiz.locator(".no-arvore.pasta", has_text="src").click()
    raiz.locator(".no-arvore.arquivo", has_text="app.py").click()
    pagina.wait_for_selector(".editor .fonte", timeout=8000)
    passo("editor abre o arquivo com realce de sintaxe e numeros de linha",
          pagina.locator(".editor .realce .tk-kw").count() >= 1 and "2" in pagina.locator(".editor .numeros").inner_text())
    pagina.locator(".editor .fonte").click()
    pagina.keyboard.press("Control+End")
    pagina.keyboard.type("\nx = som")
    pagina.keyboard.press("Control+Space")
    expect(pagina.locator(".editor .completar-caixa li", has_text="soma").first).to_be_visible(timeout=4000)
    pagina.keyboard.press("Enter")
    passo("autocompletar sugere palavras do arquivo e completa com Enter", "x = soma" in pagina.locator(".editor .fonte").input_value())
    pagina.keyboard.type("  # editado pela bancada")
    passo("aba mostra alteracao nao salva", pagina.locator(".aba-editor.suja").count() == 1)
    pagina.keyboard.press("Control+s")
    expect(pagina.locator(".aba-editor.suja")).to_have_count(0, timeout=6000)
    passo("Ctrl+S salva no disco pela API da area de trabalho", "editado pela bancada" in (pasta / "src" / "app.py").read_text(encoding="utf-8"))
    # catalogo de autocompletar (ADR-027): membro depois de "os." com explicacao ao lado, e assinatura ao abrir parenteses
    pagina.keyboard.type("\nimport os\nv = os.ge")
    expect(pagina.locator(".editor .completar-caixa li", has_text="getenv").first).to_be_visible(timeout=4000)
    passo("autocompletar do catalogo entende o modulo (os.) e explica o item ao lado",
          "ambiente" in pagina.locator(".editor .completar-doc").inner_text())
    pagina.keyboard.press("Escape")
    pagina.keyboard.type("\nprint(")
    expect(pagina.locator(".editor .dica-codigo")).to_be_visible(timeout=4000)
    passo("abrir parenteses mostra a assinatura da funcao", "print(" in pagina.locator(".editor .dica-codigo").inner_text())
    pagina.keyboard.press("Escape")
    pagina.locator(".editor-barra button", has_text="Buscar").hover()
    expect(pagina.locator(".dica.visivel")).to_be_visible(timeout=3000)
    passo("botao mostra dica (tooltip) animada ao passar o mouse", "Ctrl+F" in pagina.locator(".dica.visivel").inner_text())
    pagina.mouse.move(5, 5)
    (pasta / "src" / "app.py").write_text("x = 'mudou fora'\n", encoding="utf-8")
    pagina.keyboard.type("\n# segunda")
    pagina.keyboard.press("Control+s")  # o confirm de recarregar e recusado (Playwright dispensa dialogos)
    pagina.wait_for_selector(".toast.erro", timeout=6000)
    passo("arquivo mudado fora do editor nao e sobrescrito (concorrencia otimista)",
          (pasta / "src" / "app.py").read_text(encoding="utf-8") == "x = 'mudou fora'\n")
    raiz.locator(".no-arvore.arquivo", has_text="ruim.json").click()
    expect(pagina.locator("#st-problemas")).to_contain_text("⊗ 1", timeout=6000)
    passo("JSON invalido vira problema na barra de status e na calha", pagina.locator(".marca-problema").count() >= 1)
    raiz.locator(".no-arvore.arquivo", has_text="notas.md").click()
    pagina.wait_for_selector(".editor[data-linguagem=markdown]", timeout=6000)
    pagina.get_by_role("button", name="Prévia").click()
    expect(pagina.locator(".previa h1")).to_have_text("Notas da bancada", timeout=4000)
    passo("previa de Markdown ao lado do codigo", True)
    pagina.screenshot(path=str(saida / "bancada-editor.png"))
    pagina.keyboard.press("Control+p")
    pagina.locator("#paleta-busca").fill("app")
    expect(pagina.locator(".paleta-op", has_text="app.py").first).to_be_visible(timeout=6000)
    pagina.keyboard.press("Enter")
    expect(pagina.locator(".aba-editor.ativa")).to_contain_text("app.py", timeout=4000)
    passo("Ctrl+P (abrir arquivo) encontra e abre o arquivo", True)

    # terminal com assistente
    pagina.keyboard.press("Control+Shift+P")
    pagina.locator("#paleta-busca").fill(">abrir terminal")
    pagina.keyboard.press("Enter")
    entrada = pagina.locator(".terminal-entrada")
    expect(entrada).to_be_visible(timeout=6000)
    entrada.fill("git log -n abc")
    expect(pagina.locator(".terminal-assist")).to_contain_text("inteiro", timeout=4000)
    passo("assistente aponta erro de tipo (opcao que espera inteiro)", "git log" in pagina.locator(".terminal-assist .assinatura").inner_text())
    entrada.fill("")
    entrada.type("git pu")
    expect(pagina.locator("#terminal-sugestoes li").first).to_be_visible(timeout=4000)
    entrada.press("Tab")
    passo("Tab completa o subcomando sugerido (como no Excel)", entrada.input_value() in ("git pull ", "git push "))
    entrada.fill("echo forja-ok")
    entrada.press("Enter")
    expect(pagina.locator(".terminal-saida")).to_contain_text("forja-ok", timeout=30000)
    passo("terminal roda um comando", True)
    entrada.fill("cat .env")
    entrada.press("Enter")
    expect(pagina.locator(".terminal-saida")).to_contain_text("SEGREDO=ficticio", timeout=15000)
    passo("terminal mostra o .env ao usuario com aviso (nunca vai para os agentes)", "só para você" in pagina.locator(".terminal-saida").inner_text())
    entrada.fill("Remove-Item -Recurse lixo")
    entrada.press("Enter")
    expect(pagina.locator("#dlg-geral")).to_contain_text("risco alto", timeout=8000)
    pagina.locator("#dlg-geral").get_by_role("button", name="Cancelar").click()
    expect(pagina.locator(".terminal-saida")).to_contain_text("Cancelado", timeout=6000)
    passo("comando perigoso pergunta antes; cancelar nao executa nada", (pasta / "lixo").exists())
    pagina.screenshot(path=str(saida / "bancada-terminal.png"))
    pagina.keyboard.press("Control+j")

    # Git: preparar (segredo pergunta), commit e diff lado a lado
    for args in (["init", "-q", "-b", "main"], ["config", "user.name", "Teste"], ["config", "user.email", "teste@exemplo.invalid"]):
        subprocess.run(["git", *args], cwd=pasta, check=True, capture_output=True)  # noqa: S603, S607
    pagina.locator("#atividades button[data-id=codigo]").click()
    if pagina.locator("#lateral .grupo-abas [role=tab]", has_text="Git").get_attribute("aria-selected") != "true":
        pagina.locator("#lateral .grupo-abas [role=tab]", has_text="Git").click()
    pagina.locator("#lateral-corpo select[aria-label=Projeto]").select_option(label=nome)
    expect(pagina.locator(".scm .linha-git").first).to_be_visible(timeout=8000)
    passo("Git mostra as alteracoes, com o .env marcado como segredo", pagina.locator(".scm .linha-git.segredo").count() == 1)
    pagina.get_by_role("button", name="Preparar tudo").click()
    expect(pagina.locator("#dlg-geral")).to_contain_text(".env", timeout=8000)
    pagina.locator("#dlg-geral").get_by_role("button", name="Cancelar").click()
    passo("preparar tudo com .env pergunta antes (aviso, nao bloqueio)", pagina.locator(".scm-secao h3", has_text="Preparadas").count() == 0)
    pagina.get_by_role("button", name="Preparar src/app.py").click()
    expect(pagina.locator(".scm-secao h3", has_text="Preparadas (1)")).to_be_visible(timeout=8000)
    pagina.get_by_label("Mensagem do commit").fill("primeiro commit da bancada")
    pagina.get_by_role("button", name="✓ Commit").click()
    expect(pagina.locator(".scm-secao h3", has_text="Preparadas")).to_have_count(0, timeout=8000)
    log = subprocess.run(["git", "log", "--oneline"], cwd=pasta, capture_output=True, text=True, check=False).stdout  # noqa: S603, S607
    passo("commit pela tela grava no repositorio", "primeiro commit da bancada" in log)
    (pasta / "src" / "app.py").write_text("x = 'mudou fora'\ny = 2\n", encoding="utf-8")
    pagina.get_by_role("button", name="Atualizar").first.click()
    pagina.locator(".scm .linha-git", has_text="app.py").locator("button.bloco").click()
    expect(pagina.locator(".tabela-diff")).to_be_visible(timeout=8000)
    passo("clicar no arquivo alterado abre as diferencas lado a lado", pagina.locator(".tabela-diff tr.d-add, .tabela-diff tr.d-mudou").count() >= 1)
    pagina.screenshot(path=str(saida / "bancada-diff.png"))

    # Requisicoes HTTP (estilo Postman) contra a propria Forja
    pagina.goto(base + "#/http")
    pagina.reload()
    pagina.locator(".url-http").fill(base + "api/v1/saude")
    pagina.locator(".barra-url button.primario").click()
    expect(pagina.locator(".status-http.grande")).to_contain_text("200", timeout=10000)
    passo("Requisicoes HTTP envia e mostra status, tempo e corpo", '"status"' in pagina.locator(".corpo-resposta").inner_text())
    pagina.screenshot(path=str(saida / "bancada-http.png"))

    # Comandos e receitas
    pagina.goto(base + "#/comandos")
    pagina.reload()
    pagina.get_by_label("Buscar comando ou receita").fill("push")
    pagina.locator(".lista-catalogo button", has_text="git push").first.click()
    expect(pagina.locator(".detalhe-comando .tabela-opcoes")).to_be_visible(timeout=6000)
    passo("catalogo explica o comando (sintaxe, opcoes e riscos)", "--force" in pagina.locator(".detalhe-comando").inner_text())
    pagina.locator(".segmentado button", has_text="Receitas").click()
    pagina.get_by_label("Buscar comando ou receita").fill("remoto")
    pagina.locator(".lista-catalogo button", has_text="Vincular").first.click()
    pagina.get_by_role("button", name="Abrir e executar").click()
    expect(pagina.locator(".janela-receita .passos-receita li")).to_have_count(6, timeout=6000)
    pagina.locator(".janela-receita").get_by_label("URL do repositório remoto").fill("https://exemplo.invalid/projeto.git")
    passo("receita mostra os passos com as variaveis preenchidas", "https://exemplo.invalid/projeto.git" in pagina.locator(".janela-receita").inner_text())
    pagina.screenshot(path=str(saida / "bancada-receita.png"))
    pagina.keyboard.press("Escape")
    pagina.keyboard.press("Control+/")
    expect(pagina.locator("#dlg-geral")).to_contain_text("Atalhos de teclado", timeout=4000)
    passo("Ctrl+/ mostra os atalhos de teclado", True)
    pagina.keyboard.press("Escape")

    # divisoria, Chat e Agentes
    pagina.goto(base + "#/explorador")
    pagina.reload()
    abrir_menu(pagina)
    antes = pagina.locator("#lateral").bounding_box()["width"]
    pagina.locator(".divisor-lateral").focus()
    pagina.keyboard.press("ArrowRight")
    pagina.keyboard.press("ArrowRight")
    pagina.wait_for_timeout(400)
    passo("divisoria redimensiona a barra lateral pelo teclado", pagina.locator("#lateral").bounding_box()["width"] >= antes + 40)
    pagina.keyboard.press("Home")
    pagina.locator('#modos button[data-modo="chat"]').click()
    expect(pagina.locator(".chat-grade .chat-fios")).to_be_visible(timeout=6000)
    passo("modo Chat expande a conversa para a tela toda (editor escondido)", pagina.locator("#principal").is_hidden())
    pagina.locator("button.fio", has_text="Conversa com o master").click()
    expect(pagina.locator(".chat-painel .conversa-master")).to_be_visible(timeout=6000)
    passo("lista de conversas abre a conversa com o master", True)
    pagina.screenshot(path=str(saida / "bancada-chat.png"))
    pagina.locator('#modos button[data-modo="agentes"]').click()
    expect(pagina.locator("canvas.escritorio-cena")).to_be_visible(timeout=6000)
    expect(pagina.locator(".escritorio-lista li").first).to_be_visible(timeout=8000)  # a lista chega junto com GET /oficina
    passo("modo Agentes mostra o escritorio em pixel art com lista acessivel", pagina.locator(".escritorio-lista li").count() >= 1)
    pagina.wait_for_timeout(600)
    pagina.screenshot(path=str(saida / "bancada-agentes.png"))
    pagina.locator('#modos button[data-modo="editor"]').click()
    expect(pagina.locator(".faixa-abas")).to_be_visible(timeout=4000)
    passo("volta ao modo Editor com as abas abertas", pagina.locator(".aba-editor").count() >= 3)


def interagir(pagina, base: str, saida: Path, erros: list[str]) -> int:
    from playwright.sync_api import expect  # a CSP da pagina proibe eval: wait_for_function nao funciona aqui

    """Fluxos de usuario no navegador. Cada passo imprime OK/FALHA; devolve quantas falhas houve."""
    falhas = 0

    def passo(nome: str, condicao: bool) -> None:
        nonlocal falhas
        ultimo_passo[0] = nome
        print(f"  [{'OK' if condicao else 'FALHA'}] {nome}")
        falhas += 0 if condicao else 1
        if not condicao:
            anotar("passo do painel", nome)

    erros.clear()
    pagina.goto(base + "#/tarefas")
    pagina.reload()
    pagina.wait_for_selector(".cartao")
    passo("painel de conversa comeca recolhido", pagina.locator("#direita").is_hidden())
    lat, princ = pagina.locator("#lateral").bounding_box(), pagina.locator("#principal").bounding_box()
    passo("barra lateral mostra o menu da area e EMPURRA o conteudo (estilo VS Code)",
          pagina.locator("#lateral").is_visible() and princ["x"] >= lat["x"] + lat["width"] - 1)
    fechar_menu(pagina)
    pagina.wait_for_timeout(400)  # transicao da grade
    passo("botao da barra de titulo recolhe a barra lateral e o conteudo ocupa o espaco",
          pagina.locator("#lateral").is_hidden() and pagina.locator("#principal").bounding_box()["x"] <= 60)
    pagina.locator(".cartao", has_text="Definir autenticação").click()
    pagina.wait_for_selector("#direita .msg", timeout=8000)
    passo("selecionar tarefa abre a conversa com o briefing do agente", pagina.locator("#direita .decisao").count() >= 1)
    largura_msg = pagina.locator("#direita .msg").first.bounding_box()["width"]
    passo("mensagens da conversa ocupam a largura do painel (sem colisao de CSS)", largura_msg > 0.8 * pagina.locator("#direita").bounding_box()["width"] - 30)
    passo("aviso de contexto aparece uma unica vez (sem render concorrente)", pagina.locator("#direita .aviso").count() <= 1)
    pagina.locator("#direita input[type=file]").set_input_files(files=[{"name": "erro.log", "mimeType": "text/plain", "buffer": b"Traceback: falha na fila\n"}])
    expect(pagina.locator("#direita .chip-anexo")).to_have_count(1, timeout=6000)
    passo("anexar arquivo enviado (de qualquer pasta) aparece como chip", "erro.log" in pagina.locator("#direita .anexos").inner_text())
    pagina.locator("#direita .chip-anexo button").click()
    expect(pagina.locator("#direita .chip-anexo")).to_have_count(0, timeout=6000)
    passo("remover anexo", True)

    pasta = Path(tempfile.mkdtemp(prefix="forja-proj-"))
    (pasta / "src").mkdir()
    (pasta / "src" / "fila_prioridade.py").write_text("def enfileirar(x):\n    return x\n", encoding="utf-8")
    (pasta / ".env").write_text("SEGREDO=x", encoding="utf-8")
    abrir_menu(pagina)
    pagina.get_by_role("button", name="+ Projeto").click()
    pagina.get_by_label("Nome do projeto").fill(f"Projeto da fila {pasta.name}")  # unico: o script pode rodar de novo no mesmo demo
    pagina.get_by_label("Caminho da pasta").fill(str(pasta))
    pagina.locator("#dlg-geral").get_by_role("button", name="Salvar").click()
    expect(pagina.locator("#lateral")).to_contain_text("1 de trabalho, 0 de consulta", timeout=6000)
    passo("criar projeto com pasta de trabalho", True)
    pagina.get_by_role("button", name="+ Nova tarefa").click()
    pagina.get_by_label("Modo da tarefa").select_option("alteracao_codigo")
    pagina.get_by_role("button", name="+ testes passam").click()
    passo("sugestao de criterio verificavel entra no campo", "testes passam" in pagina.get_by_label("Criterios de aceite (obrigatorio)").input_value())
    pagina.get_by_label("Modo da tarefa").select_option("analise")
    pagina.get_by_label("Titulo").fill("Revisar a fila")
    pagina.get_by_label("Criterios de aceite (obrigatorio)").fill("explicar a fila")
    pagina.get_by_role("button", name="Criar e preparar").click()
    fechar_menu(pagina)
    pagina.locator(".cartao", has_text="Revisar a fila").click()
    pagina.get_by_role("button", name="@ do projeto").click()
    pagina.get_by_label("Buscar arquivo do projeto").fill("@fila")
    pagina.locator(".escolher-arquivo button", has_text="fila_prioridade.py").first.click()
    expect(pagina.locator("#direita .chip-anexo")).to_have_count(1, timeout=6000)
    passo("@mencao anexa arquivo da pasta do projeto", "fila_prioridade.py" in pagina.locator("#direita .anexos").inner_text())
    pagina.get_by_role("button", name="@ do projeto").click()
    passo("explorador do projeto esconde .env", ".env" not in pagina.locator(".explorador").inner_text())
    pagina.screenshot(path=str(saida / "projeto-anexos.png"))
    passo("janela flutuante tem cabecalho com titulo e botao de fechar", pagina.locator("#dlg-geral .janela-cabeca .fechar").is_visible())
    pagina.locator("#dlg-geral").get_by_role("button", name="Fechar", exact=True).click()
    abrir_menu(pagina)
    pagina.get_by_label("Filtrar por projeto").select_option("")  # volta a mostrar todas as tarefas para os proximos passos
    pagina.screenshot(path=str(saida / "tarefas-conversa.png"))
    fechar_menu(pagina)
    pagina.locator('#direita [data-fechar="direita"]').click()
    expect(pagina.locator("#direita")).to_be_hidden(timeout=3000)
    passo("botao de fechar recolhe a conversa", True)

    pagina.locator(".cartao", has_text="Planejar migração").drag_to(pagina.locator('.coluna[data-id="concluida"]'))
    pagina.wait_for_selector(".toast.erro", timeout=4000)
    passo("arrastar para coluna invalida e recusado com aviso", "nao permitido" in pagina.locator(".toast.erro").first.inner_text())

    passo("campos avancados escondidos no nivel simples", pagina.locator(".cartao .meta .tag", has_text="T-").count() == 0 or not pagina.locator(".so-avancado").first.is_visible())
    pagina.select_option("#nivel", "avancado")
    passo("nivel avancado mostra campos tecnicos", pagina.locator(".so-avancado").first.is_visible())
    pagina.select_option("#nivel", "simples")

    altura_antes = pagina.locator("#principal").bounding_box()["height"]
    pagina.keyboard.press("Control+j")
    expect(pagina.locator("#inferior")).to_be_visible(timeout=3000)
    pagina.wait_for_timeout(400)  # transicao da grade
    passo("Ctrl+J abre o painel inferior e EMPURRA o conteudo (nada fica coberto)",
          pagina.locator("#principal").bounding_box()["height"] < altura_antes - 50)
    pagina.keyboard.press("Control+j")
    expect(pagina.locator("#inferior")).to_be_hidden(timeout=3000)
    passo("Ctrl+J recolhe o painel inferior", True)

    pagina.goto(base + "#/quadro")
    pagina.reload()
    pagina.wait_for_selector(".msg-q")
    fechar_menu(pagina)
    antes = pagina.locator(".msg-q.pendente").count()
    pagina.locator(".msg-q.pendente").first.get_by_role("button", name="Resolver").click()
    pagina.fill("#dlg-geral-corpo input", "feito no teste")
    pagina.get_by_role("button", name="Resolver", exact=True).last.click()
    expect(pagina.locator(".msg-q.pendente")).to_have_count(antes - 1, timeout=6000)
    passo("resolver mensagem do quadro atualiza a faixa", pagina.locator(".msg-q.resolvida").count() >= 1)

    pagina.goto(base + "#/memoria")
    pagina.reload()
    pagina.wait_for_selector(".grafo-caixa svg .no")
    pagina.locator(".lista-notas button", has_text="Autenticação Bearer").click()
    pagina.wait_for_selector(".nota > .linha h1", timeout=6000)
    passo("abrir nota mostra titulo, wikilinks e backlinks", pagina.locator(".nota .wikilink").count() >= 2 and "backlinks" in pagina.locator(".nota").inner_text().lower())
    passo("wikilink sem nota aparece como quebrado", pagina.locator(".nota .wikilink.quebrado").count() >= 1)
    pagina.locator(".nota .wikilink:not(.quebrado)").first.click()
    expect(pagina.locator(".nota > .linha h1")).not_to_have_text("Autenticação Bearer", timeout=6000)
    passo("clicar em wikilink navega para a outra nota", pagina.locator(".nota > .linha h1").inner_text() != "Autenticação Bearer")
    pagina.get_by_role("button", name="Editar").click()
    campo = pagina.get_by_label("Conteudo em Markdown")
    campo.fill(campo.input_value() + "\nLinha editada pelo teste com [[Nota isolada]].")
    pagina.get_by_role("button", name="Salvar").click()
    pagina.wait_for_selector(".toast.ok", timeout=6000)
    expect(pagina.locator(".nota")).to_contain_text("Linha editada pelo teste", timeout=6000)
    passo("editar e salvar nota persiste e renderiza", True)
    pagina.screenshot(path=str(saida / "memoria-nota.png"))
    abrir_menu(pagina)
    antes_base = pagina.locator(".grafo-caixa .no").count()
    pagina.get_by_label("mostrar a base da Forja").check()
    expect(pagina.locator(".grafo-caixa .no")).not_to_have_count(antes_base, timeout=6000)
    passo("base inicial da Forja aparece no grafo sob demanda (60+ notas ligadas)", pagina.locator(".grafo-caixa .no").count() >= antes_base + 60)
    pagina.get_by_label("mostrar a base da Forja").uncheck()
    expect(pagina.locator(".grafo-caixa .no")).to_have_count(antes_base, timeout=6000)
    pagina.get_by_role("button", name="Estudar e alimentar…").click()
    pagina.get_by_label("Tópico ou caminho da pasta").fill("boas praticas de filas com prioridade")
    pagina.locator("#dlg-geral").get_by_role("button", name="Solicitar estudo").click()
    expect(pagina.locator("#dlg-geral")).to_contain_text("Estudo preparado", timeout=8000)
    passo("solicitar estudo de topico cria tarefa preparada (sem executar)", True)
    pagina.locator("#dlg-geral").get_by_role("button", name="Cancelar").click()
    abrir_menu(pagina)
    pagina.fill('input[aria-label="Buscar no grafo"]', "alembic")
    # demo no segundo cerebro do usuario (pessoal): Alembic, o guia ligado e a nota pessoal que cita o Alembic (ADR-029)
    expect(pagina.locator(".grafo-caixa .no")).to_have_count(3, timeout=6000)
    passo("busca filtra o grafo", pagina.locator(".grafo-caixa .no").count() <= 3)
    pagina.locator(".lista-notas button", has_text="Alembic").click()
    pagina.wait_for_selector(".ligacoes", timeout=6000)
    pagina.get_by_label("Ligar esta nota a").select_option(label="Guia de migração")
    pagina.get_by_role("button", name="Ligar…").click()
    pagina.get_by_label("Tipo da ligacao").select_option("DOCUMENTADO_EM")
    pagina.get_by_label("Nota da ligacao").fill("o guia explica o uso")
    pagina.get_by_role("button", name="Ligar", exact=True).click()
    expect(pagina.locator(".ligacoes h2")).to_contain_text("(1)", timeout=6000)
    passo("criar ligacao tipada pela tela aparece na nota e no grafo (tracejada)", pagina.locator(".grafo-caixa .aresta.tipada").count() >= 1)
    pagina.screenshot(path=str(saida / "ligacao-tipada.png"))
    pagina.locator(".ligacoes").get_by_role("button", name="remover", exact=False).first.click()
    expect(pagina.locator(".ligacoes h2")).to_contain_text("(0)", timeout=6000)
    passo("remover ligacao tipada", pagina.locator(".grafo-caixa .aresta.tipada").count() == 0)
    pagina.goto(base + "#/config")
    pagina.reload()
    pagina.wait_for_selector(".opcao")
    passo("configuracoes abrem em janela flutuante (nao em pagina)", pagina.locator("dialog#janela-config[open]").count() == 1)
    passo("janela lista as categorias", pagina.locator("#janela-config").get_by_role("button", name="Privacidade").count() == 1)
    passo("abas Gerais e Avancadas separadas", pagina.get_by_role("tab", name="Avançadas", exact=False).count() == 1)
    passo("categoria Agentes abre primeiro com nivel, tags e observacoes", pagina.locator('[data-pref="metodos_acao"] .tag-opcao').count() >= 6)
    pagina.locator('[data-pref="metodos_acao"]').get_by_role("button", name="Direto").click()
    passo("tag contraditoria fica bloqueada", pagina.locator('[data-pref="metodos_acao"]').get_by_role("button", name="Pesquisador").is_disabled())
    passo("cada tag mostra o texto exato enviado ao agente", "Enviado ao agente: Direto:" in pagina.locator('[data-pref="metodos_acao"]').inner_text())
    pagina.locator('[data-pref="observacoes_guia"] textarea').fill("Prefira pytest. Commits em portugues.")
    pagina.locator('[data-pref="nivel_autonomia"]').get_by_role("button", name="Acesso liberado").click()
    pagina.get_by_role("button", name="Salvar alterações").click()
    pagina.wait_for_selector(".toast.ok", timeout=6000)
    passo("perfil de trabalho salvo (nivel + tags + observacoes)", pagina.locator('[data-pref="nivel_autonomia"] select').input_value() == "liberado")
    pagina.screenshot(path=str(saida / "config-agentes.png"))
    pagina.get_by_role("button", name="Aparência").click()
    passo("4 paletas escuras e 4 claras como amostras", pagina.locator('[data-pref="paleta_escura"] [role=radio]').count() == 4
          and pagina.locator('[data-pref="paleta_clara"] [role=radio]').count() == 4)
    pagina.locator('[data-pref="tema"]').get_by_role("button", name="Escuro").click()
    pagina.locator('[data-pref="paleta_escura"]').get_by_role("radio", name="Brasa").click()
    passo("escolher tema e paleta mostra previa na hora (antes de salvar)", pagina.locator("html").get_attribute("data-paleta") == "brasa")
    pagina.screenshot(path=str(saida / "config-aparencia.png"))
    pagina.get_by_role("button", name="Descartar").click()
    passo("descartar desfaz a previa", pagina.locator("html").get_attribute("data-paleta") != "brasa")
    pagina.locator('[data-pref="tema"]').get_by_role("button", name="Claro").click()
    pagina.get_by_role("button", name="Salvar alterações").click()
    expect(pagina.locator("html")).to_have_attribute("data-tema", "claro", timeout=6000)
    passo("tema claro e salvo e aplicado na hora", True)
    pagina.locator('[data-pref="tema"]').get_by_role("button", name="Restaurar padrão").click()
    expect(pagina.locator("html")).not_to_have_attribute("data-tema", "claro", timeout=6000)
    passo("restaurar padrao devolve o tema automatico", True)
    pagina.get_by_role("button", name="Eficiência").click()
    pagina.get_by_role("tab", name="Avançadas", exact=False).click()
    pagina.locator('[data-pref="contexto_orcamento_tokens"]').get_by_role("button", name="Alto").click()
    passo("exemplo aplica valor no campo", pagina.locator('[data-pref="contexto_orcamento_tokens"] input[type=number]').input_value() != "2000")
    estado_sem = pagina.locator('[data-pref="busca_semantica"] .estado-semantica')
    expect(estado_sem).not_to_contain_text("Verificando", timeout=8000)
    passo("busca semantica por nivel mostra a disponibilidade real", pagina.locator('[data-pref="busca_semantica"] select option').count() == 3
          and ("Disponível" in estado_sem.inner_text() or "Indisponível" in estado_sem.inner_text()))
    pagina.get_by_role("button", name="Descartar").click()
    pagina.get_by_role("button", name="Privacidade").click()
    pagina.get_by_role("tab", name="Gerais", exact=False).click()
    passo("leitura de arquivos nasce desativada", not pagina.locator('[data-pref="ferramentas_arquivos_ativas"] input[type=checkbox]').is_checked())
    pagina.locator('[data-pref="pastas_proibidas"] textarea').fill(PROIBIDA)
    pagina.get_by_role("button", name="Salvar alterações").click()
    pagina.wait_for_selector(".toast.ok", timeout=6000)
    passo("pasta proibida salva pela tela", "pasta-ficticia-proibida" in pagina.locator('[data-pref="pastas_proibidas"] textarea').input_value())
    pagina.locator('[data-pref="pastas_proibidas"]').get_by_role("button", name="Restaurar padrão").click()
    expect(pagina.locator('[data-pref="pastas_proibidas"] textarea')).to_have_value("", timeout=6000)
    pagina.locator('[data-pref="pastas_permitidas"] textarea').fill(INEXISTENTE)
    pagina.get_by_role("button", name="Salvar alterações").click()
    pagina.wait_for_selector(".toast.erro", timeout=6000)
    passo("pasta permitida inexistente e recusada com mensagem", True)
    pagina.get_by_role("button", name="Descartar").click()
    pagina.screenshot(path=str(saida / "config-privacidade.png"))
    pagina.get_by_role("button", name="Consumo").click()
    pagina.wait_for_selector("table input")
    passo("modelo de reserva configuravel por parte", pagina.get_by_label("Modelos de reserva de Execucao de tarefas").count() == 1)
    pagina.get_by_label("Modelo de Execucao de tarefas").fill("modelo-rapido")
    pagina.get_by_role("button", name="Salvar modelos").click()
    expect(pagina.locator("#st-modelo")).to_contain_text("modelo-rapido", timeout=6000)
    passo("salvar modelo por parte atualiza a barra de status", True)
    pagina.get_by_role("button", name="Manutenção").click()
    pagina.get_by_role("button", name="Solicitar revisao").click()
    pagina.wait_for_selector("text=Revisao criada e preparada", timeout=8000)
    passo("solicitar revisao cria tarefa preparada sem executar", True)
    falhas += integracoes(pagina, base, saida, expect, passo)

    pagina.goto(base + "#/integracoes")
    pagina.reload()
    pagina.wait_for_selector("#acoes-externas")
    fechar_menu(pagina)
    pendentes = pagina.locator(".acao-externa").count()
    passo("acoes externas pendentes aparecem com a frase em linguagem natural",
          pendentes == 0 or "Posso criar no Trello o cartao" in pagina.locator("#acoes-externas + .grade").inner_text())
    passo("secao de acoes nao renderiza texto solto (null/undefined)", "null" not in pagina.locator("#principal").inner_text().split("\n"))
    if pendentes:
        pagina.screenshot(path=str(saida / "acoes-externas.png"))
        cartao = pagina.locator(".acao-externa").first
        cartao.locator("textarea").fill("nao agora, revisar o texto antes")
        cartao.get_by_role("button", name="Negar").click()
        expect(pagina.locator(".acao-externa")).to_have_count(pendentes - 1, timeout=6000)
        passo("negar com adendo remove a acao da fila sem executar", True)

    pagina.goto(base + "#/memoria")
    pagina.reload()
    pagina.get_by_role("button", name="Avaliar a busca").click()
    pagina.get_by_label("Pergunta real").fill("como funciona a autenticação bearer")
    pagina.get_by_role("button", name="Ver resultados").click()
    pagina.wait_for_selector("text=Marque TODOS", timeout=6000)
    pagina.locator('input[aria-label^="Relevante: Autenticação Bearer"]').check()
    pagina.get_by_role("button", name="Salvar rotulos desta pergunta").click()
    expect(pagina.get_by_text("Busca atual:")).to_be_visible(timeout=6000)
    passo("rotular uma pergunta real mostra recall/MRR da busca", "MRR" in pagina.locator(".rotulagem").inner_text())
    pagina.screenshot(path=str(saida / "rotulagem.png"))
    pagina.locator("#dlg-geral").get_by_role("button", name="Fechar", exact=True).click()

    melhorias(pagina, base, saida, expect, passo)
    fluxo_master(pagina, base, saida, expect, passo)
    bancada(pagina, base, saida, expect, passo)

    pagina.goto(base + "#/ferramentas")
    pagina.reload()
    pagina.locator(".lista-notas button", has_text="tokens.orcar").click()
    pagina.get_by_role("button", name="Executar").click()
    pagina.wait_for_selector("pre.saida", timeout=6000)
    passo("executar ferramenta mostra resumo e custo", pagina.locator(".tag", has_text="reducao").count() >= 1)
    passo("nenhum erro de console/CSP durante as interacoes", not [e for e in erros if "404" not in e and "422" not in e and "428" not in e
                                                                  and not ("409" in e and ("/area/arquivo" in e or "Failed to load resource" in e))])  # conflito provocado no teste
    for e in erros[:5]:
        print("   ", e[:200])
    return falhas


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--porta", type=int, default=8787)
    ap.add_argument("--saida", default="capturas-painel")
    ap.add_argument("--token", default="")
    ap.add_argument("--interagir", action="store_true", help="executa fluxos de usuario (altera os dados sinteticos)")
    ap.add_argument("--largura", type=int, default=1440)
    ap.add_argument("--altura", type=int, default=900)
    ap.add_argument("--navegador", choices=("msedge", "chromium"), default="msedge", help="chromium = o do Playwright (CI)")
    ap.add_argument("--a11y", action="store_true", help="auditoria axe-core em cada vista (falha em violacao critica/seria)")
    ap.add_argument("--login", action="store_true", help="testa a tela de acesso num servidor com login e SEM conta criada")
    ap.add_argument("--so-melhorias", action="store_true", help="so os fluxos das melhorias 9.x (desfazer, custo, revisao, regras, oficina)")
    a = ap.parse_args()
    from playwright.sync_api import sync_playwright  # import tardio: dependencia opcional


    saida = Path(a.saida)
    saida.mkdir(parents=True, exist_ok=True)
    problemas = 0
    with sync_playwright() as p:
        try:
            nav = p.chromium.launch(channel="msedge") if a.navegador == "msedge" else p.chromium.launch()
        except Exception:  # noqa: BLE001 - cai para o Chromium do Playwright se o Edge nao existir
            nav = p.chromium.launch()
        ctx = nav.new_context(viewport={"width": a.largura, "height": a.altura})
        if a.token:
            ctx.add_init_script(f"sessionStorage.setItem('forja_token', {a.token!r})")
        pagina = ctx.new_page()
        erros: list[str] = []
        pagina.on("console", lambda m: erros.append(f"console.{m.type}: {m.text}") if m.type in ("error", "warning") else None)
        pagina.on("pageerror", lambda e: erros.append(f"pageerror: {e}"))
        pagina.on("response", lambda r: erros.append(f"http {r.status} {r.request.method}: {r.url.split('/api/v1')[-1]} (apos: {ultimo_passo[0]})") if r.status >= 400 else None)
        base = f"http://127.0.0.1:{a.porta}/"
        if a.login:  # servidor proprio, COM login e sem conta: so a tela de acesso
            problemas = login(nav, base, saida, a.a11y)
            nav.close()
            print("problemas:", problemas)
            return 1 if problemas else 0
        for vista, seletor in VISTAS.items():
            erros.clear()
            pagina.goto(f"{base}#/{vista}")
            pagina.reload()
            try:
                pagina.wait_for_selector(seletor, timeout=8000)
                n = pagina.locator(seletor).count()
                estado = "ok"
            except Exception:  # noqa: BLE001
                n, estado = 0, "ELEMENTO AUSENTE"
                problemas += 1
            pagina.wait_for_timeout(600)
            pagina.screenshot(path=str(saida / f"{vista}.png"))
            problemas += len(erros)
            for e in erros[:3]:
                anotar(f"vista {vista}", e)
            print(f"{vista:<12} {estado:<17} {seletor!r}={n} erros={len(erros)}")
            for e in erros[:5]:
                print("   ", e[:200])
        if a.a11y:
            problemas += auditar_a11y(nav, base, a, saida)
        problemas += estreito(nav, base, a, saida)
        if a.so_melhorias:  # iteracao rapida nas telas das melhorias 9.x
            from playwright.sync_api import expect

            falhas = [0]

            def passo(nome: str, condicao: bool) -> None:
                print(f"  [{'OK' if condicao else 'FALHA'}] {nome}")
                falhas[0] += 0 if condicao else 1

            melhorias(pagina, base, saida, expect, passo)
            problemas += falhas[0]
        elif a.interagir:
            problemas += interagir(pagina, base, saida, erros)
        nav.close()
    print("problemas:", problemas)
    return 1 if problemas else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 - no CI, a excecao vira anotacao; localmente o traceback continua
        anotar("inspecao do painel", f"{type(e).__name__}: {str(e).splitlines()[0] if str(e) else ''}")
        traceback.print_exc()
        sys.exit(1)
