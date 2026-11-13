// Cliente da API. A credencial (sessao do login ou token da API) fica so em sessionStorage (esta aba); nunca e exibida nem registrada.
const BASE = "/api/v1";
let token = sessionStorage.getItem("forja_token") || "";

export const temToken = () => Boolean(token);
export const lerToken = () => token;
export function definirToken(valor) {
  token = (valor || "").trim();
  if (token) sessionStorage.setItem("forja_token", token); else sessionStorage.removeItem("forja_token");
}

export class ErroApi extends Error {
  constructor(mensagem, status, dados = null) { super(mensagem); this.status = status; this.dados = dados; }
}

export async function api(metodo, caminho, corpo) {
  const cab = { "Content-Type": "application/json" };
  if (token) cab.Authorization = `Bearer ${token}`;
  let resp;
  try {
    resp = await fetch(BASE + caminho, { method: metodo, headers: cab, body: corpo === undefined ? undefined : JSON.stringify(corpo) });
  } catch {
    throw new ErroApi("Sem conexao com o servidor local.", 0);
  }
  const texto = await resp.text();
  let dados = null;
  try { dados = texto ? JSON.parse(texto) : null; } catch { dados = null; }
  if (!resp.ok) {
    // sessao expirada em qualquer tela -> volta para o login (as rotas /auth tratam o proprio erro na tela de acesso)
    if (resp.status === 401 && !caminho.startsWith("/auth/")) document.dispatchEvent(new CustomEvent("forja:auth"));
    // nunca repassa stack trace: usa apenas a mensagem de dominio ou um texto generico
    const msg = dados?.mensagem || (dados?.detalhes ? "Dados invalidos: " + dados.detalhes.map((d) => `${d.local?.slice(1).join(".")} ${d.msg}`).join("; ")
      : resp.status === 401 ? "Sessão expirada ou credenciais inválidas." : `Falha HTTP ${resp.status}`);
    throw new ErroApi(msg, resp.status, dados);
  }
  return dados;
}

export const consulta = (params) => new URLSearchParams(Object.entries(params).filter(([, v]) => v !== "" && v !== undefined && v !== null)).toString();
