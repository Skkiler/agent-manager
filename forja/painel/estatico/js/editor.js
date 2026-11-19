// Editor de codigo leve (sem build, sem bibliotecas externas): textarea nativa (desfazer, selecao, IME e leitor de tela do
// navegador) + camada de realce alinhada + calha com numeros de linha e marcas de problema. Busca/substituicao, previa de
// Markdown/HTML (iframe sandbox, sem scripts), corretor ortografico do navegador e Ctrl+S. O conteudo e DADO (so DOM/texto).
import { criarCompletador } from "./completar.js";
import { icone } from "./icones.js";
import { renderizar as renderizarMarkdown } from "./markdown.js";
import { realcar } from "./realce.js";
import { el } from "./ui.js";

const ALTURA_LINHA = 20;
let seq = 0;

function linhaColuna(texto, pos) {
  const antes = texto.slice(0, pos);
  const linha = (antes.match(/\n/g) || []).length + 1;
  return [linha, pos - antes.lastIndexOf("\n")];
}

function inicioDaLinha(texto, linha) {
  let pos = 0;
  for (let n = 1; n < linha; n += 1) { const i = texto.indexOf("\n", pos); if (i < 0) return texto.length; pos = i + 1; }
  return pos;
}

function inserir(area, texto) {
  area.focus();
  // execCommand mantem a pilha de desfazer da textarea (setRangeText nao). Sem suporte: cai no setRangeText.
  if (!document.execCommand?.("insertText", false, texto)) {
    area.setRangeText(texto, area.selectionStart, area.selectionEnd, "end");
    area.dispatchEvent(new Event("input"));
  }
}

/**
 * opcoes: { texto, linguagem, somenteLeitura, rotulo, aoSalvar(texto) -> Promise, aoMudar(sujo), aoCursor(l, c), aoAlterarTexto(texto) }
 */
export function criarEditor(op) {
  const id = `ed-${++seq}`;
  const lf = (s) => String(s ?? "").replace(/\r\n?/g, "\n"); // a textarea sempre usa \n; o CRLF volta ao salvar (bancada.js)
  let salvo = lf(op.texto);
  let linguagem = op.linguagem || "texto";
  let problemas = [];
  let marcas = [];
  let marcaAtual = -1;
  let tabMoveFoco = false;
  const previaPossivel = linguagem === "markdown" || linguagem === "html";
  let modoPrevia = "codigo"; // codigo | dividido | previa
  const usaTab = /^\t/m.test(salvo) && !/^ {2,}\S/m.test(salvo);

  const area = el("textarea", { className: "fonte", spellcheck: linguagem === "markdown" || linguagem === "texto", lang: "pt-BR", wrap: "off",
    readOnly: Boolean(op.somenteLeitura), "aria-label": op.rotulo || "Editor de código", "aria-describedby": `${id}-ajuda`, autocapitalize: "off",
    autocomplete: "off" });
  area.value = salvo;
  const codigo = el("code");
  const realce = el("pre", { className: "realce", "aria-hidden": "true" }, codigo);
  const numeros = el("pre", { className: "numeros", "aria-hidden": "true" });
  const marcasCalha = el("div", { className: "marcas-calha", "aria-hidden": "true" });
  const calha = el("div", { className: "calha", "aria-hidden": "true" }, numeros, marcasCalha);
  const camada = el("div", { className: "codigo" }, realce, area);
  const ajuda = el("span", { id: `${id}-ajuda`, className: "sr-only", textContent:
    "Tab indenta. Pressione Esc e depois Tab para sair do editor. Ctrl+S salva, Ctrl+F busca, Ctrl+H substitui, Ctrl+Espaço sugere, "
    + "F12 vai para a definição." });
  const previa = el("div", { className: "previa", hidden: true, tabIndex: 0, "aria-label": "Prévia" });

  // ---- barra de busca
  const busca = el("input", { type: "search", placeholder: "Buscar", "aria-label": "Buscar no arquivo", spellcheck: false });
  const troca = el("input", { type: "text", placeholder: "Substituir", "aria-label": "Substituir por", spellcheck: false, hidden: Boolean(op.somenteLeitura) });
  const contagem = el("span", { className: "mudo contagem", role: "status", "aria-live": "polite" });
  const barraBusca = el("div", { className: "editor-busca", hidden: true, role: "search" }, busca,
    el("button", { type: "button", className: "pequeno", "aria-label": "Ocorrência anterior", textContent: "↑", onclick: () => irMarca(-1) }),
    el("button", { type: "button", className: "pequeno", "aria-label": "Próxima ocorrência", textContent: "↓", onclick: () => irMarca(1) }),
    contagem, troca,
    op.somenteLeitura ? null : el("button", { type: "button", className: "pequeno", textContent: "Substituir", onclick: () => substituir(false) }),
    op.somenteLeitura ? null : el("button", { type: "button", className: "pequeno", textContent: "Tudo", onclick: () => substituir(true) }),
    el("button", { type: "button", className: "pequeno", "aria-label": "Fechar busca", textContent: "✕", onclick: () => fecharBusca() }));

  // ---- barra do editor
  const estadoSalvo = el("span", { className: "mudo estado-salvo", role: "status" });
  const botaoPrevia = previaPossivel ? el("button", { type: "button", className: "pequeno", "aria-pressed": "false", title: "Prévia (Ctrl+Shift+V)",
    onclick: () => alternarPrevia() }, icone("olho", 16), "Prévia") : null;
  const botaoOrto = el("button", { type: "button", className: "pequeno", "aria-pressed": String(area.spellcheck), title: "Correção ortográfica do navegador",
    onclick: () => { area.spellcheck = !area.spellcheck; botaoOrto.setAttribute("aria-pressed", String(area.spellcheck)); area.blur(); area.focus(); } },
  icone("ortografia", 16), "Ortografia");
  const botaoSalvar = op.somenteLeitura ? null : el("button", { type: "button", className: "pequeno", title: "Salvar (Ctrl+S)", onclick: () => salvar() }, icone("salvar", 16), "Salvar");
  const barra = el("div", { className: "editor-barra" }, el("span", { className: "tag", textContent: linguagem }),
    op.somenteLeitura ? el("span", { className: "tag aviso", textContent: "somente leitura" }) : null, estadoSalvo, el("span", { className: "espaco" }),
    el("button", { type: "button", className: "pequeno", title: "Buscar (Ctrl+F)", onclick: () => abrirBusca(false) }, icone("busca", 16), "Buscar"),
    botaoOrto, botaoPrevia, botaoSalvar);

  const corpo = el("div", { className: "editor-corpo" }, calha, camada);
  // ---- autocompletar (palavras do arquivo, palavras-chave e trechos) e ir para a definicao (F12 / Ctrl+clique)
  let larguraCaractere = 0;
  const medirCaractere = () => {
    if (larguraCaractere) return larguraCaractere;
    const c = document.createElement("canvas").getContext("2d");
    c.font = getComputedStyle(area).font;
    larguraCaractere = c.measureText("0000000000").width / 10 || 7.8;
    return larguraCaractere;
  };
  const comp = criarCompletador(area, {
    linguagem: () => linguagem,
    coordenadas: () => {
      const [l, c] = linhaColuna(area.value, area.selectionStart);
      return { x: calha.offsetWidth + 16 + (c - 1) * medirCaractere() - area.scrollLeft, y: 8 + l * ALTURA_LINHA - area.scrollTop + 2 };
    },
    inserir: (texto, apagar, cursorRel) => {
      const ini = area.selectionStart - apagar;
      area.setSelectionRange(ini, area.selectionStart);
      inserir(area, texto);
      area.setSelectionRange(ini + cursorRel, ini + cursorRel);
    },
  });
  corpo.append(comp.no);
  const palavraNoCursor = () => {
    const v = area.value, p = area.selectionStart;
    let i = p, f = p;
    while (i > 0 && /[\w$]/.test(v[i - 1])) i -= 1;
    while (f < v.length && /[\w$]/.test(v[f])) f += 1;
    return v.slice(i, f);
  };
  const irDefinicao = () => { const w = palavraNoCursor(); if (w && op.aoDefinicao) op.aoDefinicao(w); };
  const divisao = el("div", { className: "editor-divisao" }, corpo, previa);
  const no = el("div", { className: "editor", dataset: { linguagem } }, barra, barraBusca, divisao, ajuda);

  // ---- desenho
  let pendente = false;
  function desenhar() {
    pendente = false;
    const texto = area.value;
    realcar(codigo, texto, linguagem, marcas);
    const n = (texto.match(/\n/g) || []).length + 1;
    if (numeros.dataset.n !== String(n)) {
      numeros.dataset.n = String(n);
      numeros.textContent = Array.from({ length: n }, (_, i) => i + 1).join("\n");
      no.style.setProperty("--digitos", String(Math.max(3, String(n).length)));
    }
    desenharProblemas();
    if (modoPrevia !== "codigo") desenharPrevia();
    sincronizarRolagem();
  }
  const agendar = () => { if (!pendente) { pendente = true; requestAnimationFrame(desenhar); } };
  function sincronizarRolagem() {
    codigo.style.translate = `${-area.scrollLeft}px ${-area.scrollTop}px`;
    numeros.style.translate = `0 ${-area.scrollTop}px`;
    marcasCalha.style.translate = `0 ${-area.scrollTop}px`;
  }
  function desenharProblemas() {
    marcasCalha.replaceChildren(...problemas.map((p) => {
      const m = el("span", { className: `marca-problema ${p.gravidade === "erro" ? "grave" : "leve"}` });
      m.style.top = `${(p.linha - 1) * ALTURA_LINHA}px`;
      return m;
    }));
  }
  let tPrevia = null;
  function desenharPrevia() {
    clearTimeout(tPrevia);
    tPrevia = setTimeout(() => {
      if (linguagem === "markdown") previa.replaceChildren(renderizarMarkdown(area.value));
      else {
        // HTML do proprio arquivo, isolado: sandbox SEM allow-scripts (nada roda) e sem acesso a esta pagina
        const f = el("iframe", { title: "Prévia do HTML", sandbox: "", referrerPolicy: "no-referrer" });
        f.srcdoc = area.value;
        previa.replaceChildren(f);
      }
    }, 150);
  }
  function alternarPrevia(modo) {
    modoPrevia = modo || { codigo: "dividido", dividido: "previa", previa: "codigo" }[modoPrevia];
    no.dataset.previa = modoPrevia;
    previa.hidden = modoPrevia === "codigo";
    botaoPrevia?.setAttribute("aria-pressed", String(modoPrevia !== "codigo"));
    if (botaoPrevia) botaoPrevia.lastChild.textContent = { codigo: "Prévia", dividido: "Dividido", previa: "Só prévia" }[modoPrevia];
    if (modoPrevia !== "codigo") desenharPrevia();
  }

  // ---- estado salvo / sujo
  const sujo = () => area.value !== salvo;
  function atualizarSujo() {
    const s = sujo();
    estadoSalvo.textContent = op.somenteLeitura ? "" : s ? "● não salvo" : "salvo";
    no.classList.toggle("sujo", s);
    op.aoMudar?.(s);
  }
  async function salvar() {
    if (op.somenteLeitura || !op.aoSalvar) return;
    const texto = area.value;
    try { const ok = await op.aoSalvar(texto); if (ok !== false) { salvo = texto; atualizarSujo(); } } catch { /* quem salva avisa */ }
  }

  // ---- busca
  function calcularMarcas() {
    const q = busca.value;
    marcas = [];
    if (q) {
      const t = area.value.toLowerCase(), alvo = q.toLowerCase();
      for (let i = t.indexOf(alvo); i >= 0 && marcas.length < 5000; i = t.indexOf(alvo, i + Math.max(1, alvo.length))) marcas.push([i, i + alvo.length]);
    }
    marcaAtual = marcas.length ? Math.max(0, marcas.findIndex((m) => m[0] >= area.selectionStart)) : -1;
    contagem.textContent = q ? (marcas.length ? `${marcaAtual + 1} de ${marcas.length}` : "nenhum resultado") : "";
    agendar();
  }
  function irMarca(passo) {
    if (!marcas.length) return;
    marcaAtual = (marcaAtual + passo + marcas.length) % marcas.length;
    const [a, b] = marcas[marcaAtual];
    contagem.textContent = `${marcaAtual + 1} de ${marcas.length}`;
    area.setSelectionRange(a, b);
    rolarAte(linhaColuna(area.value, a)[0]);
  }
  function substituir(tudo) {
    if (!marcas.length || op.somenteLeitura) return;
    if (tudo) {
      area.focus(); area.select();
      const q = busca.value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      inserir(area, area.value.replace(new RegExp(q, "gi"), () => troca.value));
    } else {
      const [a, b] = marcas[Math.max(0, marcaAtual)];
      area.setSelectionRange(a, b); inserir(area, troca.value);
    }
    calcularMarcas(); busca.focus();
  }
  function abrirBusca(comTroca) {
    barraBusca.hidden = false;
    const sel = area.value.slice(area.selectionStart, area.selectionEnd);
    if (sel && !sel.includes("\n")) busca.value = sel;
    calcularMarcas();
    (comTroca && !op.somenteLeitura ? troca : busca).focus(); (comTroca ? troca : busca).select();
  }
  function fecharBusca() { barraBusca.hidden = true; marcas = []; agendar(); area.focus(); }
  busca.addEventListener("input", calcularMarcas);
  busca.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") { ev.preventDefault(); irMarca(ev.shiftKey ? -1 : 1); }
    if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); fecharBusca(); }
  });
  troca.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") { ev.preventDefault(); substituir(ev.ctrlKey); }
    if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); fecharBusca(); }
  });

  function rolarAte(linha) {
    const topo = (linha - 1) * ALTURA_LINHA;
    if (topo < area.scrollTop || topo > area.scrollTop + area.clientHeight - 2 * ALTURA_LINHA) area.scrollTop = Math.max(0, topo - area.clientHeight / 3);
    sincronizarRolagem();
  }

  // ---- teclado
  area.addEventListener("keydown", (ev) => {
    if (comp.tecla(ev)) return;
    const ctrl = ev.ctrlKey || ev.metaKey;
    if (ev.key === "F12") { ev.preventDefault(); irDefinicao(); return; }
    const k = ev.key.toLowerCase();
    if (ctrl && k === "s") { ev.preventDefault(); ev.stopPropagation(); salvar(); return; }
    if (ctrl && k === "f") { ev.preventDefault(); ev.stopPropagation(); abrirBusca(false); return; }
    if (ctrl && k === "h") { ev.preventDefault(); ev.stopPropagation(); abrirBusca(true); return; }
    if (ctrl && ev.shiftKey && k === "v" && previaPossivel) { ev.preventDefault(); alternarPrevia(); return; }
    if (ev.key === "F3") { ev.preventDefault(); irMarca(ev.shiftKey ? -1 : 1); return; }
    if (ev.key === "Escape") { tabMoveFoco = true; if (!barraBusca.hidden) fecharBusca(); return; }
    if (op.somenteLeitura) return;
    if (ev.key === "Tab" && !ctrl && !ev.altKey) {
      if (tabMoveFoco) { tabMoveFoco = false; return; } // deixa o navegador mover o foco (acessibilidade)
      ev.preventDefault();
      const recuo = usaTab ? "\t" : "    ";
      const v = area.value, ini = area.selectionStart, fim = area.selectionEnd;
      if (ini === fim && !ev.shiftKey) { inserir(area, recuo); return; }
      const li = v.lastIndexOf("\n", ini - 1) + 1, lf = v.indexOf("\n", fim - (fim > ini && v[fim - 1] === "\n" ? 1 : 0));
      const bloco = v.slice(li, lf < 0 ? v.length : lf);
      const novo = ev.shiftKey ? bloco.replace(usaTab ? /^\t/gm : /^ {1,4}/gm, "") : bloco.replace(/^/gm, recuo);
      area.setSelectionRange(li, lf < 0 ? v.length : lf); inserir(area, novo);
      area.setSelectionRange(li, li + novo.length);
      return;
    }
    tabMoveFoco = false;
    if (ev.key === "Enter" && !ctrl && !ev.shiftKey && !ev.altKey) {
      const v = area.value, ini = area.selectionStart;
      const linhaAtual = v.slice(v.lastIndexOf("\n", ini - 1) + 1, ini);
      let recuo = (linhaAtual.match(/^[ \t]*/) || [""])[0];
      if (/[:{[(]\s*$/.test(linhaAtual) && ["python", "javascript", "typescript", "json", "css"].includes(linguagem)) recuo += usaTab ? "\t" : "    ";
      ev.preventDefault(); inserir(area, `\n${recuo}`);
    }
  });
  const cursor = () => { const [l, c] = linhaColuna(area.value, area.selectionStart); op.aoCursor?.(l, c); };
  area.addEventListener("input", (ev) => { agendar(); atualizarSujo(); if (!barraBusca.hidden) calcularMarcas(); op.aoAlterarTexto?.(area.value); if (!op.somenteLeitura) comp.aoDigitar(ev); });
  area.addEventListener("blur", () => setTimeout(() => comp.fechar(), 120));
  area.addEventListener("click", (ev) => { comp.fechar(); if (ev.ctrlKey || ev.metaKey) irDefinicao(); });
  area.addEventListener("scroll", sincronizarRolagem, { passive: true });
  for (const t of ["keyup", "click", "focus"]) area.addEventListener(t, cursor);

  desenhar(); atualizarSujo();
  return {
    no,
    valor: () => area.value,
    sujo,
    focar: () => area.focus({ preventScroll: true }),
    salvar,
    abrirBusca,
    alternarPrevia,
    marcarSalvo: (texto) => { salvo = lf(texto ?? area.value); atualizarSujo(); },
    definirTexto: (texto) => { salvo = lf(texto); area.value = salvo; agendar(); atualizarSujo(); },
    irPara: (linha, coluna = 1) => {
      const pos = inicioDaLinha(area.value, linha) + Math.max(0, coluna - 1);
      area.focus({ preventScroll: true }); area.setSelectionRange(pos, pos); rolarAte(linha); cursor();
    },
    marcarProblemas: (lista) => { problemas = (lista || []).filter((p) => p.linha); desenharProblemas(); },
    linguagem: () => linguagem,
    palavraNoCursor,
  };
}
