// Movimento e dicas (ADR-027): tooltips proprios para [title], [data-dica] e botoes so com icone (aria-label), com atraso,
// "aquecimento" (passar de um botao para outro mostra na hora), teclado (aparece no foco visivel, Esc fecha) e top layer
// (popover: fica acima de janelas modais). Tambem anima a entrada de telas e paineis e a troca de visualizacao, sem mudar o
// fluxo sincrono do codigo (so classes CSS). Com "reduzir movimento" nada anima.
const ATRASO_MS = 450, AQUECIDO_MS = 600, ATRASO_FOCO_MS = 250;
const reduzir = matchMedia("(prefers-reduced-motion: reduce)");
let dica = null, alvo = null, timer = null, ultimaVisivel = 0, descricaoAdicionada = false;

const somenteIcone = (e) => e.matches("button, a, [role='button'], [role='tab']") && !e.textContent.trim();
const textoDe = (e) => e.dataset.dica || e.getAttribute("title") || e.dataset.dicaTitulo || (somenteIcone(e) ? e.getAttribute("aria-label") || "" : "");

function alvoDe(no) {
  if (!(no instanceof Element) || no.closest(".dica, .completar-caixa, .dica-codigo, input, textarea, select, option")) return null;
  const e = no.closest("[data-dica], [title], [data-dica-titulo], button[aria-label], a[aria-label], [role='tab'][aria-label]");
  return e && textoDe(e).trim() ? e : null;
}

function criar() {
  dica = document.createElement("div");
  dica.className = "dica";
  dica.id = "dica-global";
  dica.setAttribute("role", "tooltip");
  if ("popover" in dica) dica.setAttribute("popover", "manual");
  dica.hidden = true;
  document.body.append(dica);
}

function posicionar(e) {
  const r = e.getBoundingClientRect(), d = dica.getBoundingClientRect(), m = 8;
  let lado = "cima", top = r.top - d.height - 8;
  if (top < m) { lado = "baixo"; top = r.bottom + 8; }
  const left = Math.max(m, Math.min(innerWidth - d.width - m, r.left + r.width / 2 - d.width / 2));
  dica.style.left = `${Math.round(left)}px`;
  dica.style.top = `${Math.round(Math.min(top, innerHeight - d.height - m))}px`;
  dica.dataset.lado = lado;
  dica.style.setProperty("--seta-x", `${Math.round(Math.max(10, Math.min(d.width - 10, r.left + r.width / 2 - left)))}px`);
}

function mostrar(e) {
  if (!e.isConnected) return;
  const texto = textoDe(e).trim();
  if (!texto) return;
  if (e.hasAttribute("title")) { e.dataset.dicaTitulo = e.getAttribute("title"); e.removeAttribute("title"); } // sem dica nativa dupla
  dica.textContent = texto.length > 300 ? `${texto.slice(0, 300)}…` : texto;
  dica.hidden = false;
  try { if (dica.showPopover && !dica.matches(":popover-open")) dica.showPopover(); } catch { /* sem popover: z-index */ }
  posicionar(e);
  dica.classList.remove("visivel"); void dica.offsetWidth; dica.classList.add("visivel");
  const nome = (e.getAttribute("aria-label") || e.textContent || "").trim();
  descricaoAdicionada = nome !== texto && !(e.getAttribute("aria-describedby") || "").includes("dica-global");
  if (descricaoAdicionada) e.setAttribute("aria-describedby", `${e.getAttribute("aria-describedby") || ""} dica-global`.trim());
  alvo = e;
}

function esconder() {
  clearTimeout(timer);
  if (!alvo) return;
  const e = alvo;
  alvo = null;
  ultimaVisivel = Date.now();
  if (e.dataset.dicaTitulo !== undefined) { e.setAttribute("title", e.dataset.dicaTitulo); delete e.dataset.dicaTitulo; }
  if (descricaoAdicionada) {
    const resto = (e.getAttribute("aria-describedby") || "").split(/\s+/).filter((x) => x && x !== "dica-global").join(" ");
    if (resto) e.setAttribute("aria-describedby", resto); else e.removeAttribute("aria-describedby");
  }
  dica.classList.remove("visivel");
  dica.hidden = true;
  try { if (dica.hidePopover && dica.matches(":popover-open")) dica.hidePopover(); } catch { /* idem */ }
}

function agendar(e, atraso) {
  clearTimeout(timer);
  timer = setTimeout(() => mostrar(e), Date.now() - ultimaVisivel < AQUECIDO_MS ? 60 : atraso);
}

export function iniciarDicas() {
  if (dica) return;
  criar();
  document.addEventListener("pointerover", (ev) => {
    if (ev.pointerType === "touch") return;
    const e = alvoDe(ev.target);
    if (e === alvo) return;
    if (alvo) esconder();
    if (e) agendar(e, ATRASO_MS); else clearTimeout(timer);
  }, { passive: true });
  document.addEventListener("pointerout", (ev) => {
    const para = ev.relatedTarget;
    const atual = alvo || null;
    if (atual && !(para instanceof Node && atual.contains(para))) esconder();
    else if (!atual) clearTimeout(timer);
  }, { passive: true });
  document.addEventListener("focusin", (ev) => {
    const e = alvoDe(ev.target);
    if (alvo && alvo !== e) esconder();
    if (e && e.matches(":focus-visible")) agendar(e, ATRASO_FOCO_MS);
  });
  document.addEventListener("focusout", () => esconder());
  document.addEventListener("pointerdown", () => esconder(), { passive: true, capture: true });
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && alvo) esconder(); }, { capture: true });
  addEventListener("scroll", () => esconder(), { passive: true, capture: true });
  addEventListener("blur", () => esconder());
}

// ---------------------------------------------------------------- transicoes de tela
function animarEntradas(container, classe) {
  if (!container) return;
  new MutationObserver((mudancas) => {
    if (reduzir.matches) return;
    // redesenho da MESMA tela (atualizacao em tempo real) nao anima: so a troca para outra tela/conteudo
    const saiu = new Set(mudancas.flatMap((m) => [...m.removedNodes]).filter((n) => n instanceof HTMLElement).map((n) => n.className.replace(classe, "").trim()));
    for (const m of mudancas) {
      for (const n of m.addedNodes) {
        if (!(n instanceof HTMLElement) || n.parentElement !== container || saiu.has(n.className.trim())) continue;
        n.classList.remove(classe); void n.offsetWidth; n.classList.add(classe);
        n.addEventListener("animationend", () => n.classList.remove(classe), { once: true });
      }
    }
  }).observe(container, { childList: true });
}

export function iniciarTransicoes() {
  animarEntradas(document.getElementById("vista"), "entra-vista");
  for (const id of ["lateral-corpo", "direita-corpo", "inferior-corpo"]) animarEntradas(document.getElementById(id), "entra-painel");
  const area = document.getElementById("area");
  if (area) {
    new MutationObserver(() => {
      if (reduzir.matches) return;
      area.classList.remove("modo-trocando"); void area.offsetWidth; area.classList.add("modo-trocando");
      setTimeout(() => area.classList.remove("modo-trocando"), 320);
    }).observe(area, { attributes: true, attributeFilter: ["data-modo"] });
  }
}
