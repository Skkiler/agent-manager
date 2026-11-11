// Quadro de comunicacao (blackboard): mensagens tipadas entre master, operador e agentes, com prioridade e validade.
import { api, consulta } from "../api.js";
import { agrupar, ouvir } from "../estado.js";
import { dataCurta, dialogo, el, limpar, tag, toast } from "../ui.js";

const filtros = { estado: "", tipo: "", prioridade_max: "" };
let ultimo = null;

const FAIXAS = [
  ["master", "Para o master", (m) => m.destino === "master"],
  ["operador", "Para voce", (m) => m.destino === "operador"],
  ["agentes", "Para agentes", (m) => m.destino.startsWith("agente:")],
  ["todos", "Difusao", (m) => m.destino === "todos"],
];

async function resolver(m) {
  const nota = el("input", { maxLength: 1000, placeholder: "Nota opcional" });
  const f = el("form", {}, el("label", { className: "campo" }, el("span", { textContent: "Nota de resolucao" }), nota),
    el("div", { className: "linha" }, el("button", { type: "submit", className: "primario", textContent: "Resolver" }),
      el("button", { type: "button", textContent: "Cancelar", onclick: () => d.fechar() })));
  const d = dialogo(`Resolver: ${m.assunto}`, f);
  f.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try { await api("POST", `/quadro/${m.id}/resolver`, { nota: nota.value }); d.fechar(); await atualizar(); } catch (e) { toast(e.message, "erro"); }
  });
}

function mensagem(m) {
  const aberta = m.estado === "pendente" || m.estado === "entregue";
  return el("article", { className: `msg-q ${m.estado}`, dataset: { prio: m.prioridade } },
    el("div", { className: "linha" }, tag(m.tipo), tag(`P${m.prioridade}`, m.prioridade <= 2 ? "aviso" : ""), tag(m.estado, aberta ? "" : "ok"),
      m.expira_em ? tag(`expira ${dataCurta(m.expira_em)}`, "so-avancado") : null),
    el("strong", { textContent: m.assunto }),
    el("div", { className: "mudo", textContent: `${m.origem} → ${m.destino} · ${dataCurta(m.criado_em)}` }),
    m.payload?.texto ? el("p", { className: "recolhivel", textContent: m.payload.texto }) : null,
    Object.keys(m.payload || {}).length ? el("pre", { className: "so-avancado", textContent: JSON.stringify(m.payload, null, 1) }) : null,
    (m.referencias || []).length ? el("div", { className: "linha" }, ...m.referencias.map((r) => tag(r))) : null,
    m.nota_resolucao ? el("div", { className: "mudo", textContent: `Resolvida por ${m.resolvida_por}: ${m.nota_resolucao}` }) : null,
    aberta ? el("button", { type: "button", textContent: "Resolver", onclick: () => resolver(m) }) : null);
}

export async function atualizar() {
  if (!ultimo) return;
  try {
    const [msgs, painel] = await Promise.all([
      api("GET", `/quadro?${consulta({ ...filtros, limite: 200 })}`), api("GET", "/controle/painel")]);
    limpar(ultimo.alertas);
    ultimo.alertas.append(...(painel.alertas.length ? painel.alertas.map((a) => tag(a, "aviso")) : [tag("Nada exige atencao agora", "ok")]));
    limpar(ultimo.faixas);
    ultimo.faixas.append(...FAIXAS.map(([id, rotulo, teste]) => {
      const itens = msgs.filter(teste);
      return el("section", { className: "faixa", "aria-label": `${rotulo}: ${itens.length}` }, el("h3", { textContent: `${rotulo} (${itens.length})` }),
        ...(itens.length ? itens.map(mensagem) : [el("p", { className: "mudo", textContent: "Sem mensagens", style: "padding:0 8px" })]));
    }));
  } catch (e) { limpar(ultimo.faixas); ultimo.faixas.append(el("p", { className: "aviso", textContent: `Erro: ${e.message}` })); }
}

function publicar() {
  const destinos = ["master", "operador", "todos", "agente:analista", "agente:revisor"];
  const campo = (rot, no) => el("label", { className: "campo" }, el("span", { textContent: rot }), no);
  const origem = el("select", {}, ...["operador", "master"].map((v) => el("option", { value: v, textContent: v })));
  const destino = el("select", {}, ...destinos.map((v) => el("option", { value: v, textContent: v })));
  const tipo = el("select", {}, ...["apontamento", "comando", "pergunta", "evento"].map((v) => el("option", { value: v, textContent: v })));
  const prio = el("select", {}, ...[1, 2, 3, 4, 5].map((n) => el("option", { value: n, textContent: `P${n}`, selected: n === 3 })));
  const assunto = el("input", { required: true, maxLength: 120 });
  const texto = el("textarea", { rows: 3, maxLength: 3000 });
  const refs = el("input", { placeholder: "tarefa:T-1, memoria:MEM-2 (opcional)" });
  const f = el("form", {}, campo("Origem (declarada)", origem), campo("Destino", destino), campo("Tipo", tipo), campo("Prioridade (1 = mais urgente)", prio),
    campo("Assunto", assunto), campo("Mensagem", texto), campo("Referencias (nao cole conteudo grande: use referencias)", refs),
    el("div", { className: "linha" }, el("button", { type: "submit", className: "primario", textContent: "Publicar" }),
      el("button", { type: "button", textContent: "Cancelar", onclick: () => d.fechar() })));
  const d = dialogo("Nova mensagem no quadro", f);
  f.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      await api("POST", "/quadro", { origem: origem.value, destino: destino.value, tipo: tipo.value, prioridade: Number(prio.value), assunto: assunto.value,
        payload: texto.value ? { texto: texto.value } : {}, referencias: refs.value.split(",").map((s) => s.trim()).filter(Boolean) });
      d.fechar(); toast("Mensagem publicada", "ok"); await atualizar();
    } catch (e) { toast(e.message, "erro"); }
  });
}

export function montarLateral(lat) {
  limpar(lat);
  const sel = (rot, chave, opcoes) => {
    const s = el("select", { onchange: () => { filtros[chave] = s.value; atualizar(); } }, el("option", { value: "", textContent: "Todos" }),
      ...opcoes.map((o) => el("option", { value: o, textContent: o, selected: filtros[chave] === o })));
    return el("label", { className: "campo" }, el("span", { textContent: rot }), s);
  };
  lat.append(el("h2", { textContent: "Quadro de comunicacao" }), el("button", { type: "button", className: "primario", textContent: "+ Nova mensagem", onclick: publicar }),
    sel("Estado", "estado", ["pendente", "entregue", "resolvida", "expirada"]), sel("Tipo", "tipo", ["comando", "evento", "apontamento", "pergunta", "resultado"]),
    sel("Prioridade ate", "prioridade_max", ["1", "2", "3", "4", "5"]),
    el("p", { className: "aviso", textContent: "Mensagens guardam resumo e referencias, nunca o historico completo. A origem e declarada por quem publica (token unico de operador)." }));
}

export function montar(raiz) {
  limpar(raiz);
  const alertas = el("div", { className: "alertas", role: "status" });
  const faixas = el("div", { className: "faixas" });
  raiz.append(el("div", { className: "titulo-vista" }, el("h1", { textContent: "Comunicacao" }), el("button", { type: "button", textContent: "Atualizar", onclick: atualizar })), alertas, faixas);
  ultimo = { alertas, faixas };
  atualizar();
}

const reagir = agrupar(() => { if (ultimo?.faixas.isConnected) atualizar(); });
ouvir("evento", (e) => { if (String(e.tipo).startsWith("quadro.")) reagir(); });
