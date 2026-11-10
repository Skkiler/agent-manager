// Menu de configuracoes: categorias, abas Gerais/Avancadas, cada opcao explicada com exemplos e consequencias.
// O servidor descreve as opcoes (registro declarativo); aqui so se desenha e se envia o que mudou.
import { api } from "../api.js";
import { definirNivel, emitir, estado, selecionarTarefa } from "../estado.js";
import { el, limpar, tag, toast } from "../ui.js";

const ESCOPOS = [["arquitetura", "Arquitetura"], ["busca_e_memoria", "Busca e memoria"], ["ferramentas", "Ferramentas"],
  ["interface", "Interface"], ["seguranca", "Seguranca"], ["custo_e_modelos", "Custo e modelos"]];
const ESFORCOS = [["", "padrao"], ["low", "baixo"], ["medium", "medio"], ["high", "alto"], ["xhigh", "muito alto"], ["max", "maximo"]];
const RISCO = { baixo: "ok", medio: "aviso", alto: "erro" };
const ctx = { raiz: null, prefs: null, rascunho: {}, categoria: "agentes", aba: "geral" };

export async function recarregar() {
  const c = await api("GET", "/configuracao");
  estado.config = c;
  const exec = c.partes.find((p) => p.id === "execucao");
  document.getElementById("st-config").textContent = `config v${c.versao}`;
  document.getElementById("st-modelo").textContent = `modelo: ${exec?.modelo_efetivo ?? "—"}`;
  return c;
}

const itensDe = (prefs) => prefs.categorias.flatMap((c) => c.itens);
const valorDe = (p) => (p.id in ctx.rascunho ? ctx.rascunho[p.id] : p.valor);
const igual = (a, b) => JSON.stringify(a) === JSON.stringify(b);

/** Aplica ao painel o que e puramente visual (tema, detalhe, oficina) a partir das preferencias salvas. */
export function aplicarPreferencias(prefs) {
  const v = Object.fromEntries(itensDe(prefs).filter((p) => p.persistida).map((p) => [p.id, p.valor]));
  if (v.tema === "claro" || v.tema === "escuro") document.documentElement.dataset.tema = v.tema; else delete document.documentElement.dataset.tema;
  if (v.nivel_detalhe) { definirNivel(v.nivel_detalhe); const s = document.getElementById("nivel"); if (s) s.value = v.nivel_detalhe; }
  if (typeof v.oficina_pixel === "boolean") { estado.oficina = v.oficina_pixel; localStorage.setItem("forja_oficina", v.oficina_pixel ? "on" : "off"); emitir("oficina", v.oficina_pixel); }
}

export async function carregarPreferencias() {
  ctx.prefs = await api("GET", "/preferencias");
  aplicarPreferencias(ctx.prefs);
  return ctx.prefs;
}

/** Salva UMA preferencia direto (atalhos fora do menu, como o botao da oficina). */
export async function definirPreferencia(id, valor) {
  const atual = ctx.prefs ?? await carregarPreferencias();
  ctx.prefs = await api("PUT", "/preferencias", { expected_version: atual.versao, valores: { [id]: valor } });
  aplicarPreferencias(ctx.prefs);
}

// ---------------------------------------------------------------- controles por tipo
function controle(p) {
  const v = valorDe(p);
  const definir = (novo) => { if (igual(novo, p.valor)) delete ctx.rascunho[p.id]; else ctx.rascunho[p.id] = novo; atualizarBarra(); };
  const rotulo = `${p.rotulo}`;
  if (p.tipo === "bool") {
    const c = el("input", { type: "checkbox", checked: !!v, "aria-label": rotulo, onchange: () => definir(c.checked) });
    return { no: el("label", { className: "linha" }, c, el("span", { textContent: "Ativado" })), aplicar: (x) => { c.checked = !!x; } };
  }
  if (p.tipo === "int") {
    const c = el("input", { type: "number", min: p.minimo, max: p.maximo, value: v, "aria-label": rotulo, oninput: () => c.value !== "" && definir(Number(c.value)) });
    return { no: el("label", { className: "linha" }, c, el("span", { className: "mudo", textContent: `${p.unidade} (de ${p.minimo} a ${p.maximo})` })), aplicar: (x) => { c.value = x; } };
  }
  if (p.tipo === "selecao") {
    const c = el("select", { "aria-label": rotulo, onchange: () => definir(c.value) }, ...p.opcoes.map(([val, r]) => el("option", { value: val, textContent: r })));
    c.value = v;
    return { no: c, aplicar: (x) => { c.value = x; } };
  }
  if (p.tipo === "tags") {
    // Tags combinaveis: cada uma acrescenta uma caracteristica. O texto exato enviado ao agente fica visivel na tela.
    const det = new Map(p.detalhes.map((d) => [d.id, d]));
    const rot = new Map(p.opcoes);
    let atual = new Set(v || []);
    const caixa = el("div", { className: "tags", role: "group", "aria-label": rotulo });
    const explica = el("ul", { className: "tags-explicadas" });
    const desenharTags = () => {
      limpar(caixa); limpar(explica);
      const bloqueadas = new Set([...atual].flatMap((id) => det.get(id)?.conflitos || []));
      for (const [id, r] of p.opcoes) {
        const d = det.get(id);
        const on = atual.has(id), bloq = !on && bloqueadas.has(id);
        caixa.append(el("button", { type: "button", className: `tag-opcao${on ? " ativa" : ""}`, "aria-pressed": String(on), disabled: bloq,
          title: bloq ? `Contradiz ${[...atual].filter((a) => det.get(a)?.conflitos.includes(id)).map((a) => rot.get(a)).join(", ")}` : d.descricao,
          textContent: r, onclick: () => { on ? atual.delete(id) : atual.add(id); definir([...atual]); desenharTags(); } }));
      }
      for (const id of atual) {
        const d = det.get(id);
        explica.append(el("li", {}, el("strong", { textContent: `${rot.get(id)}: ` }), d.descricao,
          d.efeito ? el("div", { className: "mudo", textContent: `Efeito: ${d.efeito}` }) : null,
          el("div", { className: "mono mudo", textContent: `Enviado ao agente: ${d.instrucao}` })));
      }
      if (!atual.size) explica.append(el("li", { className: "mudo", textContent: "Nenhuma tag: o agente usa o comportamento padrao." }));
    };
    desenharTags();
    return { no: el("div", {}, caixa, explica), aplicar: (x) => { atual = new Set(x || []); desenharTags(); } };
  }
  if (p.tipo === "texto") {
    const c = el("textarea", { rows: 6, maxLength: p.max_texto, "aria-label": rotulo, placeholder: "Ex.: Commits em portugues. Prefira pytest. Nunca altere migrations sem perguntar." });
    const cont = el("span", { className: "mudo", role: "status" });
    const contar = () => { cont.textContent = `${c.value.length} / ${p.max_texto} caracteres (~${Math.ceil(c.value.length / 4)} tokens por tarefa)`; };
    c.value = v || "";
    c.addEventListener("input", () => { definir(c.value); contar(); }); contar();
    return { no: el("div", {}, c, cont), aplicar: (x) => { c.value = x || ""; contar(); } };
  }
  if (p.tipo === "pastas") {
    const c = el("textarea", { rows: 4, spellcheck: false, "aria-label": `${rotulo} (um caminho por linha)`, placeholder: "Um caminho completo por linha",
      oninput: () => definir(c.value.split("\n").map((s) => s.trim()).filter(Boolean)) });
    c.value = (v || []).join("\n");
    return { no: c, aplicar: (x) => { c.value = (x || []).join("\n"); } };
  }
  return null;
}

function cartao(p) {
  const ctl = controle(p);
  const fonte = p.fonte === "ambiente" ? tag("vem do ambiente", "aviso") : null;
  const exemplos = p.exemplos.length && ctl ? el("div", { className: "linha", role: "group", "aria-label": `Exemplos para ${p.rotulo}` },
    ...p.exemplos.map((e) => el("button", { type: "button", className: "exemplo", title: e.descricao, textContent: e.rotulo,
      onclick: () => { ctx.rascunho[p.id] = e.valor; if (igual(e.valor, p.valor)) delete ctx.rascunho[p.id]; ctl.aplicar(e.valor); atualizarBarra(); } }))) : null;
  const explicados = p.exemplos.length ? el("ul", { className: "exemplos-lista" }, ...p.exemplos.map((e) => el("li", {}, el("strong", { textContent: `${e.rotulo}: ` }), el("span", { textContent: e.descricao })))) : null;
  const restaurar = p.persistida && p.tipo !== "perfil" ? el("button", { type: "button", textContent: "Restaurar padrão",
    title: `Padrão: ${padraoTexto(p)}`, onclick: () => restaurarPadrao(p) }) : null;
  return el("section", { className: "card opcao", "data-pref": p.id },
    el("div", { className: "linha" }, el("h3", { textContent: p.rotulo }), tag(`risco ${p.risco}`, RISCO[p.risco] || ""), ...(p.reinicia ? [tag("exige reiniciar", "aviso")] : []), ...(fonte ? [fonte] : [])),
    el("p", { textContent: p.explicacao }),
    ...(ctl ? [ctl.no] : []), ...(exemplos ? [exemplos] : []),
    el("details", {}, el("summary", { textContent: "Exemplos e consequências" }),
      ...(explicados ? [explicados] : []),
      ...(p.se_ligar ? [el("p", {}, el("strong", { textContent: p.tipo === "bool" ? "Se ativar: " : "Ao escolher mais: " }), p.se_ligar)] : []),
      ...(p.se_desligar ? [el("p", {}, el("strong", { textContent: p.tipo === "bool" ? "Se desativar: " : "Ao escolher menos: " }), p.se_desligar)] : [])),
    el("div", { className: "linha mudo" }, el("span", { textContent: `Padrão: ${padraoTexto(p)}` }), ...(restaurar ? [restaurar] : [])));
}

function padraoTexto(p) {
  if (p.tipo === "bool") return p.padrao ? "ativado" : "desativado";
  if (p.tipo === "pastas") return "nenhuma pasta";
  if (p.tipo === "tags") return "nenhuma tag";
  if (p.tipo === "texto") return "vazio";
  if (p.tipo === "selecao") return (p.opcoes.find(([v]) => v === p.padrao) || [null, p.padrao])[1];
  return `${p.padrao} ${p.unidade}`.trim();
}

async function restaurarPadrao(p) {
  try {
    ctx.prefs = await api("POST", "/preferencias/restaurar", { expected_version: ctx.prefs.versao, ids: [p.id] });
    delete ctx.rascunho[p.id]; aplicarPreferencias(ctx.prefs); toast("Padrão restaurado", "ok"); desenhar();
  } catch (e) { toast(e.status === 409 ? "As preferências mudaram em outra aba. Recarregue." : e.message, "erro"); }
}

// ---------------------------------------------------------------- cartoes especiais
function cartaoInfo(p) {
  return el("section", { className: "card opcao", "data-pref": p.id }, el("h3", { textContent: p.rotulo }), el("p", { textContent: p.explicacao }),
    ...(p.texto ? [el("pre", { className: "saida", textContent: p.texto })] : []));
}

function cartaoPerfil(p) {
  const caixa = el("div", { role: "status" }, el("p", { className: "mudo", textContent: "Carregando…" }));
  api("GET", "/usuario/perfil").then((r) => {
    limpar(caixa);
    const linhas = Object.entries(r).filter(([, x]) => ["string", "boolean", "number"].includes(typeof x));
    caixa.append(el("dl", { className: "perfil" }, ...linhas.flatMap(([k, x]) => [el("dt", { textContent: k.replaceAll("_", " ") }), el("dd", { className: "mono", textContent: String(x) })])),
      el("p", {}, el("strong", { textContent: "Sobe ao Git: " }), (r.sobe_ao_git || []).join("; ")),
      el("p", {}, el("strong", { textContent: "Fica só neste computador: " }), (r.fica_so_aqui || []).join("; ")));
  }).catch((e) => { limpar(caixa); caixa.append(el("p", { className: "aviso", textContent: e.message })); });
  return el("section", { className: "card opcao", "data-pref": p.id }, el("h3", { textContent: p.rotulo }), el("p", { textContent: p.explicacao }), caixa);
}

function cartaoModelos(p) {
  const caixa = el("div");
  Promise.all([recarregar(), api("GET", "/configuracao/modelos").catch(() => ({ modelos: [], aviso: "Nao foi possivel consultar os modelos." }))])
    .then(([c, catalogo]) => caixa.append(...secaoModelos(c, catalogo)))
    .catch((e) => caixa.append(el("p", { className: "aviso", textContent: e.message })));
  return el("section", { className: "card opcao", "data-pref": p.id }, el("h3", { textContent: p.rotulo }), el("p", { textContent: p.explicacao }), caixa,
    el("details", {}, el("summary", { textContent: "Exemplos e consequências" }),
      ...p.exemplos.map((e) => el("p", {}, el("strong", { textContent: `${e.rotulo}: ` }), e.descricao)),
      ...(p.se_ligar ? [el("p", {}, el("strong", { textContent: "Modelo mais forte: " }), p.se_ligar)] : []),
      ...(p.se_desligar ? [el("p", {}, el("strong", { textContent: "Modelo mais leve: " }), p.se_desligar)] : [])));
}

function secaoModelos(c, catalogo) {
  const custos = new Map(catalogo.modelos.map((m) => [m.id, m]));
  const lista = el("datalist", { id: "lista-modelos" }, ...catalogo.modelos.map((m) => el("option", { value: m.id, label: `${m.custo}x creditos — ${m.descricao}` })));
  const campos = new Map();
  const linhas = c.partes.map((p) => {
    const modelo = el("input", { value: p.modelo, maxLength: 80, list: "lista-modelos", placeholder: p.usa_modelo ? "vazio = padrao da conta" : "sem modelo", disabled: !p.usa_modelo,
      "aria-label": `Modelo de ${p.rotulo}`, pattern: "[A-Za-z0-9][A-Za-z0-9._:/\\-]{0,79}" });
    const esforco = el("select", { disabled: !p.usa_modelo, "aria-label": `Esforco de ${p.rotulo}` }, ...ESFORCOS.map(([v, r]) => el("option", { value: v, textContent: r, selected: v === p.esforco })));
    const custo = el("span", { className: "mudo", role: "status" });
    const mostrar = () => { const m = custos.get(modelo.value.trim()); custo.textContent = m ? `${m.custo}x creditos` : ""; };
    modelo.addEventListener("input", mostrar); mostrar();
    campos.set(p.id, { modelo, esforco });
    return el("tr", {}, el("td", {}, el("strong", { textContent: p.rotulo }), el("div", { className: "mudo", textContent: p.descricao })),
      el("td", {}, modelo, custo), el("td", {}, esforco), el("td", { className: "so-avancado mono", textContent: p.usa_modelo ? p.modelo_efetivo : "deterministico" }));
  });
  const salvar = el("button", { type: "button", className: "primario", textContent: "Salvar modelos", onclick: async () => {
    const partes = {};
    for (const [id, f] of campos) if (!f.modelo.disabled && (f.modelo.value.trim() || f.esforco.value)) partes[id] = { modelo: f.modelo.value.trim(), esforco: f.esforco.value };
    try {
      await api("PUT", "/configuracao", { expected_version: c.versao, configuracao: { partes } });
      toast("Modelos salvos", "ok"); await recarregar(); desenhar();
    } catch (e) { toast(e.status === 409 ? "A configuracao mudou em outra aba. Recarregue." : e.message, "erro"); }
  } });
  return [el("p", { className: "aviso", textContent: catalogo.modelos.length
    ? "Os modelos vem da sua conta, com o custo relativo em creditos (menor e mais barato). Vazio usa o padrao da conta."
    : `${catalogo.aviso || ""} Um nome invalido faz o Kiro recusar a sessao.` }), lista,
  el("table", {}, el("thead", {}, el("tr", {}, el("th", { textContent: "Parte" }), el("th", { textContent: "Modelo" }), el("th", { textContent: "Esforco" }), el("th", { className: "so-avancado", textContent: "Efetivo" }))), el("tbody", {}, ...linhas)),
  el("div", { className: "linha" }, salvar, tag(`versao ${c.versao}`, "so-avancado"))];
}

function cartaoRevisao(p) {
  const marcas = ESCOPOS.map(([v, r]) => el("label", {}, el("input", { type: "checkbox", value: v, checked: v === "arquitetura" }), ` ${r}`));
  const web = el("input", { type: "checkbox" });
  const exec = el("input", { type: "checkbox" });
  const saida = el("div", { role: "status", "aria-live": "polite" });
  const pedir = el("button", { type: "button", className: "primario", textContent: "Solicitar revisao", onclick: async () => {
    const escopo = marcas.map((l) => l.querySelector("input")).filter((i) => i.checked).map((i) => i.value);
    if (!escopo.length) return toast("Escolha ao menos um eixo.", "erro");
    if (exec.checked && !confirm("Executar agora consome creditos do provedor de IA. Continuar?")) return;
    pedir.disabled = true;
    try {
      const r = await api("POST", "/revisoes", { escopo, pesquisar_web: web.checked, executar: exec.checked });
      limpar(saida);
      saida.append(el("p", { textContent: exec.checked ? "Revisao iniciada." : "Revisao criada e preparada (nao executada)." }),
        el("button", { type: "button", textContent: "Abrir no quadro", onclick: () => { selecionarTarefa(r.tarefa.id); emitir("ir", "tarefas"); } }),
        el("details", { className: "so-avancado" }, el("summary", { textContent: "fatos medidos enviados ao agente" }), el("pre", { className: "saida", textContent: JSON.stringify(r.snapshot, null, 1) })));
    } catch (e) { toast(e.message, "erro"); } finally { pedir.disabled = false; }
  } });
  return el("section", { className: "card opcao", "data-pref": p.id }, el("h3", { textContent: p.rotulo }), el("p", { textContent: p.explicacao }),
    el("fieldset", {}, el("legend", { className: "mudo", textContent: "Eixos" }), ...marcas.map((m) => el("div", {}, m))),
    el("label", {}, web, " pedir pesquisa de novidades (passa pelas aprovacoes por acao)"), el("br"),
    el("label", {}, exec, " executar agora (consome creditos)"), el("div", { className: "linha" }, pedir), saida);
}

const ESPECIAIS = { info: cartaoInfo, perfil: cartaoPerfil, modelos: cartaoModelos, revisao: cartaoRevisao };
const montarItem = (p) => (ESPECIAIS[p.tipo] ?? cartao)(p);

// ---------------------------------------------------------------- tela
function atualizarBarra() {
  const n = Object.keys(ctx.rascunho).length;
  const barra = document.getElementById("barra-config");
  if (!barra) return;
  barra.querySelector("[data-contagem]").textContent = n ? `${n} alteração(ões) não salva(s)` : "Nenhuma alteração pendente";
  barra.querySelectorAll("button").forEach((b) => { b.disabled = !n; });
}

async function salvar() {
  try {
    ctx.prefs = await api("PUT", "/preferencias", { expected_version: ctx.prefs.versao, valores: ctx.rascunho });
    ctx.rascunho = {}; aplicarPreferencias(ctx.prefs); toast("Configurações salvas", "ok"); desenhar();
  } catch (e) { toast(e.status === 409 ? "As preferências mudaram em outra aba. Recarregue." : e.message, "erro"); }
}

function trocar(cat, aba) {
  if (cat) ctx.categoria = cat;
  if (aba) ctx.aba = aba;
  desenhar(); desenharLateral();
}

let latEl = null;
function desenharLateral() {
  if (!latEl || !ctx.prefs) return;
  limpar(latEl);
  latEl.append(el("h2", { textContent: "Configurações" }),
    el("nav", { "aria-label": "Categorias de configuração" }, ...ctx.prefs.categorias.map((c) =>
      el("button", { type: "button", className: c.id === ctx.categoria ? "primario bloco" : "bloco", "aria-current": c.id === ctx.categoria ? "page" : "false",
        textContent: c.rotulo, onclick: () => trocar(c.id) }))));
}

export function montarLateral(lat) {
  latEl = lat;
  desenharLateral();
  if (!ctx.prefs) lat.append(el("p", { className: "mudo", textContent: "Carregando categorias…" }));
}

function desenhar() {
  const raiz = ctx.raiz;
  if (!raiz || !ctx.prefs) return;
  limpar(raiz);
  const cat = ctx.prefs.categorias.find((c) => c.id === ctx.categoria) ?? ctx.prefs.categorias[0];
  const gerais = cat.itens.filter((p) => p.nivel === "geral");
  const avancadas = cat.itens.filter((p) => p.nivel === "avancado");
  const mostrar = ctx.aba === "geral" ? gerais : avancadas;
  const aba = (id, rotulo, n) => el("button", { type: "button", role: "tab", "aria-selected": String(ctx.aba === id), className: ctx.aba === id ? "primario" : "",
    textContent: `${rotulo} (${n})`, onclick: () => trocar(null, id) });
  raiz.append(el("div", { className: "titulo-vista" }, el("h1", { textContent: cat.rotulo })), el("p", { className: "mudo", textContent: cat.descricao }),
    el("div", { className: "linha", role: "tablist", "aria-label": "Tipo de configuração" }, aba("geral", "Gerais", gerais.length), aba("avancado", "Avançadas", avancadas.length)),
    ...ctx.prefs.avisos.map((a) => el("p", { className: "aviso", role: "status", textContent: a })),
    el("div", { id: "lista-config", className: "grade", style: "grid-template-columns:repeat(auto-fit,minmax(380px,1fr))" },
      ...(mostrar.length ? mostrar.map(montarItem) : [el("p", { className: "mudo", textContent: "Nenhuma opção nesta aba." })])),
    el("div", { id: "barra-config", className: "linha barra-salvar" }, el("span", { "data-contagem": "", className: "mudo", role: "status" }),
      el("button", { type: "button", className: "primario", textContent: "Salvar alterações", onclick: salvar }),
      el("button", { type: "button", textContent: "Descartar", onclick: () => { ctx.rascunho = {}; desenhar(); } }),
      tag(`versão ${ctx.prefs.versao}`, "so-avancado")));
  atualizarBarra();
}

export async function montar(raiz) {
  ctx.raiz = raiz;
  limpar(raiz);
  raiz.append(el("p", { className: "mudo", textContent: "Carregando configurações…" }));
  try { await carregarPreferencias(); desenhar(); desenharLateral(); recarregar().catch(() => {}); }
  catch (e) { limpar(raiz); raiz.append(el("p", { className: "aviso", textContent: e.message })); }
}
