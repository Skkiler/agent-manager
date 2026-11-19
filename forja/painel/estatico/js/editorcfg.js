// Configuracao do editor vinda do servidor (preferencias da tela Configuracoes > Editor, estado dos servidores de linguagem e
// catalogo de autocompletar por linguagem). Cache curto: mudar uma preferencia vale no proximo arquivo aberto ou em ate 30 s.
import { api } from "./api.js";

const VALIDADE_MS = 30_000;
let cfg = null, quando = 0, pendente = null;
const catalogos = new Map();

export const PADRAO = { autocompletar_codigo: true, autocompletar_automatico: true, autocompletar_atraso_ms: 120, autocompletar_max: 12,
  autocompletar_fontes: ["lsp", "catalogo", "trechos", "palavras"], autocompletar_ramos_desligados: [], lsp_ativo: true, terminal_assistente: true };

/** {preferencias, lsp, ramos}; nunca rejeita (sem servidor vale o padrao). */
export function configEditor(forcar = false) {
  if (!forcar && cfg && Date.now() - quando < VALIDADE_MS) return Promise.resolve(cfg);
  pendente ||= api("GET", "/area/editor").then((r) => { cfg = { ...r, preferencias: { ...PADRAO, ...(r.preferencias || {}) } }; quando = Date.now(); return cfg; })
    .catch(() => cfg || { preferencias: { ...PADRAO }, lsp: null, ramos: [] }).finally(() => { pendente = null; });
  return pendente;
}

/** Leitura sincrona (ultimo valor conhecido) para o caminho quente das teclas. */
export const prefsEditor = () => (cfg ? cfg.preferencias : PADRAO);

/** O servidor de linguagem desta linguagem esta instalado? (e o LSP ligado) */
export function lspDisponivel(linguagem) {
  const p = prefsEditor();
  if (!p.lsp_ativo || !(p.autocompletar_fontes || []).includes("lsp") || !cfg?.lsp?.servidores) return false;
  return cfg.lsp.servidores.some((s) => s.disponivel && s.linguagens.includes(linguagem));
}

export function lspLigado(linguagem) {
  const p = prefsEditor();
  return Boolean(p.lsp_ativo && cfg?.lsp?.servidores?.some((s) => s.disponivel && s.linguagens.includes(linguagem)));
}

/** Catalogo de autocompletar (ramos com itens) da linguagem; cache por sessao, invalidado ao salvar preferencias. */
export function catalogoDe(linguagem) {
  if (!catalogos.has(linguagem)) {
    catalogos.set(linguagem, api("GET", `/area/codigo/catalogo?linguagem=${encodeURIComponent(linguagem)}`)
      .then((r) => preparar(r.ramos || [])).catch(() => { catalogos.delete(linguagem); return []; }));
  }
  return catalogos.get(linguagem);
}

function preparar(ramos) {
  return ramos.map((r) => {
    let detectar = [];
    try { detectar = (r.detectar || []).map((x) => new RegExp(x, "m")); } catch { detectar = []; }
    return { ...r, detectar };
  });
}

export function invalidarEditor() { cfg = null; quando = 0; catalogos.clear(); }

addEventListener("forja:preferencias", () => invalidarEditor());
