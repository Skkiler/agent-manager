// Catalogo de ferramentas N0: contrato, execucao manual e custo observado (tokens estimados).
import { api } from "../api.js";
import { el, limpar, tag, toast } from "../ui.js";

let ctx = {};
let catalogo = [];
let escolhida = null;

function exemplo(schema) {
  const saida = {};
  for (const [nome, p] of Object.entries(schema.properties || {})) {
    if ("default" in p) { if (nome !== "texto") saida[nome] = p.default; continue; }
    if (!(schema.required || []).includes(nome)) continue;
    saida[nome] = p.type === "integer" ? 1 : p.type === "boolean" ? false : p.type === "array" ? [] : p.type === "object" ? {} : "";
  }
  return saida;
}

function formulario(f) {
  const entrada = el("textarea", { rows: 7, "aria-label": "Entrada em JSON", spellcheck: false, className: "mono", value: JSON.stringify(exemplo(f.entrada), null, 2) });
  const saida = el("div", { role: "status", "aria-live": "polite" });
  const props = Object.entries(f.entrada.properties || {}).map(([k, p]) => `${k}: ${p.type || "any"}${(f.entrada.required || []).includes(k) ? "*" : ""}`);
  const rodar = el("button", { type: "button", className: "primario", disabled: !f.disponivel, textContent: f.disponivel ? "Executar" : "Indisponivel (defina APP_TOOLS_ROOTS)",
    onclick: async () => {
      let corpo;
      try { corpo = JSON.parse(entrada.value || "{}"); } catch { return toast("A entrada precisa ser um JSON valido.", "erro"); }
      rodar.disabled = true; limpar(saida);
      try {
        const r = await api("POST", `/ferramentas/${f.id}/executar`, { entrada: corpo });
        saida.append(el("div", { className: "linha" }, tag(r.ferramenta), tag(`bruto ~${r.tokens_origem} tok`), tag(`resumo ~${r.tokens_resumo} tok`, "ok"),
          tag(`reducao ${(r.reducao * 100).toFixed(0)}%`, r.reducao > 0.3 ? "ok" : "aviso"), r.truncado ? tag("truncado", "aviso") : null, r.fallback_de ? tag(`fallback de ${r.fallback_de}`, "aviso") : null),
        ...r.avisos.map((a) => el("p", { className: "aviso", textContent: a })), el("pre", { className: "saida", textContent: r.resumo }),
        el("details", { className: "so-avancado" }, el("summary", { textContent: "dados estruturados" }), el("pre", { className: "saida", textContent: JSON.stringify(r.dados, null, 1) })));
        carregarEstatisticas();
      } catch (e) { saida.append(el("p", { className: "aviso", textContent: e.message })); } finally { rodar.disabled = !f.disponivel; }
    } });
  return el("section", {}, el("h1", { textContent: f.id }), el("p", { textContent: f.descricao }),
    el("div", { className: "linha" }, tag(`risco: ${f.risco}`), f.fallback ? tag(`fallback: ${f.fallback}`) : null, f.usa_arquivos ? tag("le arquivos autorizados") : tag("so texto")),
    el("p", { className: "mudo so-avancado mono", textContent: `entrada: { ${props.join(", ")} }` }), entrada, el("div", { className: "linha" }, rodar), saida,
    el("p", { className: "aviso", textContent: "Somente leitura; sem shell, sem rede. A saida e dado nao confiavel e tokens sao estimativas." }));
}

async function carregarEstatisticas() {
  if (!ctx.stats) return;
  try {
    const s = await api("GET", "/ferramentas/estatisticas");
    limpar(ctx.stats);
    const linhas = Object.entries(s);
    ctx.stats.append(el("h2", { textContent: "Custo observado nesta sessao do servidor" }), linhas.length ? el("table", {}, el("thead", {}, el("tr", {}, ...["ferramenta", "chamadas", "erros", "fallbacks", "tokens bruto", "tokens resumo", "ms medio"].map((h) => el("th", { textContent: h })))),
      el("tbody", {}, ...linhas.map(([k, v]) => el("tr", {}, ...[k, v.chamadas, v.erros, v.fallbacks, v.tokens_origem, v.tokens_resumo, v.ms_medio].map((x) => el("td", { textContent: String(x) })))))) : el("p", { className: "mudo", textContent: "Nenhuma chamada ainda." }));
  } catch { /* estatistica e opcional */ }
}

function mostrar() {
  if (!ctx.corpo) return;
  limpar(ctx.corpo);
  const f = catalogo.find((x) => x.id === escolhida);
  ctx.corpo.append(f ? formulario(f) : el("p", { className: "mudo", textContent: "Escolha uma ferramenta na barra lateral." }));
  for (const b of ctx.lista?.querySelectorAll("button") || []) b.setAttribute("aria-current", String(b.dataset.id === escolhida));
}

export async function montarLateral(lat) {
  limpar(lat);
  ctx.lista = el("ul", { className: "lista-notas", "aria-label": "Ferramentas" });
  lat.append(el("h2", { textContent: "Ferramentas" }), ctx.lista);
  try {
    catalogo = await api("GET", "/ferramentas");
    ctx.lista.append(...catalogo.map((f) => el("li", {}, el("button", { type: "button", dataset: { id: f.id }, textContent: `${f.disponivel ? "" : "⊘ "}${f.id}`, onclick: () => { escolhida = f.id; mostrar(); } }))));
  } catch (e) { lat.append(el("p", { className: "aviso", textContent: e.message })); }
  mostrar();
}

export function montar(raiz) {
  limpar(raiz);
  ctx.corpo = el("div"); ctx.stats = el("div");
  raiz.append(el("div", { className: "titulo-vista" }, el("h1", { textContent: "Ferramentas do orquestrador" })), ctx.corpo, ctx.stats);
  mostrar(); carregarEstatisticas();
}
