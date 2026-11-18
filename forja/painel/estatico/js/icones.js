// Icones proprios (tracos simples em 24x24, cor = currentColor). Criados por DOM (createElementNS), sem innerHTML.
const NS = "http://www.w3.org/2000/svg";
const D = {
  explorador: ["M4 4h7l2 2h7v13a1 1 0 0 1-1 1H4z", "M4 9h16"],
  busca: ["M10.5 4a6.5 6.5 0 1 1 0 13a6.5 6.5 0 0 1 0-13z", "M15.5 15.5L20 20"],
  git: ["M7 4v11", "M7 4a2 2 0 1 0 0 .01", "M7 19a2 2 0 1 0 0 .01", "M17 7a2 2 0 1 0 0 .01", "M17 9c0 5-10 3-10 8"],
  docker: ["M3 12h16c1 0 2-1 2-2", "M3 12c0 4 3 7 8 7c5 0 8-3 9-7", "M6 9h3v3H6z", "M9 9h3v3H9z", "M12 9h3v3h-3z", "M9 6h3v3H9z"],
  master: ["M12 3l2.2 5.3L20 9l-4.4 3.8L17 19l-5-3l-5 3l1.4-6.2L4 9l5.8-.7z"],
  tarefas: ["M4 4h16v16H4z", "M9.3 4v16", "M14.6 4v16", "M5.5 7h2.5", "M10.8 7h2.5", "M10.8 10h2.5", "M16 7h2.5"],
  quadro: ["M3 6h18v12H3z", "M3 6l9 7l9-7"],
  memoria: ["M12 5a2 2 0 1 0 0 .01", "M5 17a2 2 0 1 0 0 .01", "M19 17a2 2 0 1 0 0 .01", "M12 7v4", "M12 11l-6 5", "M12 11l6 5", "M7 18h10"],
  ferramentas: ["M14 6l4 4", "M4 20l9-9", "M13 4l7 7l-3 3l-7-7z"],
  integracoes: ["M4 8h12", "M13 5l3 3l-3 3", "M20 16H8", "M11 13l-3 3l3 3"],
  custos: ["M12 3a9 9 0 1 1 0 18a9 9 0 0 1 0-18z", "M15 9c-.5-1.2-1.7-2-3-2c-1.7 0-3 1-3 2.4c0 3.2 6 1.8 6 5c0 1.4-1.3 2.6-3 2.6c-1.4 0-2.6-.8-3-2", "M12 5v2", "M12 17v2"],
  conta: ["M12 4a4 4 0 1 1 0 8a4 4 0 0 1 0-8z", "M4 20c1-4 4.5-6 8-6s7 2 8 6"],
  config: ["M12 9a3 3 0 1 1 0 6a3 3 0 0 1 0-6z", "M12 2v3", "M12 19v3", "M2 12h3", "M19 12h3", "M4.9 4.9l2.1 2.1", "M17 17l2.1 2.1", "M4.9 19.1L7 17", "M17 7l2.1-2.1"],
  inicio: ["M4 11l8-7l8 7", "M6 10v10h12V10", "M10 20v-5h4v5"],
  painel_lateral: ["M3 5h18v14H3z", "M9 5v14"],
  painel_inferior: ["M3 5h18v14H3z", "M3 14h18"],
  painel_direito: ["M3 5h18v14H3z", "M15 5v14"],
  arquivo: ["M6 3h8l4 4v14H6z", "M14 3v4h4"],
  pasta: ["M3 6h7l2 2h9v11H3z"],
  atualizar: ["M20 11a8 8 0 1 0-2.3 5.7", "M20 5v6h-6"],
  mais: ["M12 5v14", "M5 12h14"],
  terminal: ["M3 5h18v14H3z", "M7 9l3 3l-3 3", "M12 15h5"],
  salvar: ["M5 4h11l3 3v13H5z", "M8 4v5h7V4", "M8 20v-6h8v6"],
  olho: ["M2 12s4-7 10-7s10 7 10 7s-4 7-10 7S2 12 2 12z", "M12 9a3 3 0 1 1 0 6a3 3 0 0 1 0-6z"],
  ortografia: ["M4 17l4-10l4 10", "M5.5 13.5h5", "M14 15l2.5 2.5L21 12"],
};

export function icone(nome, tamanho = 20) {
  const s = document.createElementNS(NS, "svg");
  for (const [k, v] of Object.entries({ viewBox: "0 0 24 24", width: tamanho, height: tamanho, fill: "none", stroke: "currentColor",
    "stroke-width": "1.6", "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true", focusable: "false" })) s.setAttribute(k, String(v));
  s.classList.add("ico");
  for (const d of D[nome] || D.arquivo) { const p = document.createElementNS(NS, "path"); p.setAttribute("d", d); s.append(p); }
  return s;
}
