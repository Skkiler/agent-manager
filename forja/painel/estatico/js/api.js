// Cliente da API. O token fica so em sessionStorage (esta aba) e nunca e exibido nem registrado.
const BASE = "/api/v1";
let token = sessionStorage.getItem("forja_token") || "";

export const temToken = () => Boolean(token);
export const lerToken = () => token;
export function definirToken(valor) {
  token = (valor || "").trim();
  sessionStorage.setItem("forja_token", token);
}

export class ErroApi extends Error {
  constructor(mensagem, status) { super(mensagem); this.status = status; }
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
    if (resp.status === 401) document.dispatchEvent(new CustomEvent("forja:auth"));
    // nunca repassa stack trace: usa apenas a mensagem de dominio ou um texto generico
    const msg = dados?.mensagem || (dados?.detalhes ? "Dados invalidos: " + dados.detalhes.map((d) => `${d.local?.slice(1).join(".")} ${d.msg}`).join("; ") : `Falha HTTP ${resp.status}`);
    throw new ErroApi(msg, resp.status);
  }
  return dados;
}

export const consulta = (params) => new URLSearchParams(Object.entries(params).filter(([, v]) => v !== "" && v !== undefined && v !== null)).toString();
