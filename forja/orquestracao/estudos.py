"""Alimentacao do segundo cerebro: estudo de PASTA ou de TOPICO, e registro de decisoes/aprendizados de cada tarefa.

Fluxo do estudo (solicitacao de alimentacao):
1. A Forja prepara fatos DETERMINISTICOS (pasta: mapa, arquivos centrais e grafo de funcoes; topico: o que a base ja sabe).
2. Um agente de estudo (parte 'estudo' da configuracao: modelo rapido, somente leitura) escreve NOTAS curtas, uma por subtopico,
   no formato `### Nota: <titulo>` com `Topico pai:`, `Tags:` e `Fontes:`.
3. Ao concluir, a Forja cria as notas como CANDIDATAS (redigidas, com fonte) e liga cada uma ao topico pai (SUBTOPICO_DE): um
   assunto grande vira varios subtopicos pequenos e ligados. Nada nasce validado; o usuario revisa e promove.

Registro de aprendizados: ao concluir uma tarefa real (nao simulada), a Forja guarda um resumo auditavel (entendimento, plano,
premissas, decisoes, evidencias, pendencias) como nota candidata do tipo 'decisoria', ligada ao topico do projeto.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from forja.adapters.sqlite import tabelas as T
from forja.dominio.contratos import ObjetivoIn, ProjetoIn, ResultadoAgente, TarefaIn, TransicaoIn
from forja.dominio.erros import ErroDominio, ValidacaoDominio
from forja.dominio.estados import EstadoTarefa
from forja.memoria.contratos import FonteIn, MemoriaIn
from forja.memoria.modelo import Principal, validar_namespace
from forja.observabilidade.sanitizar import sanitizar_texto

log = logging.getLogger("forja.estudos")
PROJETO = "forja-estudos"
MAX_NOTAS = 30
MAX_FATOS = 2600
MAX_NOTAS_RESUMO = 25
MAX_FATOS_RESUMO = 3000
_NOTA = re.compile(r"^#{2,4}\s*Nota\s*:\s*(?P<t>.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_CAMPO = re.compile(r"^\s*(?P<k>t[oó]pico pai|pai|tags|fontes?)\s*:\s*(?P<v>.*)$", re.IGNORECASE)
_SLUG = re.compile(r"[^a-z0-9._-]+")


class EstudoIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    tipo: Literal["pasta", "topico"]
    alvo: str = Field(min_length=2, max_length=500, description="caminho da pasta (permitida) ou o topico a pesquisar")
    namespace: str = "pessoal/estudos"
    foco: str = Field("", max_length=500, description="o que interessa (ex.: 'autenticacao e banco')")
    pesquisar_web: bool = True
    executar: bool = False


@dataclass
class NotaEstudo:
    titulo: str
    corpo: str
    pai: str = ""
    tags: list[str] = field(default_factory=list)
    fontes: list[str] = field(default_factory=list)


def extrair_notas(texto: str) -> list[NotaEstudo]:
    """`### Nota: titulo` + campos opcionais + corpo, ate a proxima nota ou secao de nivel 2. Tolerante a variacoes."""
    marcas = list(_NOTA.finditer(texto))
    notas = []
    for i, m in enumerate(marcas):
        fim = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
        bloco = texto[m.end():fim]
        corte = re.search(r"^##\s+\S", bloco, re.MULTILINE)
        if corte:
            bloco = bloco[: corte.start()]
        nota = NotaEstudo(m["t"].strip(" *`")[:200], "")
        corpo = []
        for linha in bloco.splitlines():
            if not corpo and not linha.strip():
                continue  # linhas em branco antes dos campos
            c = _CAMPO.match(linha)
            if c and not corpo:
                k, v = c["k"].casefold(), c["v"].strip()
                if "pai" in k:
                    nota.pai = v.strip(" *`[]")[:200]
                elif k.startswith("tag"):
                    nota.tags = [x.strip(" #`")[:50] for x in re.split(r"[,;]", v) if x.strip(" #`")][:8]
                else:
                    nota.fontes = [x.strip(" <>`")[:200] for x in re.split(r"[,;\s]+", v) if x.strip(" <>`")][:8]
            else:
                corpo.append(linha)
        nota.corpo = "\n".join(corpo).strip()[:6000]
        if nota.titulo and nota.corpo:
            notas.append(nota)
    return notas[:MAX_NOTAS]


def _slug(s: str) -> str:
    return _SLUG.sub("-", s.casefold()).strip("-.")[:40] or "geral"


class EstudoServico:
    def __init__(self, servico: Any, memoria: Any, grafo: Any, politica: Any | None = None, principal: Principal | None = None) -> None:
        self.servico, self.memoria, self.grafo = servico, memoria, grafo
        self.politica = politica  # () -> PoliticaPastas: so pastas permitidas pelo usuario podem ser estudadas
        self.principal = principal or Principal("estudos", frozenset({"publico", "pessoal"}))
        self.registrar_aprendizados = True  # preferencia 'registrar_aprendizados'

    # ------------------------------------------------------------------ solicitacao
    def _fatos_pasta(self, pasta: Path, foco: str) -> str:
        from forja.ferramentas.estrutura import estrutura_codigo, resumo_grafo
        from forja.ferramentas.mapa import mapa_repositorio

        partes = [mapa_repositorio(pasta).resumo, estrutura_codigo(pasta, ".", "mapa", "", 15).resumo, resumo_grafo(pasta, 250)]
        fatos = "\n".join(p for p in partes if p)
        return fatos if len(fatos) <= MAX_FATOS else fatos[:MAX_FATOS] + "\n...(cortado)"

    def _fatos_topico(self, alvo: str) -> str:
        try:
            r = self.memoria.buscar(self.principal, alvo, ["publico"], limite=6)
        except ErroDominio:
            return ""
        linhas = [f"- {x.get('titulo') or x.get('caminho')}: {(x.get('resumo') or '')[:160]}" for x in r["resultados"] if x["origem"] == "memoria"]
        return ("O segundo cerebro ja sabe (nao repita; aprofunde ou corrija):\n" + "\n".join(linhas)) if linhas else ""

    def solicitar(self, d: EstudoIn) -> dict[str, Any]:
        validar_namespace(d.namespace)
        self.principal.exigir(d.namespace)
        pastas: list[dict[str, str]] = []
        if d.tipo == "pasta":
            pasta = Path(d.alvo).expanduser()
            pol = self.politica() if self.politica else None
            if pol is None or not pol.ativa or not pol.permite(pasta):
                raise ValidacaoDominio("A pasta precisa estar entre as pastas permitidas (Configuracoes > Privacidade).")
            if not pasta.is_dir():
                raise ValidacaoDominio("Pasta inexistente.")
            fatos = self._fatos_pasta(pasta.resolve(), d.foco)
            pastas = [{"caminho": str(pasta.resolve()), "papel": "consulta"}]
            assunto = pasta.name
            pedido = (f"Estude a pasta de codigo '{pasta.name}' (somente leitura) e organize o conhecimento util em notas para o segundo "
                      "cerebro: proposito, arquitetura, modulos centrais, fluxos, contratos, decisoes visiveis, riscos e como testar.")
        else:
            assunto = d.alvo[:120]
            fatos = self._fatos_topico(d.alvo)
            pedido = (f"Estude o topico '{d.alvo}' e organize o conhecimento util em notas para o segundo cerebro. "
                      + ("Pesquise na web fontes confiaveis e recentes; cada nota cita a fonte (URL) e a data. " if d.pesquisar_web
                         else "Nao pesquise na web; use o que voce sabe e marque incertezas. "))
        descricao = (pedido + (f" Foco: {d.foco}." if d.foco else "") + "\n" + fatos)[:3900]
        projeto = next(iter(self.servico.listar(T.Projeto, nome=PROJETO)), None)
        if projeto is None:
            projeto, _ = self.servico.criar_projeto(ProjetoIn(nome=PROJETO, descricao="Estudos para alimentar o segundo cerebro"))
        objetivo, _ = self.servico.criar_objetivo(ObjetivoIn(projeto_id=projeto["id"], titulo=f"Estudo: {assunto}"[:200], prioridade=4,
                                                             criterios_sucesso=["Notas candidatas criadas e ligadas por topico"]))
        tarefa, _ = self.servico.criar_tarefa(TarefaIn(
            objetivo_id=objetivo["id"], titulo=f"Estudo ({d.tipo}): {assunto}"[:200], descricao=descricao, modo="estudo",
            especialidade="estudo", criterios_aceite=["Cada nota cobre UM subtopico, curta e com fonte",
                                                      "Notas ligadas a um topico pai; nada copiado de segredos ou dados pessoais"],
            entrada={"estudo": {"tipo": d.tipo, "alvo": d.alvo[:500], "namespace": d.namespace, "assunto": assunto, "pastas": pastas}}))
        for destino in (EstadoTarefa.CLASSIFICADA, EstadoTarefa.PREPARADA):
            tarefa, _ = self.servico.transicionar(tarefa["id"], TransicaoIn(para=destino, expected_version=tarefa["versao_estado"]))
        execucao = None
        if d.executar:
            execucao = self.servico.criar_execucao(tarefa["id"])
            self.servico.iniciar_execucao(execucao["id"], "operador")
        return {"tarefa": tarefa, "execucao_id": execucao["id"] if execucao else None, "fatos_tokens": len(fatos) // 4}

    def solicitar_resumo(self, p: Principal, namespace: str, tema: str, memorias: list[str], executar: bool = True) -> dict[str, Any]:
        """9.12: pede ao Kiro (parte 'estudo' da configuracao: modelo rapido e barato, somente leitura) UMA nota-topico que resume
        um grupo de notas. O conteudo das notas vai MARCADO como dado (spotlighting). Ao concluir, `criar_notas` cria o topico
        como candidato e liga as notas a ele (SUBTOPICO_DE). Nada e apagado nem alterado nas notas originais."""
        from forja.seguranca import spotlight

        p.exigir(namespace)
        notas = []
        with self.memoria.repo.leitura() as t:
            for mid in memorias[:MAX_NOTAS_RESUMO]:
                m = t.obter(T.Memoria, mid)
                if m and m["namespace"] == namespace and p.pode(m["namespace"]) and m["estado"] not in ("revogado", "substituido", "obsoleto"):
                    notas.append(m)
        if len(notas) < 3:
            raise ValidacaoDominio("O grupo precisa de pelo menos 3 notas ativas para virar um tópico.")
        por_nota = max(120, MAX_FATOS_RESUMO // len(notas))
        blocos = "\n".join(f"- {m['titulo']}: {' '.join((m['resumo'] or m['conteudo'] or '').split())[:por_nota]}" for m in notas)
        cod = spotlight.codigo()
        descricao = (f"Organize o segundo cerebro: escreva UMA nota-topico que resuma as {len(notas)} notas abaixo (tema: '{tema}'). "
                     "Use SO o que esta nas notas (nao invente, nao pesquise na web). Corpo de 5 a 12 linhas: o que une as notas, os "
                     "pontos principais, contradicoes ou lacunas, e um [[titulo]] para cada nota. Formato: '## Notas' e uma unica "
                     "'### Nota: <titulo curto do topico>' com 'Tags:'.\n" + spotlight.REGRA + "\n"
                     + spotlight.envolver("NOTAS", blocos, cod))[:3990]
        projeto = next(iter(self.servico.listar(T.Projeto, nome=PROJETO)), None)
        if projeto is None:
            projeto, _ = self.servico.criar_projeto(ProjetoIn(nome=PROJETO, descricao="Estudos para alimentar o segundo cerebro"))
        objetivo, _ = self.servico.criar_objetivo(ObjetivoIn(projeto_id=projeto["id"], titulo=f"Topico: {tema}"[:200], prioridade=4,
                                                             criterios_sucesso=["Nota-topico candidata criada e ligada as notas"]))
        tarefa, _ = self.servico.criar_tarefa(TarefaIn(
            objetivo_id=objetivo["id"], titulo=f"Resumo em topico: {tema}"[:200], descricao=descricao, modo="estudo", especialidade="estudo",
            criterios_aceite=["Uma nota-topico curta, fiel as notas e com [[titulo]] de cada uma"],
            entrada={"estudo": {"tipo": "resumo", "alvo": tema[:200], "namespace": namespace, "assunto": f"Topico: {tema}"[:200],
                                "pastas": [], "memorias": [m["id"] for m in notas]}}))
        for destino in (EstadoTarefa.CLASSIFICADA, EstadoTarefa.PREPARADA):
            tarefa, _ = self.servico.transicionar(tarefa["id"], TransicaoIn(para=destino, expected_version=tarefa["versao_estado"]))
        execucao = None
        if executar:
            execucao = self.servico.criar_execucao(tarefa["id"])
            self.servico.iniciar_execucao(execucao["id"], "sistema:organizacao")
        return {"tarefa_id": tarefa["id"], "execucao_id": execucao["id"] if execucao else None, "notas": len(notas)}

    def _criar_topico_resumo(self, tarefa: dict[str, Any], cfg: dict[str, Any], notas: list[NotaEstudo]) -> dict[str, Any]:
        ns = cfg.get("namespace") or "pessoal/estudos"
        if not notas:
            return {"raiz": None, "criadas": [], "puladas": 0, "ligacoes": 0}
        n = notas[0]
        with self.memoria.repo.leitura() as t:
            ocupado = any(m["titulo"].casefold() == n.titulo.casefold() for m in t.listar(T.Memoria, namespace=ns, limite=5000))
        titulo = (f"{n.titulo} (tópico)" if ocupado else n.titulo)[:200]
        topico = self.memoria.criar(self.principal, MemoriaIn(
            tipo="estrutural", titulo=titulo, resumo=next((x.strip(" -*") for x in n.corpo.splitlines() if x.strip()), titulo)[:300],
            conteudo=n.corpo, namespace=ns, tags=["topico", *[x for x in [cfg.get("alvo", "")] if x], *n.tags][:15],
            fonte=FonteIn(tipo="execucao", caminho=f"tarefas/{tarefa['id']}"), refs=[f"tarefa:{tarefa['id']}"], confianca=0.3), "agente:estudo")
        ligacoes = 0
        for mid in cfg.get("memorias") or []:
            try:
                self.grafo.ligar(self.principal, mid, topico["id"], "SUBTOPICO_DE", "resumida no topico", ator="agente:estudo")
                ligacoes += 1
            except ErroDominio:  # nota removida/inativa depois do pedido: segue sem ela
                pass
        return {"raiz": topico["id"], "criadas": [topico["id"]], "puladas": max(0, len(notas) - 1), "ligacoes": ligacoes}

    # ------------------------------------------------------------------ ganchos pos-execucao
    def _tarefa_de(self, execucao_id: str) -> dict[str, Any] | None:
        with self.servico.repo.leitura() as t:
            ex = t.obter(T.Execucao, execucao_id)
            return t.obter(T.Tarefa, ex["tarefa_id"]) if ex else None

    def ao_finalizar(self, execucao_id: str, res: ResultadoAgente) -> None:
        if res.estado != "concluida":
            return
        tarefa = self._tarefa_de(execucao_id)
        if tarefa is None or tarefa["estado"] != "concluida":
            return
        if tarefa["modo"] == "estudo":
            self.criar_notas(tarefa, res)
        elif self.registrar_aprendizados and not res.mock:
            self.registrar(tarefa, res)

    def _topico(self, namespace: str, titulo: str, resumo: str, tags: list[str]) -> str:
        """Nota-indice do assunto (cria se nao existir): raiz dos subtopicos."""
        with self.memoria.repo.leitura() as t:
            achada = next((m for m in t.listar(T.Memoria, namespace=namespace, titulo=titulo, limite=5)
                           if m["estado"] not in ("revogado", "substituido")), None)
        if achada:
            return achada["id"]
        m = self.memoria.criar(self.principal, MemoriaIn(tipo="estrutural", titulo=titulo[:200], resumo=resumo[:300], conteudo=resumo,
                                                         namespace=namespace, tags=tags[:10], fonte=FonteIn(tipo="execucao")), "forja")
        return m["id"]

    def criar_notas(self, tarefa: dict[str, Any], res: ResultadoAgente) -> dict[str, Any]:
        cfg = (tarefa.get("entrada") or {}).get("estudo") or {}
        ns = cfg.get("namespace") or "pessoal/estudos"
        texto = next((a.conteudo for a in res.artefatos if a.nome.endswith(".md")), "") or "\n".join(m.conteudo for m in res.mensagens)
        notas = extrair_notas(texto)
        if cfg.get("tipo") == "resumo":  # 9.12: uma nota-topico sobre notas existentes
            r = self._criar_topico_resumo(tarefa, cfg, notas)
            with self.servico.repo.escrita() as t:
                t.emitir_evento("estudo.topico_criado", self.servico._ts(), {"tarefa_id": tarefa["id"], "topico": r["raiz"],
                                                                           "ligacoes": r["ligacoes"]})
            return r
        raiz = self._topico(ns, f"Estudo: {cfg.get('assunto') or tarefa['titulo']}",
                            f"Notas do estudo ({cfg.get('tipo')}) '{cfg.get('alvo', '')}'. Subtopicos ligados a esta nota.",
                            ["estudo", cfg.get("tipo") or "topico"])
        criadas: dict[str, str] = {}
        puladas = 0
        with self.memoria.repo.leitura() as t:
            existentes = {m["titulo"].casefold() for m in t.listar(T.Memoria, namespace=ns, limite=5000)}
        for n in notas:
            if n.titulo.casefold() in existentes or n.titulo.casefold() in criadas:
                puladas += 1
                continue
            fontes = [f for f in n.fontes if f]
            corpo = n.corpo + (("\n\nFontes: " + "; ".join(fontes)) if fontes else "")
            fonte = FonteIn(tipo="documento", repositorio=(Path(cfg["alvo"]).name if cfg.get("tipo") == "pasta" else "web")[:200])
            m = self.memoria.criar(self.principal, MemoriaIn(
                tipo="semantica", titulo=n.titulo, resumo=next((x.strip(" -*") for x in n.corpo.splitlines() if x.strip()), n.titulo)[:300],
                conteudo=corpo, namespace=ns, tags=["estudo", *n.tags][:15], fonte=fonte,
                refs=[f"tarefa:{tarefa['id']}", *[f"fonte:{f}"[:200] for f in fontes[:5]]], confianca=0.3), "agente:estudo")
            criadas[n.titulo.casefold()] = m["id"]
        ligacoes = 0
        for n in notas:
            mid = criadas.get(n.titulo.casefold())
            if not mid:
                continue
            pai = criadas.get(n.pai.casefold()) if n.pai else None
            if pai is None and n.pai:  # pai fora do estudo: nota existente (inclusive a base da Forja)
                pai = self._buscar_titulo(n.pai)
            try:
                self.grafo.ligar(self.principal, mid, pai or raiz, "SUBTOPICO_DE", ator="agente:estudo")
                ligacoes += 1
            except ErroDominio:
                pass
        with self.servico.repo.escrita() as t:
            t.emitir_evento("estudo.notas_criadas", self.servico._ts(), {"tarefa_id": tarefa["id"], "notas": len(criadas),
                                                                           "puladas": puladas, "ligacoes": ligacoes})
        return {"raiz": raiz, "criadas": list(criadas.values()), "puladas": puladas, "ligacoes": ligacoes}

    def _buscar_titulo(self, titulo: str) -> str | None:
        with self.memoria.repo.leitura() as t:
            for m in t.listar(T.Memoria, titulo=titulo, limite=10):
                if self.principal.pode(m["namespace"]) and m["estado"] not in ("revogado", "substituido"):
                    return m["id"]
        return None

    def registrar(self, tarefa: dict[str, Any], res: ResultadoAgente) -> dict[str, Any] | None:
        """Decisoes, premissas e evidencias da tarefa como nota CANDIDATA 'decisoria', ligada ao topico do projeto."""
        secoes = {m.tipo: m.conteudo for m in res.mensagens}
        with self.servico.repo.leitura() as t:
            projeto = t.obter(T.Projeto, tarefa["projeto_id"]) or {"nome": "geral"}
            respostas = [m["conteudo"] for m in t.listar(T.Mensagem, tarefa_id=tarefa["id"], papel="operador", limite=50)]
        partes = []
        for chave, rotulo in (("entendimento", "Entendimento"), ("plano", "Plano"), ("premissas", "Premissas"),
                              ("evidencias", "Evidências"), ("verificacao", "Verificação da Forja")):
            if secoes.get(chave):
                partes.append(f"## {rotulo}\n{secoes[chave][:1500]}")
        if respostas:
            partes.append("## Decisões do desenvolvedor\n" + "\n".join(f"- {sanitizar_texto(r)[:400]}" for r in respostas[-5:]))
        if res.pendencias:
            partes.append("## Pendências\n" + "\n".join(f"- {p[:200]}" for p in res.pendencias[:8]))
        partes.append("## Evidências registradas\n" + "\n".join(f"- {e.tipo}{' (simulada)' if e.simulada else ''}: {e.resumo[:200]}"
                                                                for e in res.evidencias[:6]))
        if not partes:
            return None
        ns = f"pessoal/projetos/{_slug(projeto['nome'])}"
        ref = f"tarefa:{tarefa['id']}"
        with self.memoria.repo.leitura() as t:
            if any(ref in (m["refs"] or []) for m in t.listar(T.Memoria, namespace=ns, limite=2000)):
                return None  # idempotente: uma retomada concluida nao duplica o registro
        topico = self._topico(ns, f"Projeto: {projeto['nome']}"[:200], f"Decisões, aprendizados e registros do projeto {projeto['nome']}.",
                              ["projeto", "registro"])
        m = self.memoria.criar(self.principal, MemoriaIn(
            tipo="decisoria", titulo=f"Registro: {tarefa['titulo']}"[:200], resumo=(secoes.get("entendimento") or tarefa["titulo"])[:300],
            conteudo="\n\n".join(partes)[:20_000], namespace=ns, tags=["registro", tarefa["modo"], tarefa["especialidade"]][:10],
            fonte=FonteIn(tipo="execucao", caminho=f"tarefas/{tarefa['id']}"), refs=[ref], confianca=0.2), "forja")
        try:
            self.grafo.ligar(self.principal, m["id"], topico, "SUBTOPICO_DE", ator="forja")
        except ErroDominio:
            pass
        return m
