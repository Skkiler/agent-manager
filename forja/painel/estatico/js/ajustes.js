// Ajustes rapidos: tema, paleta, nivel de autonomia/acesso e detalhe, mais criar projeto, fora da tela de Configuracoes.
// Sao as MESMAS preferencias da janela de Configuracoes (definirPreferencia grava, aplicarPreferencias emite "preferencias"), entao
// as duas telas, o botao de tema do cabecalho e o chip de autonomia mostram sempre o mesmo valor. A janela e NAO BLOQUEANTE.
import { emitir, ouvir } from "./estado.js";
import { icone } from "./icones.js";
import { $, el, janela, toast } from "./ui.js";
import { CORES_AMOSTRA, definirPreferencia, itemPreferencia, obterPreferencias } from "./views/config.js";
import { dialogoProjeto } from "./views/projetos.js";

const ID_JANELA = "janela-ajustes";
const TEMAS = ["auto", "claro", "escuro"];
const RISCO = { restrito: "ok", liberado: "aviso", total: "erro" };
let prefsAtuais = null;
let aberta = null; // { raiz, redesenhar } da janela aberta (so uma)

const rotuloDe = (item, valor) => (item?.opcoes.find(([v]) => v === valor) || [valor, valor])[1];
const sistemaClaro = matchMedia("(prefers-color-scheme: light)");
const efetivoClaro = (tema) => tema === "claro" || (tema !== "escuro" && sistemaClaro.matches);

/** Novo projeto: o mesmo formulario do Explorador e das Tarefas; avisa as demais telas para recarregar a lista. */
export function novoProjeto() { dialogoProjeto(null, (p) => { emitir("projetos-mudaram"); emitir("projeto-criado", p); toast("Projeto criado", "ok"); }); }

async function gravar(id, valor, anterior) {
  try { await definirPreferencia(id, valor); }
  catch (e) { toast(e.status === 409 ? "As preferências mudaram em outra aba. Tente de novo." : e.message, "erro"); aberta?.redesenhar(); return false; }
  return anterior !== valor;
}

/** Autonomia: aumentar pede confirmacao (acao de risco alto); diminuir aplica direto. */
export async function trocarAutonomia(novo) {
  const prefs = prefsAtuais || await obterPreferencias();
  const item = itemPreferencia(prefs, "nivel_autonomia");
  if (!item || item.valor === novo) return;
  const ordem = item.opcoes.map(([v]) => v);
  if (ordem.indexOf(novo) > ordem.indexOf(item.valor)) {
    const exemplo = item.exemplos.find((e) => e.valor === novo);
    if (!confirm(`Aumentar a autonomia dos agentes para "${rotuloDe(item, novo)}"?\n\n${exemplo?.descricao || ""}\n\nRisco: ${item.risco}. Excluir, publicar, rede e instalar continuam perguntando.`)) { aberta?.redesenhar(); return; }
  }
  if (await gravar("nivel_autonomia", novo, item.valor)) toast(`Autonomia: ${rotuloDe(item, novo)}`, "ok");
}

/** Botao de tema do cabecalho: Automatico -> Claro -> Escuro -> Automatico. */
export async function alternarTema() {
  const item = itemPreferencia(prefsAtuais || await obterPreferencias(), "tema");
  if (!item) return;
  const novo = TEMAS[(TEMAS.indexOf(item.valor) + 1) % TEMAS.length];
  if (await gravar("tema", novo, item.valor)) toast(`Tema: ${rotuloDe(item, novo)}`, "ok");
}

/** Grupo de opcoes exclusivas (radio acessivel: uma parada de Tab, setas movem e escolhem). */
function grupo(rotulo, opcoes, atual, aoEscolher, { amostras = false, descricoes = {} } = {}) {
  const botoes = opcoes.map(([valor, texto]) => {
    const [fundo, cartao, acento, cor] = CORES_AMOSTRA[valor] || [];
    const faixa = amostras ? el("span", { className: "faixa-cores", "aria-hidden": "true" }, ...[fundo, cartao, acento, cor].map((c) => { const i = el("i"); i.style.background = c; return i; })) : null;
    const b = el("button", { type: "button", role: "radio", className: `rapida${amostras ? " amostra compacta" : ""}`, dataset: { valor }, "aria-checked": String(valor === atual),
      tabIndex: valor === atual ? 0 : -1, title: descricoes[valor] || texto, onclick: () => aoEscolher(valor),
      onkeydown: (ev) => {
        const passo = ev.key === "ArrowRight" || ev.key === "ArrowDown" ? 1 : ev.key === "ArrowLeft" || ev.key === "ArrowUp" ? -1 : 0;
        if (!passo) return;
        ev.preventDefault(); const i = botoes.indexOf(b); const alvo = botoes[(i + passo + botoes.length) % botoes.length]; alvo.focus(); alvo.click();
      } }, faixa, el("span", { className: "trunc", textContent: texto }));
    return b;
  });
  return el("div", { className: "grupo-rapido", role: "radiogroup", "aria-label": rotulo }, ...botoes);
}

function secao(titulo, ...filhos) { return el("section", { className: "ajuste", "aria-label": titulo }, el("h3", { textContent: titulo }), ...filhos); }

function desenhar(raiz, prefs) {
  const tema = itemPreferencia(prefs, "tema"), escura = itemPreferencia(prefs, "paleta_escura"), clara = itemPreferencia(prefs, "paleta_clara");
  const autonomia = itemPreferencia(prefs, "nivel_autonomia"), detalhe = itemPreferencia(prefs, "nivel_detalhe");
  const foco = document.activeElement instanceof HTMLElement && raiz.contains(document.activeElement) ? document.activeElement.closest("[role=radiogroup]")?.getAttribute("aria-label") : null;
  const filhos = [];
  if (!tema) filhos.push(el("p", { className: "aviso", role: "alert", textContent: "Não foi possível carregar as preferências." }));
  else {
    const ehClaro = efetivoClaro(tema.valor), pal = ehClaro ? clara : escura;
    filhos.push(secao("Aparência",
      grupo("Tema", tema.opcoes, tema.valor, (v) => gravar("tema", v, tema.valor)),
      el("p", { className: "mudo", textContent: `Paleta do tema ${ehClaro ? "claro" : "escuro"}:` }),
      grupo(`Paleta do tema ${ehClaro ? "claro" : "escuro"}`, pal.opcoes, pal.valor, (v) => gravar(pal.id, v, pal.valor), { amostras: true })));
  }
  if (autonomia) {
    const atual = autonomia.exemplos.find((e) => e.valor === autonomia.valor);
    filhos.push(secao("Autonomia dos agentes",
      grupo("Nível de autonomia e acesso", autonomia.opcoes, autonomia.valor, trocarAutonomia, { descricoes: Object.fromEntries(autonomia.exemplos.map((e) => [e.valor, e.descricao])) }),
      el("p", { className: "mudo", role: "status", textContent: atual?.descricao || "" }),
      el("p", {}, el("span", { className: `tag ${RISCO[autonomia.valor] || ""}`.trim(), textContent: `risco ${autonomia.risco}` }))));
  }
  if (detalhe) filhos.push(secao("Interface", grupo("Nível de detalhe", detalhe.opcoes, detalhe.valor, (v) => gravar("nivel_detalhe", v, detalhe.valor))));
  filhos.push(secao("Atalhos",
    el("div", { className: "linha" },
      el("button", { type: "button", className: "primario", onclick: novoProjeto }, icone("mais", 16), "Novo projeto"),
      el("button", { type: "button", onclick: () => emitir("ir", "config") }, icone("config", 16), "Todas as configurações"),
      el("button", { type: "button", onclick: () => emitir("atalhos") }, icone("teclado", 16), "Atalhos de teclado"))));
  raiz.replaceChildren(...filhos);
  if (foco) raiz.querySelector(`[aria-label="${CSS.escape(foco)}"] [aria-checked="true"]`)?.focus({ preventScroll: true }); // mantem o foco do teclado apos redesenhar
}

/** Abre a janela de ajustes (nao bloqueante). `foco`: "autonomia" ou "tema" leva o foco direto ao seletor. */
export async function abrirAjustes({ foco = "" } = {}) {
  const raiz = el("div", { className: "ajustes" }, el("p", { className: "mudo", role: "status", textContent: "Carregando…" }));
  const j = janela("Ajustes rápidos", raiz, { id: ID_JANELA, modal: false, classe: "janela-ajustes", aoFechar: () => { aberta = null; } });
  if (aberta) { focarSeletor(foco); return j; } // janela ja aberta: so traz para a frente (ui.js) e foca o seletor pedido
  aberta = { raiz, redesenhar: () => prefsAtuais && desenhar(raiz, prefsAtuais) };
  try { prefsAtuais = await obterPreferencias(); } catch (e) { raiz.replaceChildren(el("p", { className: "aviso", role: "alert", textContent: e.message })); return j; }
  desenhar(raiz, prefsAtuais);
  focarSeletor(foco);
  return j;
}
function focarSeletor(foco) {
  const rotulo = foco === "autonomia" ? "Nível de autonomia e acesso" : foco === "tema" ? "Tema" : "";
  if (rotulo) $(`#${ID_JANELA} [aria-label="${rotulo}"] [aria-checked="true"]`)?.focus();
}

// ---------------------------------------------------------------- cabecalho: botao de tema e chip de autonomia
function atualizarCabecalho(prefs) {
  prefsAtuais = prefs;
  const tema = itemPreferencia(prefs, "tema"), autonomia = itemPreferencia(prefs, "nivel_autonomia");
  const bt = $("#tema-rapido"), ca = $("#autonomia-chip");
  if (bt && tema) {
    const proximo = rotuloDe(tema, TEMAS[(TEMAS.indexOf(tema.valor) + 1) % TEMAS.length]);
    bt.setAttribute("aria-label", `Tema: ${rotuloDe(tema, tema.valor)}. Alternar para ${proximo}`);
    bt.title = `Tema: ${rotuloDe(tema, tema.valor)} · clique para ${proximo} (Ctrl+K Ctrl+T abre tema e paleta)`;
    bt.replaceChildren(icone(efetivoClaro(tema.valor) ? "sol" : "lua", 16));
  }
  if (ca && autonomia) {
    const r = rotuloDe(autonomia, autonomia.valor);
    ca.hidden = false; ca.dataset.nivel = autonomia.valor;
    ca.title = `Autonomia dos agentes: ${r}. Clique para mudar (Ctrl+Alt+S)`;
    ca.setAttribute("aria-label", `Autonomia dos agentes: ${r}. Abrir ajustes`);
    ca.replaceChildren(icone("escudo", 14), el("span", { className: "trunc", textContent: r }));
  }
  if (aberta) desenhar(aberta.raiz, prefs);
}

export function iniciarAjustes() {
  $("#tema-rapido").addEventListener("click", alternarTema);
  $("#ajustes-rapidos").addEventListener("click", () => abrirAjustes());
  $("#autonomia-chip").addEventListener("click", () => abrirAjustes({ foco: "autonomia" }));
  ouvir("preferencias", atualizarCabecalho);
  ouvir("ajustes", (foco) => abrirAjustes({ foco: foco || "" }));
  sistemaClaro.addEventListener?.("change", () => prefsAtuais && atualizarCabecalho(prefsAtuais));
}
