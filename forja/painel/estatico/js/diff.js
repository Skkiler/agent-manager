// Revisao de diferencas lado a lado (estilo VS Code): algoritmo de Myers por linha, destaque do trecho alterado dentro da linha,
// contexto recolhido, navegacao entre alteracoes (Alt+↑/↓) e contagem +/-. So DOM/texto (nada de innerHTML).
import { el } from "./ui.js";

const LIMITE_EDICOES = 4000; // acima disso (arquivos muito diferentes) cai para comparacao direta linha a linha

/** Myers O(ND): sequencia de operacoes ["=", i, j] | ["-", i] | ["+", j] entre as listas a e b. */
export function diferencas(a, b) {
  let ini = 0;
  while (ini < a.length && ini < b.length && a[ini] === b[ini]) ini += 1;
  let fa = a.length, fb = b.length;
  while (fa > ini && fb > ini && a[fa - 1] === b[fb - 1]) { fa -= 1; fb -= 1; }
  const A = a.slice(ini, fa), B = b.slice(ini, fb);
  const meio = myers(A, B) || direto(A, B);
  const ops = [];
  for (let i = 0; i < ini; i += 1) ops.push(["=", i, i]);
  for (const op of meio) ops.push(op[0] === "=" ? ["=", op[1] + ini, op[2] + ini] : op[0] === "-" ? ["-", op[1] + ini] : ["+", op[1] + ini]);
  for (let k = 0; k < a.length - fa; k += 1) ops.push(["=", fa + k, fb + k]);
  return ops;
}

function direto(A, B) {
  const ops = [];
  for (let i = 0; i < A.length; i += 1) ops.push(["-", i]);
  for (let j = 0; j < B.length; j += 1) ops.push(["+", j]);
  return ops;
}

function myers(A, B) {
  const n = A.length, m = B.length, max = n + m;
  if (!max) return [];
  const v = new Map([[1, 0]]);
  const trilha = [];
  for (let d = 0; d <= Math.min(max, LIMITE_EDICOES); d += 1) {
    trilha.push(new Map(v));
    for (let k = -d; k <= d; k += 2) {
      let x = k === -d || (k !== d && (v.get(k - 1) ?? -1) < (v.get(k + 1) ?? -1)) ? v.get(k + 1) ?? 0 : (v.get(k - 1) ?? 0) + 1;
      let y = x - k;
      while (x < n && y < m && A[x] === B[y]) { x += 1; y += 1; }
      v.set(k, x);
      if (x >= n && y >= m) return voltar(trilha, n, m);
    }
  }
  return null;
}

function voltar(trilha, n, m) {
  const ops = [];
  let x = n, y = m;
  for (let d = trilha.length - 1; d >= 0; d -= 1) {
    const v = trilha[d];
    const k = x - y;
    const kAnt = k === -d || (k !== d && (v.get(k - 1) ?? -1) < (v.get(k + 1) ?? -1)) ? k + 1 : k - 1;
    const xAnt = v.get(kAnt) ?? 0, yAnt = xAnt - kAnt;
    while (x > xAnt && y > yAnt) { x -= 1; y -= 1; ops.push(["=", x, y]); }
    if (d > 0) { if (x === xAnt) { y -= 1; ops.push(["+", y]); } else { x -= 1; ops.push(["-", x]); } }
  }
  return ops.reverse();
}

/** Linhas pareadas para exibir lado a lado: {tipo: igual|mudou|rem|add, esq, dir, ne, nd}. */
export function parear(a, b) {
  const ops = diferencas(a, b);
  const linhas = [];
  let rem = [], add = [];
  const descarregar = () => {
    const n = Math.max(rem.length, add.length);
    for (let i = 0; i < n; i += 1) {
      const r = rem[i], s = add[i];
      linhas.push({ tipo: r !== undefined && s !== undefined ? "mudou" : r !== undefined ? "rem" : "add",
        esq: r !== undefined ? a[r] : null, dir: s !== undefined ? b[s] : null, ne: r !== undefined ? r + 1 : null, nd: s !== undefined ? s + 1 : null });
    }
    rem = []; add = [];
  };
  for (const op of ops) {
    if (op[0] === "-") rem.push(op[1]);
    else if (op[0] === "+") add.push(op[1]);
    else { descarregar(); linhas.push({ tipo: "igual", esq: a[op[1]], dir: b[op[2]], ne: op[1] + 1, nd: op[2] + 1 }); }
  }
  descarregar();
  return linhas;
}

function trecho(texto, outro, lado) {
  // destaca so o meio diferente (prefixo e sufixo comuns ficam normais)
  if (texto === null) return el("span", { className: "vazio-diff" });
  if (outro === null) return document.createTextNode(texto || " ");
  let i = 0;
  while (i < texto.length && i < outro.length && texto[i] === outro[i]) i += 1;
  let j = 0;
  while (j < texto.length - i && j < outro.length - i && texto[texto.length - 1 - j] === outro[outro.length - 1 - j]) j += 1;
  const f = document.createDocumentFragment();
  f.append(texto.slice(0, i));
  if (texto.length - j > i) f.append(el("mark", { className: `marca-${lado}`, textContent: texto.slice(i, texto.length - j) }));
  f.append(texto.slice(texto.length - j) || (texto ? "" : " "));
  return f;
}

/** Componente: {no, focar}. `rotulos` = [esquerda, direita]. */
export function criarDiff(antes, depois, { rotulos = ["Antes", "Depois"], titulo = "" } = {}) {
  const a = (antes ?? "").replace(/\r\n?/g, "\n").split("\n"), b = (depois ?? "").replace(/\r\n?/g, "\n").split("\n");
  const linhas = parear(a, b);
  const add = linhas.filter((l) => l.tipo === "add" || l.tipo === "mudou").length;
  const rem = linhas.filter((l) => l.tipo === "rem" || l.tipo === "mudou").length;
  let recolher = true;
  const corpo = el("tbody");
  const blocos = [];
  const desenhar = () => {
    corpo.replaceChildren();
    blocos.length = 0;
    const mudou = linhas.map((l) => l.tipo !== "igual");
    const perto = linhas.map((_, i) => { for (let k = Math.max(0, i - 3); k <= Math.min(linhas.length - 1, i + 3); k += 1) if (mudou[k]) return true; return false; });
    let pulado = 0;
    const fecharPulo = () => {
      if (!pulado) return;
      const n = pulado;
      corpo.append(el("tr", { className: "pulo" }, el("td", { colSpan: 4 }, el("button", { type: "button", className: "link", textContent: `⋯ ${n} linha(s) iguais (mostrar tudo)`,
        onclick: () => { recolher = false; desenhar(); } }))));
      pulado = 0;
    };
    linhas.forEach((l, i) => {
      if (recolher && !perto[i]) { pulado += 1; return; }
      fecharPulo();
      const tr = el("tr", { className: `d-${l.tipo}` },
        el("td", { className: "n", textContent: l.ne ?? "" }), el("td", { className: "esq" }, trecho(l.esq, l.tipo === "mudou" ? l.dir : null, "rem")),
        el("td", { className: "n", textContent: l.nd ?? "" }), el("td", { className: "dir" }, trecho(l.dir, l.tipo === "mudou" ? l.esq : null, "add")));
      if (mudou[i] && (i === 0 || !mudou[i - 1])) blocos.push(tr);
      corpo.append(tr);
    });
    fecharPulo();
    contagem.textContent = blocos.length ? `${blocos.length} alteração(ões) · +${add} −${rem}` : "Sem diferenças";
  };
  let atual = -1;
  const ir = (passo) => {
    if (!blocos.length) return;
    atual = (atual + passo + blocos.length) % blocos.length;
    blocos.forEach((b, k) => b.classList.toggle("atual", k === atual));
    blocos[atual].scrollIntoView({ block: "center" });
    status.textContent = `Alteração ${atual + 1} de ${blocos.length}`;
  };
  const contagem = el("span", { className: "mudo" });
  const status = el("span", { className: "sr-only", role: "status", "aria-live": "polite" });
  const tabela = el("table", { className: "tabela-diff" }, el("caption", { className: "sr-only", textContent: `Diferenças: ${titulo}` }),
    el("colgroup", {}, el("col", { className: "cn" }), el("col"), el("col", { className: "cn" }), el("col")),
    el("thead", {}, el("tr", {}, el("th", { scope: "col", colSpan: 2, textContent: rotulos[0] }), el("th", { scope: "col", colSpan: 2, textContent: rotulos[1] }))), corpo);
  const rolagem = el("div", { className: "diff-rolagem", tabIndex: 0, "aria-label": "Diferenças lado a lado (Alt+↑/↓ navega entre alterações)" }, tabela);
  rolagem.addEventListener("keydown", (ev) => { if (ev.altKey && (ev.key === "ArrowDown" || ev.key === "ArrowUp")) { ev.preventDefault(); ir(ev.key === "ArrowDown" ? 1 : -1); } });
  const no = el("div", { className: "diff" },
    el("div", { className: "editor-barra" }, el("strong", { className: "trunc", textContent: titulo }), contagem, el("span", { className: "espaco" }),
      el("button", { type: "button", className: "pequeno", title: "Alteração anterior (Alt+↑)", textContent: "↑ Anterior", onclick: () => ir(-1) }),
      el("button", { type: "button", className: "pequeno", title: "Próxima alteração (Alt+↓)", textContent: "↓ Próxima", onclick: () => ir(1) }),
      el("button", { type: "button", className: "pequeno", "aria-pressed": "true", textContent: "Só alterações", onclick: (ev) => { recolher = !recolher; ev.currentTarget.setAttribute("aria-pressed", String(recolher)); desenhar(); } }),
      status), rolagem);
  desenhar();
  return { no, focar: () => rolagem.focus({ preventScroll: true }), proxima: () => ir(1) };
}
