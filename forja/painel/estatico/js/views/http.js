// Requisicoes HTTP (estilo Postman/Insomnia): metodo, URL, parametros, cabecalhos, corpo, autenticacao e variaveis {{nome}};
// resposta com status, tempo, tamanho, corpo formatado e cabecalhos; colecoes, historico e "copiar como curl".
// A requisicao sai do servidor local (o painel nao fala com a internet: CSP). Colecoes e variaveis ficam so neste navegador.
import { api } from "../api.js";
import { realcar } from "../realce.js";
import { dialogo, el, limpar, tag, toast } from "../ui.js";

const METODOS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"];
const CHAVE = "forja_http";
const ler = () => { try { return { colecoes: [], ambiente: [["base_url", "http://127.0.0.1:8000"]], historico: [], ...JSON.parse(localStorage.getItem(CHAVE) || "{}") }; } catch { return { colecoes: [], ambiente: [], historico: [] }; } };
const gravar = () => localStorage.setItem(CHAVE, JSON.stringify(dados));
const nova = () => ({ nome: "Nova requisição", metodo: "GET", url: "{{base_url}}/", parametros: [["", "", true]], cabecalhos: [["Accept", "application/json", true]], corpo: "", tipoCorpo: "nenhum", auth: { tipo: "nenhum", valor: "" } });
let dados = ler();
let atual = JSON.parse(localStorage.getItem(`${CHAVE}_atual`) || "null") || nova();
let resposta = null;
let raizAtual = null;
let abaReq = "parametros", abaResp = "corpo";

const variaveis = () => Object.fromEntries(dados.ambiente.filter(([k]) => k));
const trocarVars = (s) => String(s ?? "").replace(/\{\{\s*([\w.-]+)\s*\}\}/g, (m, k) => (k in variaveis() ? variaveis()[k] : m));

function montarPedido(r) {
  let url = trocarVars(r.url.trim());
  const ps = r.parametros.filter(([k, , on]) => k && on).map(([k, v]) => `${encodeURIComponent(trocarVars(k))}=${encodeURIComponent(trocarVars(v))}`);
  if (ps.length) url += (url.includes("?") ? "&" : "?") + ps.join("&");
  const cab = Object.fromEntries(r.cabecalhos.filter(([k, , on]) => k && on).map(([k, v]) => [trocarVars(k), trocarVars(v)]));
  if (r.auth.tipo === "bearer" && r.auth.valor) cab.Authorization = `Bearer ${trocarVars(r.auth.valor)}`;
  if (r.auth.tipo === "basic" && r.auth.valor) cab.Authorization = `Basic ${btoa(unescape(encodeURIComponent(trocarVars(r.auth.valor))))}`;
  let corpo = null;
  if (r.tipoCorpo !== "nenhum" && !["GET", "HEAD"].includes(r.metodo)) {
    corpo = trocarVars(r.corpo);
    const tipo = { json: "application/json", texto: "text/plain", form: "application/x-www-form-urlencoded" }[r.tipoCorpo];
    if (tipo && !Object.keys(cab).some((k) => k.toLowerCase() === "content-type")) cab["Content-Type"] = tipo;
  }
  return { metodo: r.metodo, url, cabecalhos: cab, corpo };
}

function comoCurl(r) {
  const p = montarPedido(r);
  const q = (s) => `"${String(s).replace(/(["\\$`])/g, "\\$1")}"`;
  return ["curl.exe", "-i", p.metodo !== "GET" ? `-X ${p.metodo}` : "", ...Object.entries(p.cabecalhos).map(([k, v]) => `-H ${q(`${k}: ${v}`)}`),
    p.corpo ? `--data-raw ${q(p.corpo)}` : "", q(p.url)].filter(Boolean).join(" ");
}

async function enviar() {
  const pedido = montarPedido(atual);
  if (!/^https?:\/\//i.test(pedido.url)) return toast("A URL precisa começar com http:// ou https:// (confira as variáveis {{...}}).", "erro");
  resposta = { carregando: true };
  desenhar();
  try { resposta = await api("POST", "/area/http", { ...pedido, tempo_s: 30 }); } catch (e) { resposta = { status: 0, erro: e.message }; }
  dados.historico = [{ quando: new Date().toISOString(), metodo: atual.metodo, url: atual.url, status: resposta.status, req: structuredClone(atual) }, ...dados.historico].slice(0, 40);
  gravar();
  desenhar();
}

function tabelaPares(lista, rotulos, aoMudar) {
  const corpo = el("tbody");
  const linha = (par, i) => {
    const k = el("input", { value: par[0], placeholder: rotulos[0], "aria-label": `${rotulos[0]} ${i + 1}`, spellcheck: false });
    const v = el("input", { value: par[1], placeholder: rotulos[1], "aria-label": `${rotulos[1]} ${i + 1}`, spellcheck: false });
    const on = el("input", { type: "checkbox", checked: par[2] !== false, "aria-label": `Ativo ${i + 1}` });
    const sinc = () => { lista[i] = [k.value, v.value, on.checked]; if (i === lista.length - 1 && (k.value || v.value)) { lista.push(["", "", true]); aoMudar(true); } else aoMudar(false); };
    for (const c of [k, v]) c.addEventListener("input", sinc);
    on.addEventListener("change", sinc);
    return el("tr", {}, el("td", {}, on), el("td", {}, k), el("td", {}, v),
      el("td", {}, el("button", { type: "button", className: "icone pequeno", "aria-label": `Remover linha ${i + 1}`, textContent: "✕", onclick: () => { lista.splice(i, 1); if (!lista.length) lista.push(["", "", true]); aoMudar(true); } })));
  };
  corpo.append(...lista.map(linha));
  return el("table", { className: "tabela-pares" }, el("thead", {}, el("tr", {}, el("th", { scope: "col", className: "sr-only", textContent: "Ativo" }),
    el("th", { scope: "col", textContent: rotulos[0] }), el("th", { scope: "col", textContent: rotulos[1] }), el("th", { scope: "col", className: "sr-only", textContent: "Remover" }))), corpo);
}

function salvarNaColecao() {
  const nome = el("input", { value: atual.nome, maxLength: 120, "aria-label": "Nome da requisição" });
  const col = el("input", { value: dados.colecoes[0]?.nome || "Minha API", maxLength: 80, list: "colecoes-http", "aria-label": "Coleção" });
  const d = dialogo("Salvar requisição", el("form", { onsubmit: (ev) => {
    ev.preventDefault();
    atual.nome = nome.value.trim() || "Requisição";
    let c = dados.colecoes.find((x) => x.nome === col.value.trim());
    if (!c) { c = { nome: col.value.trim() || "Minha API", requisicoes: [] }; dados.colecoes.push(c); }
    c.requisicoes = [...c.requisicoes.filter((x) => x.nome !== atual.nome), structuredClone(atual)];
    gravar(); d.fechar(); desenhar(); toast("Salvo na coleção.", "ok");
  } }, el("label", { className: "campo" }, el("span", { textContent: "Nome" }), nome), el("label", { className: "campo" }, el("span", { textContent: "Coleção" }), col),
  el("datalist", { id: "colecoes-http" }, ...dados.colecoes.map((c) => el("option", { value: c.nome }))),
  el("div", { className: "linha fim" }, el("button", { type: "button", textContent: "Cancelar", onclick: () => d.fechar() }), el("button", { type: "submit", className: "primario", textContent: "Salvar" }))));
}

function ladoColecoes() {
  const usar = (r) => { atual = structuredClone(r); resposta = null; desenhar(); };
  const imp = el("input", { type: "file", accept: ".json,application/json", hidden: true, onchange: async () => {
    try { const j = JSON.parse(await imp.files[0].text()); if (Array.isArray(j.colecoes)) { dados.colecoes.push(...j.colecoes); gravar(); desenhar(); toast("Coleções importadas.", "ok"); } }
    catch { toast("Arquivo inválido (esperado o JSON exportado pela Forja).", "erro"); }
  } });
  return el("aside", { className: "http-lado", "aria-label": "Coleções e histórico" },
    el("div", { className: "linha" }, el("button", { type: "button", className: "pequeno primario", textContent: "+ Nova", onclick: () => usar(nova()) }),
      el("button", { type: "button", className: "pequeno", textContent: "Exportar", onclick: () => { const b = new Blob([JSON.stringify({ colecoes: dados.colecoes }, null, 1)], { type: "application/json" });
        const a = el("a", { href: URL.createObjectURL(b), download: "colecoes-forja.json" }); a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000); } }),
      el("button", { type: "button", className: "pequeno", textContent: "Importar", onclick: () => imp.click() }), imp),
    el("h3", { textContent: "Coleções" }),
    ...(dados.colecoes.length ? dados.colecoes.map((c, ci) => el("details", { open: true }, el("summary", { textContent: `${c.nome} (${c.requisicoes.length})` }),
      el("ul", { className: "lista-http" }, ...c.requisicoes.map((r, ri) => el("li", { className: "linha" },
        el("button", { type: "button", className: "bloco", onclick: () => usar(r) }, el("span", { className: `metodo m-${r.metodo}`, textContent: r.metodo }), el("span", { className: "trunc", textContent: r.nome })),
        el("button", { type: "button", className: "icone pequeno", "aria-label": `Apagar ${r.nome}`, textContent: "✕", onclick: () => { c.requisicoes.splice(ri, 1); if (!c.requisicoes.length) dados.colecoes.splice(ci, 1); gravar(); desenhar(); } }))))))
      : [el("p", { className: "mudo", textContent: "Salve requisições para reaproveitar." })]),
    el("h3", { textContent: "Histórico" }),
    el("ul", { className: "lista-http" }, ...dados.historico.slice(0, 15).map((h) => el("li", {}, el("button", { type: "button", className: "bloco", title: h.url, onclick: () => usar(h.req) },
      el("span", { className: `metodo m-${h.metodo}`, textContent: h.metodo }), el("span", { className: "trunc", textContent: h.url }),
      el("span", { className: `status-http s${String(h.status)[0]}`, textContent: h.status || "erro" }))))),
    el("h3", { textContent: "Variáveis ({{nome}})" }),
    tabelaPares(dados.ambiente, ["nome", "valor"], (estrutura) => { gravar(); if (estrutura) desenhar(); }),
    el("p", { className: "mudo", textContent: "Coleções, histórico e variáveis ficam só neste navegador. Tokens aqui não vão para os agentes." }));
}

function painelPedido() {
  const metodo = el("select", { className: `seletor-metodo m-${atual.metodo}`, "aria-label": "Método" }, ...METODOS.map((m) => el("option", { value: m, textContent: m, selected: m === atual.metodo })));
  metodo.addEventListener("change", () => { atual.metodo = metodo.value; metodo.className = `seletor-metodo m-${atual.metodo}`; guardar(); });
  const url = el("input", { type: "text", value: atual.url, className: "url-http", "aria-label": "URL", placeholder: "https://api.exemplo.com/recurso ou {{base_url}}/recurso", spellcheck: false });
  url.addEventListener("input", () => { atual.url = url.value; guardar(); });
  url.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); enviar(); } });
  const abasDef = [["parametros", `Parâmetros${atual.parametros.filter(([k]) => k).length ? ` (${atual.parametros.filter(([k]) => k).length})` : ""}`],
    ["cabecalhos", `Cabeçalhos (${atual.cabecalhos.filter(([k]) => k).length})`], ["corpo", "Corpo"], ["auth", "Autenticação"]];
  const conteudo = el("div", { className: "http-aba" });
  const desenharAba = () => {
    limpar(conteudo);
    if (abaReq === "parametros") conteudo.append(tabelaPares(atual.parametros, ["parâmetro", "valor"], (e) => { guardar(); if (e) desenharAba(); }));
    else if (abaReq === "cabecalhos") conteudo.append(tabelaPares(atual.cabecalhos, ["cabeçalho", "valor"], (e) => { guardar(); if (e) desenharAba(); }));
    else if (abaReq === "corpo") {
      const tipo = el("div", { className: "segmentado", role: "group", "aria-label": "Tipo do corpo" }, ...[["nenhum", "Nenhum"], ["json", "JSON"], ["texto", "Texto"], ["form", "Formulário"]].map(([v, r]) =>
        el("button", { type: "button", "aria-pressed": String(atual.tipoCorpo === v), textContent: r, onclick: () => { atual.tipoCorpo = v; guardar(); desenharAba(); } })));
      const area = el("textarea", { className: "corpo-http", rows: 10, value: atual.corpo, spellcheck: false, "aria-label": "Corpo da requisição", disabled: atual.tipoCorpo === "nenhum",
        placeholder: atual.tipoCorpo === "json" ? '{\n  "nome": "valor"\n}' : atual.tipoCorpo === "form" ? "campo=valor&outro=1" : "" });
      area.addEventListener("input", () => { atual.corpo = area.value; guardar(); });
      const erro = el("p", { className: "erro-cmd", role: "status" });
      conteudo.append(tipo, area, el("div", { className: "linha" }, atual.tipoCorpo === "json" ? el("button", { type: "button", className: "pequeno", textContent: "Formatar JSON", onclick: () => {
        try { area.value = JSON.stringify(JSON.parse(area.value), null, 2); atual.corpo = area.value; guardar(); erro.textContent = ""; }
        catch (e) { erro.textContent = `JSON inválido: ${e.message}`; } } }) : null, erro));
    } else {
      const tipo = el("select", { "aria-label": "Tipo de autenticação" }, ...[["nenhum", "Nenhuma"], ["bearer", "Bearer token"], ["basic", "Básica (usuário:senha)"]].map(([v, r]) => el("option", { value: v, textContent: r, selected: atual.auth.tipo === v })));
      const valor = el("input", { type: "password", value: atual.auth.valor, "aria-label": "Credencial", placeholder: atual.auth.tipo === "basic" ? "usuario:senha" : "token ou {{token}}", autocomplete: "off" });
      tipo.addEventListener("change", () => { atual.auth.tipo = tipo.value; guardar(); desenharAba(); });
      valor.addEventListener("input", () => { atual.auth.valor = valor.value; guardar(); });
      conteudo.append(el("div", { className: "linha" }, tipo, atual.auth.tipo !== "nenhum" ? valor : null),
        el("p", { className: "mudo", textContent: "Dica: guarde o token numa variável ({{token}}) e use {{token}} aqui." }));
    }
  };
  const abasNo = el("div", { role: "tablist", "aria-label": "Partes da requisição" }, ...abasDef.map(([id, r]) => el("button", { type: "button", role: "tab", id: `aba-http-${id}`,
    "aria-selected": String(abaReq === id), tabIndex: abaReq === id ? 0 : -1, textContent: r, onclick: () => { abaReq = id; desenhar(); } })));
  desenharAba();
  return el("section", { className: "http-pedido", "aria-label": "Requisição" },
    el("div", { className: "barra-url" }, metodo, url, el("button", { type: "button", className: "primario", textContent: resposta?.carregando ? "Enviando…" : "Enviar", disabled: Boolean(resposta?.carregando), onclick: enviar }),
      el("button", { type: "button", textContent: "Salvar", onclick: salvarNaColecao }),
      el("button", { type: "button", title: "Copiar como curl", onclick: async () => { try { await navigator.clipboard.writeText(comoCurl(atual)); toast("Comando curl copiado.", "ok"); } catch { dialogo("curl", el("pre", { textContent: comoCurl(atual) })); } } }, "curl")),
    el("p", { className: "mudo url-final trunc", title: montarPedido(atual).url, textContent: `→ ${montarPedido(atual).url}` }), abasNo, conteudo);
}

function painelResposta() {
  const r = resposta;
  if (!r) return el("section", { className: "http-resposta vazio-acao" }, el("p", { textContent: "Monte a requisição e clique em Enviar (ou Enter na URL)." }),
    el("p", { className: "mudo", textContent: "Útil para testar APIs locais (FastAPI, Express...) e serviços externos, com cabeçalhos, corpo e autenticação." }));
  if (r.carregando) return el("section", { className: "http-resposta" }, el("p", { className: "mudo", textContent: "Aguardando resposta…" }));
  if (!r.status) return el("section", { className: "http-resposta" }, el("p", { className: "aviso", role: "alert", textContent: `Falhou: ${r.erro || "sem resposta"}` }));
  const tipo = (r.tipo || "").toLowerCase();
  let corpoFmt = r.corpo || "", ling = "texto";
  if (tipo.includes("json") || /^\s*[[{]/.test(corpoFmt)) { try { corpoFmt = JSON.stringify(JSON.parse(corpoFmt), null, 2); ling = "json"; } catch { /* nao era JSON */ } }
  else if (tipo.includes("html") || tipo.includes("xml")) ling = "html";
  const codigo = el("code");
  realcar(codigo, corpoFmt.slice(0, 400_000), ling);
  const abas = el("div", { role: "tablist", "aria-label": "Partes da resposta" }, ...[["corpo", "Corpo"], ["cabecalhos", `Cabeçalhos (${r.cabecalhos.length})`]].map(([id, rot]) =>
    el("button", { type: "button", role: "tab", id: `aba-resp-${id}`, "aria-selected": String(abaResp === id), tabIndex: abaResp === id ? 0 : -1, textContent: rot, onclick: () => { abaResp = id; desenhar(); } })));
  const kb = (n) => (n > 1024 * 1024 ? `${(n / 1048576).toFixed(1)} MB` : n > 1024 ? `${(n / 1024).toFixed(1)} KB` : `${n} B`);
  return el("section", { className: "http-resposta", "aria-label": "Resposta" },
    el("div", { className: "linha resumo-resposta" }, el("span", { className: `status-http grande s${String(r.status)[0]}`, textContent: `${r.status} ${r.motivo || ""}` }),
      tag(`${r.tempo_ms} ms`), tag(kb(r.tamanho)), r.redirecionamentos ? tag(`${r.redirecionamentos} redirecionamento(s)`) : null, r.truncado ? tag("cortada (2 MB)", "aviso") : null,
      el("span", { className: "espaco" }), el("button", { type: "button", className: "pequeno", textContent: "Copiar corpo", onclick: async () => { try { await navigator.clipboard.writeText(r.corpo || ""); toast("Copiado.", "ok"); } catch { toast("Sem acesso à área de transferência.", "erro"); } } })),
    abas,
    abaResp === "corpo" ? (r.base64 ? el("p", { className: "mudo", textContent: `Resposta binária (${r.tipo || "?"}, ${kb(r.tamanho)}): não exibida.` }) : el("pre", { className: "corpo-resposta", tabIndex: 0 }, codigo))
      : el("table", { className: "tabela-pares" }, el("tbody", {}, ...r.cabecalhos.map(([k, v]) => el("tr", {}, el("th", { scope: "row", textContent: k }), el("td", { textContent: v }))))));
}

let tGuardar = null;
const guardar = () => { clearTimeout(tGuardar); tGuardar = setTimeout(() => localStorage.setItem(`${CHAVE}_atual`, JSON.stringify(atual)), 300); };

function desenhar() {
  if (!raizAtual?.isConnected) return;
  const foco = document.activeElement?.className === "url-http";
  limpar(raizAtual);
  raizAtual.append(el("div", { className: "titulo-vista" }, el("h1", { textContent: "Requisições HTTP" }), el("span", { className: "mudo", textContent: atual.nome })),
    el("div", { className: "http-grade" }, ladoColecoes(), el("div", { className: "http-principal" }, painelPedido(), painelResposta())));
  if (foco) raizAtual.querySelector(".url-http")?.focus();
}

export function montar(raiz) {
  raizAtual = raiz;
  dados = ler();
  desenhar();
}
