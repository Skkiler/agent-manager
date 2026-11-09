// Integracoes: o que funciona hoje (local, gratuito, sem credencial) e o que depende de aprovacao do operador.
import { api } from "../api.js";
import { el, limpar, tag } from "../ui.js";

function cartao(c) {
  return el("article", { className: "card" },
    el("div", { className: "linha" }, el("h3", { textContent: c.nome }), el("span", { className: "espaco" }),
      tag(c.estado === "implementado" ? (c.disponivel ? "disponivel" : "ferramenta ausente") : "requer aprovacao", c.disponivel ? "ok" : "aviso")),
    el("div", { className: "linha" }, tag(c.categoria), tag(c.custo), tag(c.rede ? "usa rede" : "local"), tag(c.credencial ? "usa credencial" : "sem credencial")),
    el("p", { textContent: c.como_usar }),
    c.ferramentas.length ? el("p", { className: "mudo so-avancado mono", textContent: c.ferramentas.join(", ") }) : null,
    c.riscos.length ? el("ul", {}, ...c.riscos.map((r) => el("li", { className: "mudo", textContent: r }))) : null,
    c.aprovacao ? el("p", { className: "aviso", textContent: `Para ativar, voce precisa aprovar: ${c.aprovacao}` }) : null);
}

export function montarLateral(lat) {
  limpar(lat);
  lat.append(el("h2", { textContent: "Integracoes" }), el("p", { className: "aviso", textContent: "Nada aqui abre rede nem guarda credencial. Conectores com rede ou OAuth ficam planejados ate voce aprovar escopo, onde o token vive e quais dados podem sair da maquina." }));
}

export async function montar(raiz) {
  limpar(raiz);
  raiz.append(el("div", { className: "titulo-vista" }, el("h1", { textContent: "Integracoes e servicos" })));
  try {
    const lista = await api("GET", "/integracoes");
    raiz.append(el("h2", { textContent: "Disponiveis agora (locais e gratuitas)" }), el("div", { className: "grade" }, ...lista.filter((c) => c.estado === "implementado").map(cartao)),
      el("h2", { textContent: "Planejadas (dependem da sua aprovacao)" }), el("div", { className: "grade" }, ...lista.filter((c) => c.estado !== "implementado").map(cartao)));
  } catch (e) { raiz.append(el("p", { className: "aviso", textContent: e.message })); }
}
