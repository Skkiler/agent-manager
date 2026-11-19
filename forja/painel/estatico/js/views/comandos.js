// Comandos e receitas: catalogo do assistente do terminal (padrao + seus + documentados pela IA), receitas passo a passo,
// cadastro manual e pedido para uma IA documentar um programa novo (o resultado chega como proposta para voce revisar).
import { api } from "../api.js";
import { emitir, selecionarTarefa } from "../estado.js";
import { abrirReceita, carregarCatalogo } from "../receitas.js";
import { dialogo, el, limpar, tag, toast } from "../ui.js";

const AREAS = { git: "Git", docker: "Docker", python: "Python", node: "Node", http: "HTTP", terminal: "Terminal" };
const RISCO = { baixo: ["seguro", "ok"], medio: ["atenção", "aviso"], alto: ["perigoso", "erro"] };
const st = { aba: "comandos", sel: null, q: "", area: "" };
let raizAtual = null;

const pedidos = () => { try { return JSON.parse(localStorage.getItem("forja_pedidos_ia") || "[]"); } catch { return []; } };
const salvarPedidos = (l) => localStorage.setItem("forja_pedidos_ia", JSON.stringify(l.slice(0, 30)));

function detalheComando(c, aoMudar) {
  const [rot, cls] = RISCO[c.risco] || [c.risco, ""];
  const usar = (linha) => { emitir("terminal-colar", linha); toast("Colado no terminal."); };
  return el("article", { className: "detalhe-comando" },
    el("div", { className: "linha" }, el("h2", { className: "titulo-cmd", textContent: [c.programa, ...c.sub].join(" ") }), tag(rot, cls), tag(AREAS[c.area] || c.area),
      c.origem !== "padrao" ? tag(c.origem === "ia" ? (c.revisado ? "IA (revisado)" : "IA: revisar") : "seu", c.origem === "ia" && !c.revisado ? "aviso" : "") : null),
    el("p", { className: "resumo-cmd", textContent: c.resumo }),
    c.sintaxe ? el("pre", { className: "sintaxe-cmd" }, el("code", { textContent: c.sintaxe })) : null,
    c.descricao ? el("p", { textContent: c.descricao }) : null,
    c.motivo ? el("p", { className: "aviso", textContent: `Por que pede atenção: ${c.motivo}` }) : null,
    c.subcomandos.length ? el("section", {}, el("h3", { textContent: "Subcomandos" }), el("dl", { className: "lista-def" }, ...c.subcomandos.flatMap((s) => [
      el("dt", {}, el("code", { textContent: s.nome }), s.risco && s.risco !== "baixo" ? tag(RISCO[s.risco][0], RISCO[s.risco][1]) : null), el("dd", { textContent: s.descricao })]))) : null,
    c.opcoes.length ? el("section", {}, el("h3", { textContent: "Opções" }), el("table", { className: "tabela-opcoes" },
      el("thead", {}, el("tr", {}, ...["Opção", "Valor", "O que faz"].map((h) => el("th", { scope: "col", textContent: h })))),
      el("tbody", {}, ...c.opcoes.map((o) => el("tr", {}, el("td", {}, el("code", { textContent: o.nomes.join(", ") })),
        el("td", { textContent: o.valor ? (o.opcoes.length ? o.opcoes.join(" | ") : o.valor) : "—" }),
        el("td", {}, o.descricao, o.risco ? el("span", {}, " ", tag(RISCO[o.risco][0], RISCO[o.risco][1])) : null, o.interativo ? el("span", {}, " ", tag("interativo")) : null)))))) : null,
    c.argumentos.length ? el("section", {}, el("h3", { textContent: "Argumentos" }), el("dl", { className: "lista-def" }, ...c.argumentos.flatMap((a) => [
      el("dt", {}, el("code", { textContent: `<${a.nome}>` }), a.obrigatorio ? tag("obrigatório") : null), el("dd", { textContent: `${a.descricao} (${a.tipo})` })]))) : null,
    c.exemplos.length ? el("section", {}, el("h3", { textContent: "Exemplos" }), el("ul", { className: "exemplos-cmd" }, ...c.exemplos.map((x) => el("li", {},
      el("code", { textContent: x.linha }), el("span", { className: "mudo", textContent: ` ${x.explicacao}` }),
      el("button", { type: "button", className: "pequeno", textContent: "Usar no terminal", onclick: () => usar(x.linha) }))))) : null,
    el("div", { className: "linha" },
      el("button", { type: "button", className: "pequeno", textContent: "Usar no terminal", onclick: () => usar(`${[c.programa, ...c.sub].join(" ")} `) }),
      c.origem === "ia" && !c.revisado ? el("button", { type: "button", className: "primario", textContent: "Marcar como revisado", onclick: async () => {
        try { await api("POST", `/area/comandos/usuario/${encodeURIComponent(c.id)}/revisar`); toast("Revisado.", "ok"); aoMudar(); } catch (e) { toast(e.message, "erro"); } } }) : null,
      c.origem !== "padrao" ? el("button", { type: "button", className: "perigo", textContent: "Remover", onclick: async () => {
        if (!confirm(`Remover ${c.id}?`)) return;
        try { await api("DELETE", `/area/comandos/usuario/${encodeURIComponent(c.id)}`); st.sel = null; aoMudar(); } catch (e) { toast(e.message, "erro"); } } }) : null));
}

function detalheReceita(r, aoMudar) {
  return el("article", { className: "detalhe-comando" },
    el("div", { className: "linha" }, el("h2", { className: "titulo-cmd", textContent: r.titulo }), tag(AREAS[r.area] || r.area), r.origem !== "padrao" ? tag(r.origem === "ia" ? "IA" : "sua") : null),
    el("p", { textContent: r.descricao }),
    r.variaveis.length ? el("p", { className: "mudo", textContent: `Variáveis: ${r.variaveis.map((v) => `{${v.nome}}`).join(", ")}` }) : null,
    el("ol", { className: "passos-resumo" }, ...r.passos.map((p) => el("li", {}, el("code", { textContent: p.comando }), el("span", { className: "mudo", textContent: ` ${p.explicacao || ""}` })))),
    el("div", { className: "linha" }, el("button", { type: "button", className: "primario", textContent: "Abrir e executar", onclick: () => abrirReceita(r.id) }),
      r.origem !== "padrao" ? el("button", { type: "button", className: "perigo", textContent: "Remover", onclick: async () => {
        if (!confirm(`Remover ${r.id}?`)) return;
        try { await api("DELETE", `/area/comandos/usuario/${encodeURIComponent(r.id)}`); st.sel = null; aoMudar(); } catch (e) { toast(e.message, "erro"); } } }) : null));
}

const linhas = (texto) => texto.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => l.split("|").map((x) => x.trim()));
const ID = (s) => s.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 70) || "item";

function formComando(aoSalvar) {
  const f = {};
  const campo = (nome, rotulo, props = {}, tipo = "input") => { f[nome] = el(tipo, { "aria-label": rotulo, ...props }); return el("label", { className: "campo" }, el("span", { textContent: rotulo }), f[nome]); };
  const corpo = el("form", { className: "form-comando", onsubmit: async (ev) => {
    ev.preventDefault();
    const sub = f.sub.value.trim().split(/\s+/).filter(Boolean);
    const comando = { id: ID(`${f.programa.value}.${sub.join(".")}`), programa: f.programa.value.trim(), sub, area: f.area.value, resumo: f.resumo.value.trim(),
      sintaxe: f.sintaxe.value.trim(), descricao: f.descricao.value.trim(), risco: f.risco.value, motivo: f.motivo.value.trim(),
      opcoes: linhas(f.opcoes.value).map(([nomes, valor, descricao, risco]) => ({ nomes: nomes.split(",").map((x) => x.trim()).filter(Boolean), valor: valor && valor !== "-" ? valor : null,
        descricao: descricao || "", risco: ["medio", "alto"].includes(risco) ? risco : null })),
      exemplos: linhas(f.exemplos.value).map(([linha, explicacao]) => ({ linha, explicacao: explicacao || "" })) };
    try { await api("POST", "/area/comandos/usuario", { comando }); toast("Comando salvo.", "ok"); d.fechar(); aoSalvar(comando.id); } catch (e) { toast(e.message, "erro"); }
  } },
  el("div", { className: "grade-campos" }, campo("programa", "Programa", { required: true, maxLength: 60, placeholder: "kubectl" }), campo("sub", "Subcomando(s)", { maxLength: 80, placeholder: "get" }),
    el("label", { className: "campo" }, el("span", { textContent: "Área" }), f.area = el("select", { "aria-label": "Área" }, ...Object.entries(AREAS).map(([k, v]) => el("option", { value: k, textContent: v })))),
    el("label", { className: "campo" }, el("span", { textContent: "Risco" }), f.risco = el("select", { "aria-label": "Risco" }, ...Object.entries(RISCO).map(([k, v]) => el("option", { value: k, textContent: v[0] }))))),
  campo("resumo", "Resumo (uma frase)", { required: true, maxLength: 300 }), campo("sintaxe", "Sintaxe", { maxLength: 300, placeholder: "kubectl get <recurso> [-n <namespace>]" }),
  campo("descricao", "Descrição", { rows: 2, maxLength: 2000 }, "textarea"), campo("motivo", "Por que pede atenção (se risco médio/alto)", { maxLength: 300 }),
  campo("opcoes", "Opções: uma por linha, no formato  nomes | tipo do valor | descrição | risco", { rows: 4, placeholder: "-n, --namespace | texto | Namespace do recurso\n--all | - | Todos os recursos | medio", spellcheck: false }, "textarea"),
  campo("exemplos", "Exemplos: linha | explicação", { rows: 2, placeholder: "kubectl get pods -n web | Lista os pods do namespace web", spellcheck: false }, "textarea"),
  el("p", { className: "mudo", textContent: "Tipos de valor: texto, inteiro, porta, portas, escolha, caminho, url, ramo, remoto, imagem, container." }),
  el("div", { className: "linha fim" }, el("button", { type: "button", textContent: "Cancelar", onclick: () => d.fechar() }), el("button", { type: "submit", className: "primario", textContent: "Salvar comando" })));
  const d = dialogo("Novo comando no catálogo", corpo);
}

function formReceita(aoSalvar) {
  const titulo = el("input", { required: true, maxLength: 300, "aria-label": "Título" });
  const area = el("select", { "aria-label": "Área" }, ...Object.entries(AREAS).map(([k, v]) => el("option", { value: k, textContent: v })));
  const desc = el("textarea", { rows: 2, maxLength: 2000, "aria-label": "Descrição" });
  const vars = el("textarea", { rows: 3, spellcheck: false, "aria-label": "Variáveis", placeholder: "url | URL do remoto | https://github.com/usuario/projeto.git" });
  const passos = el("textarea", { rows: 5, spellcheck: false, required: true, "aria-label": "Passos", placeholder: "git remote add origin {url} | Liga ao remoto\ngit push -u origin main | Envia" });
  const d = dialogo("Nova receita", el("form", { className: "form-comando", onsubmit: async (ev) => {
    ev.preventDefault();
    const receita = { id: `${area.value}.${ID(titulo.value)}`, area: area.value, titulo: titulo.value.trim(), descricao: desc.value.trim(),
      variaveis: linhas(vars.value).map(([nome, rotulo, padrao]) => ({ nome: ID(nome).replace(/[.-]/g, "_"), rotulo: rotulo || nome, padrao: padrao || "" })),
      passos: linhas(passos.value).map(([comando, explicacao]) => ({ comando, explicacao: explicacao || "" })) };
    try { await api("POST", "/area/comandos/usuario", { receita }); toast("Receita salva.", "ok"); d.fechar(); aoSalvar(receita.id); } catch (e) { toast(e.message, "erro"); }
  } }, el("div", { className: "grade-campos" }, el("label", { className: "campo" }, el("span", { textContent: "Título" }), titulo), el("label", { className: "campo" }, el("span", { textContent: "Área" }), area)),
  el("label", { className: "campo" }, el("span", { textContent: "Descrição" }), desc),
  el("label", { className: "campo" }, el("span", { textContent: "Variáveis: nome | rótulo | valor padrão (use {nome} nos passos)" }), vars),
  el("label", { className: "campo" }, el("span", { textContent: "Passos: comando | explicação" }), passos),
  el("div", { className: "linha fim" }, el("button", { type: "button", textContent: "Cancelar", onclick: () => d.fechar() }), el("button", { type: "submit", className: "primario", textContent: "Salvar receita" }))));
}

function formIa(aoMudar) {
  const programa = el("input", { required: true, maxLength: 60, placeholder: "kubectl, terraform, gh, poetry…", "aria-label": "Programa" });
  const detalhe = el("input", { maxLength: 500, placeholder: "Opcional: foco (ex.: get, apply e logs)", "aria-label": "Foco" });
  const d = dialogo("Pedir à IA para documentar um programa", el("form", { className: "form-comando", onsubmit: async (ev) => {
    ev.preventDefault();
    try {
      const r = await api("POST", "/area/comandos/ia", { programa: programa.value.trim(), detalhe: detalhe.value.trim() });
      salvarPedidos([{ tarefa_id: r.tarefa_id, programa: programa.value.trim(), criado: new Date().toISOString() }, ...pedidos()]);
      toast("Pedido criado: a IA vai documentar e você revisa antes de usar.", "ok"); d.fechar(); aoMudar();
    } catch (e) { toast(e.message, "erro"); }
  } }, el("p", { textContent: "Um agente de análise (somente leitura) recebe só o nome do programa e o formato do catálogo; pode rodar o --help. O resultado vira uma proposta marcada \"IA: revisar\"." }),
  el("label", { className: "campo" }, el("span", { textContent: "Programa" }), programa), el("label", { className: "campo" }, el("span", { textContent: "Foco" }), detalhe),
  el("div", { className: "linha fim" }, el("button", { type: "button", textContent: "Cancelar", onclick: () => d.fechar() }), el("button", { type: "submit", className: "primario", textContent: "Pedir" }))));
  requestAnimationFrame(() => programa.focus());
}

async function secaoPedidos(caixa, aoMudar) {
  const lista = pedidos();
  if (!lista.length) return;
  const ul = el("ul", { className: "pedidos-ia" });
  caixa.append(el("section", { className: "cartao-pedidos" }, el("h3", { textContent: "Pedidos à IA" }), ul));
  for (const p of lista.slice(0, 8)) {
    let estado = "?";
    try { estado = (await api("GET", `/tarefas/${p.tarefa_id}`)).estado; } catch { estado = "não encontrada"; }
    ul.append(el("li", { className: "linha" }, el("strong", { textContent: p.programa }), tag(estado, estado === "concluida" ? "ok" : estado === "falhou" ? "erro" : ""),
      el("span", { className: "espaco" }),
      el("button", { type: "button", className: "pequeno", textContent: "Ver conversa", onclick: () => { selecionarTarefa(p.tarefa_id); emitir("abrir-direita", "conversa"); } }),
      el("button", { type: "button", className: "pequeno primario", disabled: estado !== "concluida", textContent: "Importar", onclick: async () => {
        try {
          const r = await api("POST", "/area/comandos/ia/importar", { tarefa_id: p.tarefa_id });
          toast(`Importado: ${r.comandos.length} comando(s) e ${r.receitas.length} receita(s) para revisar.${r.recusados.length ? ` ${r.recusados.length} item(ns) recusado(s).` : ""}`, "ok");
          salvarPedidos(pedidos().filter((x) => x.tarefa_id !== p.tarefa_id)); emitir("comandos-mudaram"); aoMudar();
        } catch (e) { toast(e.message, "erro"); }
      } }),
      el("button", { type: "button", className: "icone pequeno", "aria-label": `Esquecer pedido ${p.programa}`, textContent: "✕", onclick: () => { salvarPedidos(pedidos().filter((x) => x.tarefa_id !== p.tarefa_id)); aoMudar(); } })));
  }
}

export async function montar(raiz) {
  raizAtual = raiz;
  limpar(raiz);
  const atualizar = (sel) => { if (sel) st.sel = sel; emitir("comandos-mudaram"); montar(raizAtual); };
  raiz.append(el("div", { className: "titulo-vista" }, el("h1", { textContent: "Comandos e receitas" }), el("span", { className: "espaco" }),
    el("button", { type: "button", textContent: "Nova receita", onclick: () => formReceita((id) => { st.aba = "receitas"; atualizar(id); }) }),
    el("button", { type: "button", textContent: "Novo comando", onclick: () => formComando((id) => { st.aba = "comandos"; atualizar(id); }) }),
    el("button", { type: "button", className: "primario", textContent: "Pedir à IA", onclick: () => formIa(() => montar(raizAtual)) })));
  let cat;
  try { cat = await carregarCatalogo(); } catch (e) { raiz.append(el("p", { className: "aviso", textContent: e.message })); return; }
  const pedidosNo = el("div");
  const filtro = el("input", { type: "search", value: st.q, placeholder: "Buscar comando ou receita", "aria-label": "Buscar comando ou receita" });
  const areaSel = el("select", { "aria-label": "Área" }, el("option", { value: "", textContent: "Todas as áreas" }), ...Object.entries(AREAS).map(([k, v]) => el("option", { value: k, textContent: v, selected: k === st.area })));
  const abas = el("div", { className: "segmentado", role: "group", "aria-label": "Tipo" }, ...["comandos", "receitas"].map((a) =>
    el("button", { type: "button", "aria-pressed": String(st.aba === a), textContent: a === "comandos" ? `Comandos (${cat.comandos.length})` : `Receitas (${cat.receitas.length})`,
      onclick: () => { st.aba = a; st.sel = null; montar(raizAtual); } })));
  const lista = el("ul", { className: "lista-catalogo", "aria-label": st.aba === "comandos" ? "Comandos" : "Receitas" });
  const detalhe = el("div", { className: "detalhe-catalogo", tabIndex: -1 });
  const desenharLista = () => {
    st.q = filtro.value; st.area = areaSel.value;
    const q = st.q.toLowerCase();
    const fonte = st.aba === "comandos" ? cat.comandos : cat.receitas;
    const vis = fonte.filter((x) => (!st.area || x.area === st.area) && (!q || JSON.stringify([x.id, x.resumo || x.titulo, x.descricao, x.programa, x.sub, x.aliases]).toLowerCase().includes(q)));
    limpar(lista);
    for (const x of vis) {
      const titulo = st.aba === "comandos" ? [x.programa, ...x.sub].join(" ") : x.titulo;
      lista.append(el("li", {}, el("button", { type: "button", className: "bloco", "aria-current": String(st.sel === x.id),
        onclick: () => { st.sel = x.id; desenharLista(); desenharDetalhe(); } },
      el("span", { className: `ponto risco-${x.risco || "baixo"}`, "aria-hidden": "true" }), el("span", { className: "trunc", textContent: titulo }),
      el("span", { className: "mudo trunc", textContent: x.resumo || x.descricao || "" }), x.origem === "ia" && !x.revisado && st.aba === "comandos" ? tag("revisar", "aviso") : null)));
    }
    if (!vis.length) lista.append(el("li", { className: "mudo", textContent: "Nada encontrado. Crie um novo ou peça à IA." }));
  };
  const desenharDetalhe = () => {
    limpar(detalhe);
    const x = (st.aba === "comandos" ? cat.comandos : cat.receitas).find((y) => y.id === st.sel);
    if (!x) detalhe.append(el("div", { className: "vazio-acao" }, el("p", { textContent: "Escolha um item à esquerda." }),
      el("p", { className: "mudo", textContent: "No terminal, o assistente usa este catálogo para explicar, completar (Tab) e apontar erros enquanto você digita." })));
    else detalhe.append(st.aba === "comandos" ? detalheComando(x, () => atualizar()) : detalheReceita(x, () => atualizar()));
  };
  filtro.addEventListener("input", desenharLista); areaSel.addEventListener("change", desenharLista);
  raiz.append(pedidosNo, el("div", { className: "catalogo-grade" }, el("div", { className: "catalogo-lado" }, abas, el("div", { className: "linha" }, filtro, areaSel), lista), detalhe));
  desenharLista(); desenharDetalhe();
  secaoPedidos(pedidosNo, () => montar(raizAtual));
}
