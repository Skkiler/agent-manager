// Receitas: processos prontos (ex.: "vincular a um remoto e enviar") com variaveis configuraveis. Mostra cada comando com a
// explicacao, roda passo a passo no terminal (para no primeiro erro; passo arriscado pergunta) ou cola no terminal.
import { api } from "./api.js";
import { emitir, ouvir } from "./estado.js";
import { icone } from "./icones.js";
import { el, janela, limpar, tag, toast } from "./ui.js";

const AREAS = { git: "Git", docker: "Docker", python: "Python", node: "Node", http: "HTTP", terminal: "Terminal" };
let catalogo = null;

export async function carregarCatalogo(forcar = false) {
  if (!catalogo || forcar) catalogo = api("GET", "/area/comandos").catch((e) => { catalogo = null; throw e; });
  return catalogo;
}
ouvir("comandos-mudaram", () => { catalogo = null; });

/** Troca {variavel} pelo valor; {{ e }} viram chaves literais. */
export function preencher(modelo, valores) {
  return modelo.replace(/\{\{/g, "\u0000").replace(/\}\}/g, "\u0001")
    .replace(/\{([a-z_][a-z0-9_]*)\}/g, (m, nome) => (nome in valores ? valores[nome] : m))
    .replace(/\u0000/g, "{").replace(/\u0001/g, "}");
}

const executarNoTerminal = (linha) => new Promise((resolver) => emitir("terminal-executar", { linha, resolver }));

/** Janela de uma receita: variaveis -> passos (com explicacao) -> executar passo a passo. */
export async function abrirReceita(id, valoresIniciais = {}) {
  let cat;
  try { cat = await carregarCatalogo(); } catch (e) { return toast(e.message, "erro"); }
  const r = cat.receitas.find((x) => x.id === id);
  if (!r) return toast("Receita não encontrada.", "erro");
  const valores = Object.fromEntries(r.variaveis.map((v) => [v.nome, valoresIniciais[v.nome] ?? v.padrao ?? ""]));
  const passos = el("ol", { className: "passos-receita" });
  const campos = el("div", { className: "grade-campos" }, ...r.variaveis.map((v) => {
    const campo = el("input", { type: v.tipo === "porta" ? "number" : "text", value: valores[v.nome], min: v.tipo === "porta" ? 1 : undefined, max: v.tipo === "porta" ? 65535 : undefined,
      "aria-label": v.rotulo || v.nome, spellcheck: false });
    campo.addEventListener("input", () => { valores[v.nome] = campo.value; desenharPassos(); });
    return el("label", { className: "campo" }, el("span", { textContent: v.rotulo || v.nome }), campo);
  }));
  const estados = r.passos.map(() => null);
  let rodando = false;
  function desenharPassos() {
    limpar(passos);
    r.passos.forEach((p, i) => {
      const linha = preencher(p.comando, valores);
      const st = estados[i];
      passos.append(el("li", { className: `passo ${st ? (st.codigo === 0 ? "ok" : "erro") : ""}` },
        el("div", { className: "linha" }, el("code", { className: "cmd-passo", textContent: linha }), el("span", { className: "espaco" }),
          st ? tag(st.cancelado ? "cancelado" : st.codigo === 0 ? "ok" : `código ${st.codigo}`, st.codigo === 0 ? "ok" : "erro") : null,
          el("button", { type: "button", className: "icone pequeno", "aria-label": `Colar no terminal: ${linha}`, title: "Colar no terminal (sem executar)",
            onclick: () => { emitir("terminal-colar", linha); toast("Comando colado no terminal."); } }, icone("copiar", 14)),
          el("button", { type: "button", className: "pequeno", disabled: rodando, textContent: "Executar", onclick: () => rodar([i]) })),
        el("p", { className: "mudo", textContent: preencher(p.explicacao || "", valores) }),
        st?.saida ? el("pre", { className: "saida-passo", textContent: st.saida.slice(-1500) }) : null));
    });
  }
  async function rodar(indices) {
    rodando = true; desenharPassos();
    for (const i of indices) {
      const res = await executarNoTerminal(preencher(r.passos[i].comando, valores));
      estados[i] = res || { codigo: -1, cancelado: true, saida: "" };
      desenharPassos();
      if (!res || res.codigo !== 0) { if (indices.length > 1) toast(`Parou no passo ${i + 1}.`, "erro"); break; }
    }
    rodando = false; desenharPassos();
  }
  desenharPassos();
  janela(r.titulo, el("div", { className: "receita" },
    el("p", { textContent: r.descricao }),
    r.variaveis.length ? el("h3", { textContent: "Variáveis" }) : null, r.variaveis.length ? campos : null,
    el("h3", { textContent: `Passos (${r.passos.length})` }), passos,
    el("div", { className: "linha fim" },
      el("span", { className: "mudo", textContent: "Cada passo roda no terminal da pasta escolhida lá. Passo arriscado pede confirmação." }),
      el("button", { type: "button", className: "primario", textContent: "Executar todos", onclick: () => rodar(r.passos.map((_, i) => i)) }))),
  { classe: "janela-receita" });
}

/** Lista de receitas (opcionalmente de uma area). */
export async function abrirReceitas(area = "") {
  let cat;
  try { cat = await carregarCatalogo(); } catch (e) { return toast(e.message, "erro"); }
  const filtro = el("input", { type: "search", placeholder: "Filtrar receitas", "aria-label": "Filtrar receitas" });
  const areaSel = el("select", { "aria-label": "Área" }, el("option", { value: "", textContent: "Todas as áreas" }),
    ...[...new Set(cat.receitas.map((r) => r.area))].map((a) => el("option", { value: a, textContent: AREAS[a] || a, selected: a === area })));
  const lista = el("ul", { className: "lista-receitas" });
  let j = null;
  const desenhar = () => {
    const q = filtro.value.toLowerCase();
    limpar(lista);
    for (const r of cat.receitas.filter((x) => (!areaSel.value || x.area === areaSel.value) && (!q || `${x.titulo} ${x.descricao}`.toLowerCase().includes(q)))) {
      lista.append(el("li", {}, el("button", { type: "button", className: "bloco cartao-receita", onclick: () => { j?.fechar(); abrirReceita(r.id); } },
        el("span", { className: "tag", textContent: AREAS[r.area] || r.area }), el("strong", { className: "trunc", textContent: r.titulo }),
        el("span", { className: "mudo trunc", textContent: r.descricao }), r.origem !== "padrao" ? tag(r.origem === "ia" ? "IA" : "sua") : null)));
    }
    if (!lista.children.length) lista.append(el("li", { className: "mudo", textContent: "Nenhuma receita com esse filtro." }));
  };
  filtro.addEventListener("input", desenhar); areaSel.addEventListener("change", desenhar);
  desenhar();
  j = janela("Receitas (processos passo a passo)", el("div", {}, el("div", { className: "linha" }, filtro, areaSel), lista,
    el("p", { className: "mudo", textContent: "Crie as suas em Comandos > Nova receita, ou peça à IA para documentar um programa." })));
  requestAnimationFrame(() => filtro.focus());
}

ouvir("receita", (x) => (typeof x === "string" ? abrirReceita(x) : abrirReceita(x.id, x.valores || {})));
ouvir("receitas", (area) => abrirReceitas(area || ""));
