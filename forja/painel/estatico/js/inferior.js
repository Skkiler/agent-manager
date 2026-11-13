// Painel inferior: eventos em tempo real (SSE), painel de controle do master e oficina pixel art.
import { api } from "./api.js";
import { ouvir } from "./estado.js";
import { atualizarOficina, montarOficina } from "./oficina.js";
import { abas, dataCurta, el, limpar, tag } from "./ui.js";
import { definirPreferencia } from "./views/config.js";

let aba = "eventos";
let oficinaLigada = localStorage.getItem("forja_oficina") !== "off";
let ultimoQuadro = null;
const eventos = [];

function listaEventos(corpo) {
  corpo.append(el("ul", { id: "eventos", "aria-live": "polite", "aria-label": "Eventos" }, ...eventos.map((e) => el("li", { textContent: `#${e.seq} ${e.tipo} ${e.tarefa_id || ""} ${e.ts}` }))));
  if (!eventos.length) corpo.append(el("p", { className: "mudo", textContent: "Aguardando eventos do servidor (SSE com replay por Last-Event-ID)." }));
}

async function controle(corpo) {
  try {
    const p = await api("GET", "/controle/painel");
    corpo.append(el("div", { className: "alertas" }, ...(p.alertas.length ? p.alertas.map((a) => tag(a, "aviso")) : [tag("Nada exige atencao agora", "ok")])),
      el("div", { className: "linha so-avancado" }, tag(`quadro: ${p.quadro.abertas} abertas`), ...Object.entries(p.tarefas.por_estado).map(([k, v]) => tag(`${k}: ${v}`)), tag(`gerado ${dataCurta(p.gerado_em)}`)),
      p.tarefas.aguardando_decisao.length ? el("p", { textContent: `Aguardando decisão: ${p.tarefas.aguardando_decisao.map((t) => t.titulo).join("; ")}` }) : null,
      p.execucoes_paradas.length ? el("p", { className: "aviso", textContent: `Execuções vencidas ou sem progresso: ${p.execucoes_paradas.map((e) => e.id).join(", ")}` }) : null);
  } catch (e) { corpo.append(el("p", { className: "aviso", textContent: e.message })); }
}

function oficina(corpo) {
  const alternar = el("button", { type: "button", "aria-pressed": String(oficinaLigada), textContent: oficinaLigada ? "Desligar oficina" : "Ligar oficina",
    onclick: () => { oficinaLigada = !oficinaLigada; renderizar(); definirPreferencia("oficina_pixel", oficinaLigada).catch(() => localStorage.setItem("forja_oficina", oficinaLigada ? "on" : "off")); } });
  const cena = el("div");
  corpo.append(el("div", { className: "linha" }, alternar, el("span", { className: "mudo", textContent: "Mostra o estado real das execuções; não decide nada." })), cena);
  if (oficinaLigada) montarOficina(cena, ultimoQuadro);
}

export function renderizar() {
  const corpo = document.getElementById("inferior-corpo");
  abas(document.getElementById("inferior-abas"), [{ id: "eventos", rotulo: "Eventos" }, { id: "controle", rotulo: "Controle" }, { id: "oficina", rotulo: "Oficina" }], aba, (id) => { aba = id; renderizar(); });
  limpar(corpo);
  corpo.setAttribute("role", "tabpanel"); corpo.setAttribute("aria-labelledby", `aba-${aba}`);
  if (aba === "eventos") listaEventos(corpo); else if (aba === "controle") controle(corpo); else oficina(corpo);
}

export function iniciar() {
  ouvir("evento", (e) => { eventos.unshift(e); eventos.length = Math.min(eventos.length, 200); if (aba === "eventos") renderizar(); });
  ouvir("kanban", (q) => { ultimoQuadro = q; if (aba === "oficina" && oficinaLigada) atualizarOficina(q); });
  ouvir("oficina", (ligada) => { oficinaLigada = ligada; if (aba === "oficina") renderizar(); });
  renderizar();
}
export const atualizarControle = () => { if (aba === "controle") renderizar(); };
