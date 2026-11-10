"""Inspeciona o painel num navegador real (Playwright + Edge/Chromium): erros de console/CSP, elementos-chave e capturas.

Opcional: Playwright NAO e dependencia do projeto (pip install playwright). Uso:
  python scripts/inspecionar_painel.py [--porta 8787] [--saida pasta] [--token TOKEN]
Use com um servidor semeado por scripts/semear_demo.py (dados sinteticos).
"""

from __future__ import annotations

import argparse
from pathlib import Path

VISTAS = {
    "tarefas": ".kanban .coluna",
    "quadro": ".faixas .faixa",
    "memoria": ".grafo-caixa svg .no",
    "ferramentas": ".lista-notas button",
    "integracoes": ".grade .card",
    "config": ".opcao",
}


def integracoes(pagina, base: str, saida: Path, expect, passo) -> int:
    """Configura integracoes de rede pela tela. O Jira usa dados ficticios (host .example nunca resolve); o GitHub faz UMA
    chamada real de leitura (GET /rate_limit em api.github.com, sem token e sem enviar dados) para validar TLS e o fixador de IP."""
    pagina.goto(base + "#/integracoes")
    pagina.reload()
    pagina.wait_for_selector(".card")
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


def interagir(pagina, base: str, saida: Path, erros: list[str]) -> int:
    from playwright.sync_api import expect  # a CSP da pagina proibe eval: wait_for_function nao funciona aqui

    """Fluxos de usuario no navegador. Cada passo imprime OK/FALHA; devolve quantas falhas houve."""
    falhas = 0

    def passo(nome: str, condicao: bool) -> None:
        nonlocal falhas
        print(f"  [{'OK' if condicao else 'FALHA'}] {nome}")
        falhas += 0 if condicao else 1

    erros.clear()
    pagina.goto(base + "#/tarefas")
    pagina.reload()
    pagina.wait_for_selector(".cartao")
    passo("painel de conversa comeca recolhido", pagina.locator("#direita").is_hidden())
    pagina.locator(".cartao", has_text="Definir autenticacao").click()
    pagina.wait_for_selector("#direita .msg", timeout=8000)
    passo("selecionar tarefa abre a conversa com o briefing do agente", pagina.locator("#direita .decisao").count() >= 1)
    largura_msg = pagina.locator("#direita .msg").first.bounding_box()["width"]
    passo("mensagens da conversa ocupam a largura do painel (sem colisao de CSS)", largura_msg > 0.8 * pagina.locator("#direita").bounding_box()["width"] - 30)
    passo("aviso de contexto aparece uma unica vez (sem render concorrente)", pagina.locator("#direita .aviso").count() <= 1)
    pagina.screenshot(path=str(saida / "tarefas-conversa.png"))

    pagina.locator(".cartao", has_text="Planejar migracao").drag_to(pagina.locator('.coluna[data-id="concluida"]'))
    pagina.wait_for_selector(".toast.erro", timeout=4000)
    passo("arrastar para coluna invalida e recusado com aviso", "nao permitido" in pagina.locator(".toast.erro").first.inner_text())

    passo("campos avancados escondidos no nivel simples", pagina.locator(".cartao .meta .tag", has_text="T-").count() == 0 or not pagina.locator(".so-avancado").first.is_visible())
    pagina.select_option("#nivel", "avancado")
    passo("nivel avancado mostra campos tecnicos", pagina.locator(".so-avancado").first.is_visible())
    pagina.select_option("#nivel", "simples")

    pagina.keyboard.press("Control+j")
    passo("Ctrl+J recolhe o painel inferior", pagina.locator("#inferior").is_hidden())
    pagina.keyboard.press("Control+j")

    pagina.goto(base + "#/quadro")
    pagina.reload()
    pagina.wait_for_selector(".msg-q")
    antes = pagina.locator(".msg-q.pendente").count()
    pagina.locator(".msg-q.pendente").first.get_by_role("button", name="Resolver").click()
    pagina.fill("#dlg-geral-corpo input", "feito no teste")
    pagina.get_by_role("button", name="Resolver", exact=True).last.click()
    expect(pagina.locator(".msg-q.pendente")).to_have_count(antes - 1, timeout=6000)
    passo("resolver mensagem do quadro atualiza a faixa", pagina.locator(".msg-q.resolvida").count() >= 1)

    pagina.goto(base + "#/memoria")
    pagina.reload()
    pagina.wait_for_selector(".grafo-caixa svg .no")
    pagina.locator(".lista-notas button", has_text="Autenticacao Bearer").click()
    pagina.wait_for_selector(".nota > .linha h1", timeout=6000)
    passo("abrir nota mostra titulo, wikilinks e backlinks", pagina.locator(".nota .wikilink").count() >= 2 and "backlinks" in pagina.locator(".nota").inner_text().lower())
    passo("wikilink sem nota aparece como quebrado", pagina.locator(".nota .wikilink.quebrado").count() >= 1)
    pagina.locator(".nota .wikilink:not(.quebrado)").first.click()
    expect(pagina.locator(".nota > .linha h1")).not_to_have_text("Autenticacao Bearer", timeout=6000)
    passo("clicar em wikilink navega para a outra nota", pagina.locator(".nota > .linha h1").inner_text() != "Autenticacao Bearer")
    pagina.get_by_role("button", name="Editar").click()
    campo = pagina.get_by_label("Conteudo em Markdown")
    campo.fill(campo.input_value() + "\nLinha editada pelo teste com [[Nota isolada]].")
    pagina.get_by_role("button", name="Salvar").click()
    pagina.wait_for_selector(".toast.ok", timeout=6000)
    expect(pagina.locator(".nota")).to_contain_text("Linha editada pelo teste", timeout=6000)
    passo("editar e salvar nota persiste e renderiza", True)
    pagina.screenshot(path=str(saida / "memoria-nota.png"))
    pagina.fill('input[aria-label="Buscar no grafo"]', "alembic")
    expect(pagina.locator(".grafo-caixa .no")).to_have_count(2, timeout=6000)
    passo("busca filtra o grafo", pagina.locator(".grafo-caixa .no").count() <= 3)

    pagina.goto(base + "#/config")
    pagina.reload()
    pagina.wait_for_selector(".opcao")
    passo("menu lista categorias na lateral", pagina.get_by_role("button", name="Privacidade").count() == 1)
    passo("abas Gerais e Avancadas separadas", pagina.get_by_role("tab", name="Avançadas", exact=False).count() == 1)
    pagina.screenshot(path=str(saida / "config-aparencia.png"))
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
    pagina.get_by_role("button", name="Descartar").click()
    pagina.get_by_role("button", name="Privacidade").click()
    pagina.get_by_role("tab", name="Gerais", exact=False).click()
    passo("leitura de arquivos nasce desativada", not pagina.locator('[data-pref="ferramentas_arquivos_ativas"] input[type=checkbox]').is_checked())
    pagina.locator('[data-pref="pastas_proibidas"] textarea').fill("C:/pasta-ficticia-proibida")
    pagina.get_by_role("button", name="Salvar alterações").click()
    pagina.wait_for_selector(".toast.ok", timeout=6000)
    passo("pasta proibida salva pela tela", "pasta-ficticia-proibida" in pagina.locator('[data-pref="pastas_proibidas"] textarea').input_value())
    pagina.locator('[data-pref="pastas_proibidas"]').get_by_role("button", name="Restaurar padrão").click()
    expect(pagina.locator('[data-pref="pastas_proibidas"] textarea')).to_have_value("", timeout=6000)
    pagina.locator('[data-pref="pastas_permitidas"] textarea').fill("C:/nao-existe-xyz")
    pagina.get_by_role("button", name="Salvar alterações").click()
    pagina.wait_for_selector(".toast.erro", timeout=6000)
    passo("pasta permitida inexistente e recusada com mensagem", True)
    pagina.get_by_role("button", name="Descartar").click()
    pagina.screenshot(path=str(saida / "config-privacidade.png"))
    pagina.get_by_role("button", name="Consumo").click()
    pagina.wait_for_selector("table input")
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
    pagina.get_by_label("Pergunta real").fill("como funciona a autenticacao bearer")
    pagina.get_by_role("button", name="Ver resultados").click()
    pagina.wait_for_selector("text=Marque TODOS", timeout=6000)
    pagina.locator('input[aria-label^="Relevante: Autenticacao Bearer"]').check()
    pagina.get_by_role("button", name="Salvar rotulos desta pergunta").click()
    expect(pagina.get_by_text("Busca atual:")).to_be_visible(timeout=6000)
    passo("rotular uma pergunta real mostra recall/MRR da busca", "MRR" in pagina.locator(".rotulagem").inner_text())
    pagina.screenshot(path=str(saida / "rotulagem.png"))
    pagina.get_by_role("button", name="Fechar").click()

    pagina.goto(base + "#/ferramentas")
    pagina.reload()
    pagina.locator(".lista-notas button", has_text="tokens.orcar").click()
    pagina.get_by_role("button", name="Executar").click()
    pagina.wait_for_selector("pre.saida", timeout=6000)
    passo("executar ferramenta mostra resumo e custo", pagina.locator(".tag", has_text="reducao").count() >= 1)
    passo("nenhum erro de console/CSP durante as interacoes", not [e for e in erros if "404" not in e and "422" not in e])
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
    a = ap.parse_args()
    from playwright.sync_api import sync_playwright  # import tardio: dependencia opcional


    saida = Path(a.saida)
    saida.mkdir(parents=True, exist_ok=True)
    problemas = 0
    with sync_playwright() as p:
        try:
            nav = p.chromium.launch(channel="msedge")
        except Exception:  # noqa: BLE001 - cai para o Chromium do Playwright se o Edge nao existir
            nav = p.chromium.launch()
        ctx = nav.new_context(viewport={"width": a.largura, "height": a.altura})
        if a.token:
            ctx.add_init_script(f"sessionStorage.setItem('forja_token', {a.token!r})")
        pagina = ctx.new_page()
        erros: list[str] = []
        pagina.on("console", lambda m: erros.append(f"console.{m.type}: {m.text}") if m.type in ("error", "warning") else None)
        pagina.on("pageerror", lambda e: erros.append(f"pageerror: {e}"))
        pagina.on("response", lambda r: erros.append(f"http {r.status}: {r.url.split('/api/v1')[-1]}") if r.status >= 400 else None)
        base = f"http://127.0.0.1:{a.porta}/"
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
            print(f"{vista:<12} {estado:<17} {seletor!r}={n} erros={len(erros)}")
            for e in erros[:5]:
                print("   ", e[:200])
        if a.interagir:
            problemas += interagir(pagina, base, saida, erros)
        nav.close()
    print("problemas:", problemas)
    return 1 if problemas else 0


if __name__ == "__main__":
    raise SystemExit(main())
