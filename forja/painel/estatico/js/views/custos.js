// Painel de custo: chamadas de modelo, tokens e creditos ESTIMADOS (dia, parte, modelo, tarefa) + roteamento aprendido.
// So leitura. Os numeros vem do servidor e sao rotulados como estimativa (o ACP nao informa creditos cobrados).
import { api } from "../api.js";
import { ouvir } from "../estado.js";
import { el, limpar, tag } from "../ui.js";

let ctx = { raiz: null, dias: 30 };
const num = (n) => Number(n || 0).toLocaleString("pt-BR", { maximumFractionDigits: 2 });

function cartao(rotulo, valor, dica = "") {
  return el("div", { className: "card metrica", title: dica }, el("span", { className: "mudo", textContent: rotulo }), el("strong", { textContent: valor }));
}

function barras(dias) {
  const max = Math.max(1, ...dias.map((d) => d.creditos_estimados || 0));
  const lista = el("ol", { className: "barras", "aria-label": "Créditos estimados por dia" });
  for (const d of dias.slice(-31)) {
    const barra = el("span", { className: "barra" });
    barra.style.setProperty("--v", String((d.creditos_estimados || 0) / max)); // CSSOM (permitido pela CSP)
    lista.append(el("li", { title: `${d.dia}: ${num(d.creditos_estimados)} créditos, ${d.execucoes} execução(ões)` },
      barra, el("span", { className: "sr-only", textContent: `${d.dia}: ${num(d.creditos_estimados)} créditos estimados` }),
      el("small", { "aria-hidden": "true", textContent: d.dia.slice(5) })));
  }
  return dias.length ? lista : el("p", { className: "mudo", textContent: "Sem execuções no período." });
}

function tabela(titulo, linhas, colunas) {
  if (!linhas.length) return el("section", {}, el("h2", { textContent: titulo }), el("p", { className: "mudo", textContent: "Nada no período." }));
  return el("section", {}, el("h2", { textContent: titulo }), el("table", { className: "tabela" },
    el("thead", {}, el("tr", {}, ...colunas.map(([, r]) => el("th", { scope: "col", textContent: r })))),
    el("tbody", {}, ...linhas.map((l) => el("tr", {}, ...colunas.map(([k]) => el("td", { textContent: typeof l[k] === "number" ? num(l[k]) : String(l[k] ?? "") })))))));
}

async function carregar() {
  const raiz = ctx.raiz;
  if (!raiz?.isConnected) return;
  const corpo = raiz.querySelector(".custos-corpo");
  try {
    const [p, rotas] = await Promise.all([api("GET", `/custos?dias=${ctx.dias}`), api("GET", "/roteamento/estatisticas").catch(() => null)]);
    limpar(corpo);
    const t = p.total;
    corpo.append(
      ...(p.alertas || []).map((a) => el("p", { className: "aviso alerta-custo", role: "alert", textContent: a })),
      el("p", { className: "aviso", textContent: p.nota + (p.catalogo_disponivel ? "" : " Lista de modelos indisponível agora: todos valem 1,00x.") }),
      el("div", { className: "metricas" }, cartao("Créditos estimados", num(t.creditos_estimados), "turnos x multiplicador do modelo"),
        cartao("Chamadas de modelo", num(t.chamadas)), cartao("Execuções", `${num(t.execucoes)}${t.simuladas ? ` (${t.simuladas} simuladas)` : ""}`),
        cartao("Tokens enviados (est.)", num(t.tokens_entrada)), cartao("Tokens recebidos (est.)", num(t.tokens_saida))),
      el("section", {}, el("h2", { textContent: "Por dia" }), barras(p.por_dia)),
      tabela("Por parte do sistema", Object.entries(p.por_parte).map(([k, v]) => ({ parte: k, ...v })), [["parte", "Parte"], ["turnos", "Turnos"], ["creditos_estimados", "Créditos (est.)"]]),
      tabela("Por modelo", Object.entries(p.por_modelo).map(([k, v]) => ({ modelo: k, ...v })), [["modelo", "Modelo"], ["turnos", "Turnos"], ["multiplicador", "Multiplicador"], ["creditos_estimados", "Créditos (est.)"]]),
      tabela("Tarefas mais caras", p.mais_caras, [["titulo", "Tarefa"], ["creditos_estimados", "Créditos (est.)"]]));
    if (rotas) {
      corpo.append(el("section", {}, el("h2", {}, "Roteamento que aprende ", tag(rotas.ativo ? "ligado" : "desligado", rotas.ativo ? "ok" : "")),
        el("p", { className: "mudo", textContent: "Taxa de sucesso por nível de tarefa. Abaixo de 60% em 5+ execuções, o nível sobe um degrau (mais planejamento)." }),
        tabela("", Object.entries(rotas.por_nivel).map(([k, v]) => ({ nivel: k, execucoes: v.execucoes, taxa: `${Math.round(v.taxa * 100)}%` })),
          [["nivel", "Nível"], ["execucoes", "Execuções"], ["taxa", "Sucesso"]])));
    }
  } catch (e) { limpar(corpo); corpo.append(el("p", { className: "aviso", textContent: `Erro: ${e.message}` })); }
}

export function montar(raiz) {
  limpar(raiz);
  const periodo = el("select", { "aria-label": "Período", onchange: () => { ctx.dias = Number(periodo.value); carregar(); } },
    ...[[7, "7 dias"], [30, "30 dias"], [90, "90 dias"], [365, "1 ano"]].map(([v, r]) => el("option", { value: v, textContent: r, selected: v === ctx.dias })));
  const vista = el("div", { className: "custos" }, el("div", { className: "titulo-vista" }, el("h1", { textContent: "Custo estimado" }), periodo,
    el("button", { type: "button", textContent: "Atualizar", onclick: carregar })), el("div", { className: "custos-corpo", role: "region", "aria-live": "polite" },
    el("p", { className: "mudo", textContent: "Carregando…" })));
  raiz.append(vista);
  ctx.raiz = vista;
  carregar();
}

let espera = null;
ouvir("evento", (e) => {
  if (!/^execucao\.(concluida|falhou|bloqueada|pausada|cancelada|expirada)$/.test(String(e.tipo)) || !ctx.raiz?.isConnected) return;
  clearTimeout(espera); espera = setTimeout(carregar, 800);
});
