// Pastas do segundo cerebro (ADR-029): arvore de pastas (namespaces) com contagem, criar, renomear (migra tudo o que esta
// dentro), remover pasta vazia e mover notas. Agentes so PROPOEM (fila de Revisao); aqui e o usuario quem decide.
import { api, consulta } from "../api.js";
import { emitir } from "../estado.js";
import { el, limpar, tag, toast } from "../ui.js";

const NS = "^(publico|pessoal|terceiros)(/[a-z0-9][a-z0-9._-]{0,40}){0,6}$";
let atual = "pessoal";

export async function listarPastas() {
  try { return (await api("GET", "/memorias/pastas")).pastas; } catch { return []; }
}

/** Lista de sugestoes de pastas para um <input list>. */
export function sugestoesPastas(pastas, id) {
  return el("datalist", { id }, ...pastas.filter((p) => !p.namespace.startsWith("publico/forja-base")).map((p) => el("option", { value: p.namespace })));
}

export const pastas = {
  montar(raiz) {
    limpar(raiz);
    const arvore = el("ul", { className: "arvore-pastas", role: "tree", "aria-label": "Pastas do segundo cérebro" });
    const detalhe = el("section", { className: "card pasta-detalhe", "aria-live": "polite" });
    const nova = el("input", { type: "text", maxLength: 200, pattern: NS, placeholder: "pessoal/empresa/minha-empresa/projetos", "aria-label": "Caminho da nova pasta" });
    const descricao = el("input", { type: "text", maxLength: 300, placeholder: "Opcional: para que serve", "aria-label": "Descrição da nova pasta" });
    let todas = [];

    async function carregar() {
      todas = await listarPastas();
      limpar(arvore);
      if (!todas.length) arvore.append(el("li", { className: "mudo", textContent: "Nenhuma pasta ainda." }));
      for (const p of todas) {
        if (p.namespace.startsWith("publico/forja-base/")) continue;
        const item = el("li", { role: "treeitem", "aria-level": String(p.nivel + 1), "aria-selected": String(p.namespace === atual),
          className: p.namespace === atual ? "ativo" : "" },
        el("button", { type: "button", className: "pasta-botao", title: p.descricao || p.namespace, onclick: () => { atual = p.namespace; carregar(); } },
          el("span", { textContent: p.nome }), el("span", { className: "mudo", textContent: ` ${p.total}` + (p.arquivos ? ` · ${p.arquivos} arq.` : "") })));
        item.style.setProperty("--nivel", String(p.nivel)); // CSSOM: permitido pela CSP (sem atributo style inline)
        arvore.append(item);
      }
      await abrir(atual);
    }

    async function abrir(ns) {
      limpar(detalhe);
      const info = todas.find((p) => p.namespace === ns) || { namespace: ns, total: 0, notas: 0, somente_leitura: false };
      const destino = el("input", { type: "text", maxLength: 200, pattern: NS, list: "pastas-destino", placeholder: "pasta de destino", "aria-label": "Mover para a pasta" });
      const novoNome = el("input", { type: "text", maxLength: 200, pattern: NS, value: ns, "aria-label": "Novo caminho da pasta" });
      const lista = el("ul", { className: "lista-notas-pasta" });
      detalhe.append(el("h2", { textContent: ns }),
        el("p", { className: "mudo", textContent: `${info.notas} nota(s) nesta pasta · ${info.total} com as subpastas${info.arquivos ? ` · ${info.arquivos} arquivo(s) de código indexados` : ""}` }),
        ...(info.descricao ? [el("p", { textContent: info.descricao })] : [])); // append(null) escreveria "null"
      if (!info.somente_leitura) {
        detalhe.append(el("details", {}, el("summary", { textContent: "Renomear ou remover a pasta" }),
          el("p", { className: "mudo", textContent: "Renomear migra tudo o que está dentro (subpastas, notas e índice de código). As ligações continuam." }),
          el("div", { className: "linha" }, novoNome, el("button", { type: "button", textContent: "Renomear", onclick: async () => {
            const alvo = novoNome.value.trim();
            if (!alvo || alvo === ns || !novoNome.checkValidity()) return novoNome.focus();
            if (!confirm(`Mover a pasta ${ns} e tudo o que está dentro para ${alvo}?`)) return;
            try { const r = await api("POST", "/memorias/pastas/renomear", { origem: ns, destino: alvo }); toast(`${r.notas} nota(s) e ${r.arquivos} arquivo(s) migrados`, "ok"); atual = alvo; carregar(); } catch (e) { toast(e.message, "erro"); }
          } }), el("button", { type: "button", textContent: "Remover (só vazia)", onclick: async () => {
            try { await api("DELETE", `/memorias/pastas?${consulta({ namespace: ns })}`); toast("Pasta removida", "ok"); atual = ns.split("/").slice(0, -1).join("/") || "pessoal"; carregar(); } catch (e) { toast(e.message, "erro"); }
          } }))));
      }
      let notas = [];
      try { notas = (await api("GET", `/memorias/pastas/notas?${consulta({ namespace: ns })}`)).notas; } catch (e) { detalhe.append(el("p", { className: "aviso", role: "alert", textContent: e.message })); }
      if (!notas.length) { detalhe.append(el("p", { className: "mudo", textContent: "Sem notas diretamente nesta pasta (veja as subpastas)." })); return; }
      const marcadas = new Set();
      for (const n of notas) {
        const caixa = el("input", { type: "checkbox", "aria-label": `Selecionar ${n.titulo}`, onchange: (ev) => { if (ev.target.checked) marcadas.add(n.id); else marcadas.delete(n.id); } });
        lista.append(el("li", {}, el("label", {}, caixa, ` ${n.titulo} `), tag(n.estado, n.estado === "validado" ? "ok" : ""),
          el("button", { type: "button", className: "pequeno", textContent: "Abrir", onclick: () => emitir("abrir-nota", n.id) })));
      }
      detalhe.append(el("h3", { textContent: "Notas" }), lista, sugestoesPastas(todas, "pastas-destino"),
        el("div", { className: "linha" }, destino, el("button", { type: "button", className: "primario", textContent: "Mover selecionadas", onclick: async () => {
          if (!marcadas.size) return toast("Selecione ao menos uma nota", "aviso");
          if (!destino.value.trim() || !destino.checkValidity()) return destino.focus();
          try { const r = await api("POST", "/memorias/pastas/mover", { ids: [...marcadas], destino: destino.value.trim() }); toast(`${r.movidas} nota(s) movidas`, "ok"); carregar(); } catch (e) { toast(e.message, "erro"); }
        } })));
    }

    const criar = async (ev) => {
      ev.preventDefault();
      if (!nova.checkValidity() || !nova.value.trim()) return nova.focus();
      try { const r = await api("POST", "/memorias/pastas", { namespace: nova.value.trim(), descricao: descricao.value.trim() }); toast("Pasta criada", "ok"); atual = r.namespace; nova.value = ""; descricao.value = ""; carregar(); } catch (e) { toast(e.message, "erro"); }
    };
    raiz.append(el("div", { className: "conhecimento-aba" },
      el("h1", { textContent: "Pastas" }),
      el("p", { className: "subtitulo", textContent: "Organize as notas em pastas, como num cofre: pessoal/empresa/<id>/projetos, pessoal/interno/<id>/projetos, pessoal/geral. Agentes só propõem mudanças, que aparecem na Revisão." }),
      el("form", { className: "linha", onsubmit: criar }, nova, descricao, el("button", { type: "submit", textContent: "Nova pasta" })),
      el("div", { className: "grade-pastas" }, el("nav", { className: "card", "aria-label": "Árvore de pastas" }, arvore), detalhe)));
    carregar();
  },
};
