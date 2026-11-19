// Paleta (estilo VS Code): Ctrl+P abre arquivos dos projetos e abas abertas, ">" lista comandos, ":" vai para uma linha.
// Padrao ARIA de combobox + listbox (setas, Enter, Esc). Resultados sao DADOS (textContent).
import { api } from "./api.js";
import { abaAtiva, abas, abrirArquivo, ativar, simbolosDaAba } from "./bancada.js";
import { el, limpar } from "./ui.js";

let comandos = [];
let itens = [];
let marcado = 0;
let geracao = 0;
const $p = () => document.getElementById("paleta");

export function registrarComandos(lista) { comandos = lista; }

function opcao(item, i) {
  return el("li", { id: `paleta-op-${i}`, role: "option", className: "paleta-op", "aria-selected": String(i === marcado),
    onclick: () => executar(i), onpointermove: () => { if (marcado !== i) { marcado = i; marcar(); } } },
  el("span", { className: "trunc", textContent: item.rotulo }), item.detalhe ? el("span", { className: "mudo trunc", textContent: item.detalhe }) : null,
  item.atalho ? el("kbd", { textContent: item.atalho }) : null);
}

function marcar() {
  const lista = document.getElementById("paleta-lista");
  [...lista.children].forEach((li, i) => li.setAttribute("aria-selected", String(i === marcado)));
  const ativo = lista.children[marcado];
  document.getElementById("paleta-busca").setAttribute("aria-activedescendant", ativo ? ativo.id : "");
  ativo?.scrollIntoView({ block: "nearest" });
}

function desenhar() {
  const lista = document.getElementById("paleta-lista");
  limpar(lista);
  marcado = Math.min(marcado, Math.max(0, itens.length - 1));
  lista.append(...itens.map(opcao));
  if (!itens.length) lista.append(el("li", { className: "mudo paleta-vazia", role: "option", "aria-disabled": "true", textContent: "Nada encontrado." }));
  marcar();
}

const pontuar = (texto, q) => {
  const t = texto.toLowerCase(); q = q.toLowerCase();
  if (!q) return 1;
  const i = t.indexOf(q);
  if (i >= 0) return 100 - i;
  let j = 0; for (const c of t) if (c === q[j]) j += 1; // subsequencia ("abrtrm" acha "abrir terminal")
  return j === q.length ? 10 : 0;
};

async function atualizar() {
  const minha = ++geracao;
  const q = document.getElementById("paleta-busca").value;
  const dica = document.getElementById("paleta-dica");
  if (q.startsWith(">")) {
    const termo = q.slice(1).trim();
    itens = comandos.map((c) => ({ ...c, p: pontuar(c.rotulo, termo) })).filter((c) => c.p > 0).sort((a, b) => b.p - a.p)
      .map((c) => ({ rotulo: c.rotulo, atalho: c.atalho, fazer: c.executar }));
    dica.textContent = "Comandos da Forja. Apague o > para buscar arquivos.";
    return desenhar();
  }
  if (q.startsWith("@")) {
    const a = abaAtiva();
    dica.textContent = a?.editor ? "Símbolos do arquivo aberto (funções, classes, regras CSS…)." : "Abra um arquivo de código para ver os símbolos.";
    const termo = q.slice(1).trim();
    const lista = await simbolosDaAba();
    if (minha !== geracao) return;
    itens = lista.filter((s) => pontuar(s.nome, termo) > 0).sort((x, y) => pontuar(y.nome, termo) - pontuar(x.nome, termo) || x.linha - y.linha).slice(0, 80)
      .map((s) => ({ rotulo: s.nome, detalhe: `${s.tipo} · linha ${s.linha}`, fazer: () => a?.editor?.irPara(s.linha) }));
    return desenhar();
  }
  if (q.startsWith(":")) {
    const linha = Number.parseInt(q.slice(1), 10);
    const a = abaAtiva();
    itens = a?.editor && linha > 0 ? [{ rotulo: `Ir para a linha ${linha}`, detalhe: a.titulo, fazer: () => a.editor.irPara(linha) }] : [];
    dica.textContent = a?.editor ? "Digite o número da linha e Enter." : "Abra um arquivo para ir a uma linha.";
    return desenhar();
  }
  dica.textContent = "Arquivos dos projetos. > comandos · @ símbolos · : ir para linha";
  const termo = q.trim();
  const abertas = abas().filter((a) => pontuar(a.titulo, termo) > 0).map((a) => ({ rotulo: a.titulo, detalhe: a.rel ? `aberto · ${a.rel}` : "aberto", fazer: () => ativar(a.chave) }));
  itens = abertas; desenhar(); // abas abertas filtradas na hora: Enter logo depois de digitar ja usa a lista certa
  if (termo.length < 2) return;
  await new Promise((r) => { setTimeout(r, 160); }); // so a busca no servidor espera a digitacao parar
  if (minha !== geracao) return;
  try {
    const projetos = (await api("GET", "/projetos")).filter((p) => (p.pastas || []).length);
    const achados = await Promise.all(projetos.map((p) => api("GET", `/projetos/${p.id}/buscar-arquivos?q=${encodeURIComponent(termo)}`)
      .then((r) => r.map((x) => ({ rotulo: x.nome, detalhe: `${p.nome} · ${x.rel}${x.papel === "consulta" ? " (consulta)" : ""}`,
        fazer: () => abrirArquivo({ projeto: p.id, raiz: x.raiz, rel: x.rel, nome: x.nome }) }))).catch(() => [])));
    if (minha !== geracao) return;
    const vistos = new Set(abertas.map((a) => a.detalhe));
    itens = [...abertas, ...achados.flat().filter((x) => !vistos.has(x.detalhe))].slice(0, 60);
    desenhar();
  } catch { /* sem projetos: so as abas */ }
}

function executar(i) {
  const item = itens[i];
  if (!item) return;
  fecharPaleta();
  requestAnimationFrame(() => item.fazer());
}

export function abrirPaleta(prefixo = "") {
  const d = $p();
  const busca = document.getElementById("paleta-busca");
  busca.value = prefixo; marcado = 0;
  if (!d.open) d.showModal();
  busca.focus();
  atualizar();
}
export function fecharPaleta() { const d = $p(); if (d.open) d.close(); }

export function iniciarPaleta() {
  const d = $p();
  const busca = document.getElementById("paleta-busca");
  busca.addEventListener("input", () => { marcado = 0; atualizar(); });
  busca.addEventListener("keydown", (ev) => {
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") { ev.preventDefault(); if (itens.length) { marcado = (marcado + (ev.key === "ArrowDown" ? 1 : -1) + itens.length) % itens.length; marcar(); } }
    else if (ev.key === "Enter") { ev.preventDefault(); executar(marcado); }
  });
  d.addEventListener("click", (ev) => { if (ev.target === d) fecharPaleta(); }); // clique fora da caixa fecha
}
