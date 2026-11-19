// Realce de sintaxe leve (sem dependencias): tokenizador por expressoes "sticky" por linguagem. Gera nos DOM (span + texto),
// nunca HTML em string. Arquivos grandes ficam sem realce (o editor continua normal).
const PALAVRAS = {
  python: "False None True and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield match case self",
  javascript: "await break case catch class const continue debugger default delete do else export extends finally for from function if import in instanceof let new of return static super switch this throw try typeof var void while with yield async null undefined true false interface type enum implements readonly private public protected as",
  sql: "select from where insert into values update set delete create table index view drop alter add column primary key foreign references join left right inner outer on group by order having limit offset as and or not null is in exists distinct union all case when then else end begin commit rollback with",
  shell: "if then else elif fi for while do done case esac function return in export local echo exit set unset param begin process end foreach switch try catch finally",
  docker: "FROM RUN CMD LABEL EXPOSE ENV ADD COPY ENTRYPOINT VOLUME USER WORKDIR ARG ONBUILD STOPSIGNAL HEALTHCHECK SHELL AS",
};
const conjunto = (s, i = false) => new Set(s.split(" ").map((x) => (i ? x.toLowerCase() : x)));
const KW = { python: conjunto(PALAVRAS.python), javascript: conjunto(PALAVRAS.javascript), typescript: conjunto(PALAVRAS.javascript),
  sql: conjunto(PALAVRAS.sql, true), shell: conjunto(PALAVRAS.shell, true), powershell: conjunto(PALAVRAS.shell, true), docker: conjunto(PALAVRAS.docker) };
const IDENT = /[A-Za-z_$\u00c0-\u024f][\w$\u00c0-\u024f]*/y;
const RESTO = /\s+|[^\sA-Za-z_$\u00c0-\u024f]/y;
const NUM = [/0[xX][\da-fA-F_]+|\d[\d_]*(\.\d+)?([eE][+-]?\d+)?/y, "num"];

const REGRAS = {
  python: [[/#.*/y, "com"], [/("""|''')[\s\S]*?(\1|$)/y, "str"], [/[rbfuRBFU]{0,2}("(\\.|[^"\\\n])*"?|'(\\.|[^'\\\n])*'?)/y, "str"], [/@[\w.]+/y, "dec"], NUM],
  javascript: [[/\/\/.*/y, "com"], [/\/\*[\s\S]*?(\*\/|$)/y, "com"], [/`(\\.|[^`\\])*`?/y, "str"], [/"(\\.|[^"\\\n])*"?|'(\\.|[^'\\\n])*'?/y, "str"], NUM],
  json: [[/"(\\.|[^"\\\n])*"(?=\s*:)/y, "chave"], [/"(\\.|[^"\\\n])*"?/y, "str"], [/\b(true|false|null)\b/y, "kw"], [/-?\d+(\.\d+)?([eE][+-]?\d+)?/y, "num"]],
  css: [[/\/\*[\s\S]*?(\*\/|$)/y, "com"], [/"[^"\n]*"?|'[^'\n]*'?/y, "str"], [/@[\w-]+/y, "kw"], [/#[\da-fA-F]{3,8}\b/y, "num"],
    [/-?\d+(\.\d+)?(px|em|rem|%|vh|vw|ms|s|fr|deg)?/y, "num"], [/[\w-]+(?=\s*:[^{};]*;?)/y, "chave"], [/[.#]?[\w-]+(?=[^{};]*\{)/y, "tag"]],
  html: [[/<!--[\s\S]*?(-->|$)/y, "com"], [/<\/?[\w:-]+/y, "tag"], [/\/?>/y, "tag"], [/[\w:-]+(?==)/y, "attr"], [/"[^"]*"?|'[^']*'?/y, "str"], [/&\w+;/y, "num"]],
  markdown: [[/^#{1,6} .*/my, "titulo"], [/^```.*$/my, "com"], [/`[^`\n]+`/y, "str"], [/\*\*[^*\n]+\*\*|__[^_\n]+__/y, "kw"], [/\*[^*\n]+\*|_[^_\n]+_/y, "enfase"],
    [/\[\[[^\]\n]+\]\]|\[[^\]\n]*\]\([^)\n]*\)/y, "link"], [/^\s*([-*+]|\d+\.) /my, "num"], [/^>.*/my, "com"]],
  sql: [[/--.*/y, "com"], [/\/\*[\s\S]*?(\*\/|$)/y, "com"], [/'(''|[^'])*'?/y, "str"], NUM],
  shell: [[/#.*/y, "com"], [/"(\\.|[^"\\])*"?|'[^']*'?/y, "str"], [/\$\{?[\w:]+\}?/y, "var"], [/-{1,2}[\w-]+/y, "attr"], NUM],
  yaml: [[/#.*/y, "com"], [/^\s*[\w.-]+(?=\s*:)/my, "chave"], [/"(\\.|[^"\\\n])*"?|'[^'\n]*'?/y, "str"], [/\b(true|false|null|yes|no)\b/y, "kw"], NUM],
  toml: [[/#.*/y, "com"], [/^\s*\[[^\]\n]*\]/my, "tag"], [/^\s*[\w.-]+(?=\s*=)/my, "chave"], [/"(\\.|[^"\\\n])*"?|'[^'\n]*'?/y, "str"], [/\b(true|false)\b/y, "kw"], NUM],
  diff: [[/^(\+\+\+|---).*$/my, "titulo"], [/^@@.*$/my, "dec"], [/^\+.*$/my, "add"], [/^-.*$/my, "rem"]],
};
REGRAS.typescript = REGRAS.javascript; REGRAS.xml = REGRAS.html; REGRAS.ini = REGRAS.toml; REGRAS.powershell = REGRAS.shell;
REGRAS.docker = [[/#.*/y, "com"], [/"(\\.|[^"\\])*"?/y, "str"], [/\$\{?\w+\}?/y, "var"], NUM];

export const MAX_REALCE = 200_000;

/** Palavras-chave da linguagem (para o autocompletar do editor). */
export function palavrasChave(linguagem) {
  const ling = linguagem === "typescript" ? "javascript" : linguagem;
  return PALAVRAS[ling] ? PALAVRAS[ling].split(" ") : [];
}

/** Tokens [tipo|null, texto] do texto todo. Linguagem sem regras: um token so. */
export function tokens(texto, linguagem) {
  const regras = REGRAS[linguagem];
  if (!regras || texto.length > MAX_REALCE) return [[null, texto]];
  const kw = KW[linguagem];
  const saida = [];
  let i = 0, simples = "";
  const empurrar = (tipo, t) => { if (!tipo) { simples += t; return; } if (simples) { saida.push([null, simples]); simples = ""; } saida.push([tipo, t]); };
  while (i < texto.length) {
    let casou = false;
    for (const [re, tipo] of regras) {
      re.lastIndex = i;
      const m = re.exec(texto);
      if (m && m[0].length) { empurrar(tipo, m[0]); i += m[0].length; casou = true; break; }
    }
    if (casou) continue;
    IDENT.lastIndex = i;
    const id = IDENT.exec(texto);
    if (id) {
      const p = id[0];
      const prox = texto[i + p.length];
      const tipo = kw && (kw.has(p) || kw.has(p.toLowerCase()) && (linguagem === "sql" || linguagem === "shell" || linguagem === "powershell")) ? "kw"
        : prox === "(" && regras !== REGRAS.markdown ? "fn" : /^[A-Z][a-z]/.test(p) && (linguagem === "python" || linguagem === "javascript" || linguagem === "typescript") ? "tipo" : null;
      empurrar(tipo, p); i += p.length; continue;
    }
    RESTO.lastIndex = i;
    const r = RESTO.exec(texto);
    const t = r ? r[0] : texto[i];
    empurrar(null, t); i += t.length;
  }
  if (simples) saida.push([null, simples]);
  return saida;
}

/** Preenche `destino` (um <code>/<pre>) com o texto realcado. `marcas` = trechos [ini, fim] da busca (viram <mark>). */
export function realcar(destino, texto, linguagem, marcas = []) {
  const frag = document.createDocumentFragment();
  let pos = 0, m = 0;
  const pedaco = (tipo, t) => {
    const no = tipo ? document.createElement("span") : null;
    if (no) { no.className = `tk-${tipo}`; no.textContent = t; frag.append(no); } else frag.append(document.createTextNode(t));
  };
  for (const [tipo, t] of tokens(texto, linguagem)) {
    let ini = pos;
    const fim = pos + t.length;
    while (m < marcas.length && marcas[m][0] < fim) {
      const [a, b] = marcas[m];
      if (a > ini) pedaco(tipo, texto.slice(ini, a));
      const ate = Math.min(b, fim);
      const mk = document.createElement("mark"); mk.className = `tk-${tipo || "x"}`; mk.textContent = texto.slice(Math.max(a, ini), ate); frag.append(mk);
      ini = ate;
      if (b <= fim) m += 1; else break;
    }
    if (ini < fim) pedaco(tipo, texto.slice(ini, fim));
    pos = fim;
  }
  frag.append(document.createTextNode("\n")); // a ultima linha vazia tambem ocupa altura (alinhamento com a textarea)
  destino.replaceChildren(frag);
}
