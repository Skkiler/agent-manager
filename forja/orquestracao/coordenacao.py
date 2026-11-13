"""Master (HEAD) e sub-masters: voce conversa com o master; ele entende, decide quais tarefas (e sub-masters) criar e repassa.

Desenho (ADR-023):
- O master e um coordenador LLM (parte 'coordenacao', perfil Kiro 'forja-coordenador', sem ferramentas). Cada fala sua vira um
  TURNO dele: uma tarefa interna com o estado atual (montado sem LLM) e a conversa recente. Ele responde com '## Resposta' (para
  voce) e '## Ações' (JSON tipado). Quem DECIDE e o orquestrador: valida cada acao (limites, modos permitidos pela autonomia,
  projeto) antes de criar qualquer coisa. O master nunca aprova acao sensivel nem executa trabalho.
- Sub-master: um coordenador por projeto, criado SO quando o pedido envolve 2+ projetos (ou ja ha sub-master ativo noutro
  projeto). Faz o papel do master dentro do projeto dele, com orcamento proprio. Profundidade maxima 2 (master -> sub-masters ->
  tarefas): sub-master nao cria sub-master.
- Retorno: cada tarefa criada por um coordenador avisa a conversa dele (concluida, precisa de voce, falhou). Quando TODAS as
  tarefas de um lote terminam, o coordenador ganha UM turno de consolidacao (dentro do orcamento) e responde; o sub-master
  reporta ao master. Decisoes que so voce pode tomar continuam na conversa da propria tarefa (o master avisa onde).
- Custo: multiagente gasta varias vezes mais tokens; por isso o protocolo manda NAO dividir quando uma tarefa basta.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from forja.adapters.sqlite import tabelas as T
from forja.dominio.contratos import ObjetivoIn, Politicas, ProjetoIn, ResultadoAgente, TarefaIn, TransicaoIn
from forja.dominio.erros import Conflito, ErroDominio, NaoEncontrado, ValidacaoDominio
from forja.dominio.estados import EstadoTarefa
from forja.dominio.tempo import Relogio, RelogioSistema, iso
from forja.observabilidade.sanitizar import redigir_segredos, sanitizar_texto
from forja.seguranca import spotlight

log = logging.getLogger("forja.coordenacao")
ET = EstadoTarefa
PROJETO_INTERNO = "forja-coordenacao"
MAX_ACOES, MAX_ABERTAS, MAX_SUBMASTERS = 6, 12, 8
ORCAMENTO = {"master": 40, "submaster": 15}  # turnos de coordenador
TERMINAIS = {ET.CONCLUIDA.value, ET.FALHOU.value, ET.CANCELADA.value, ET.EXPIRADA.value}
_JSON = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_RESPOSTA = re.compile(r"^##\s*Resposta\s*$(.*?)(?=^##\s|\Z)", re.DOTALL | re.MULTILINE | re.IGNORECASE)

PROTOCOLO = (
    "Voce e o {papel} da Forja, um orquestrador de agentes de desenvolvimento. Voce NAO executa trabalho: entende o pedido, decide "
    "o que fazer e cria tarefas para agentes especialistas. Responda SEMPRE com estas duas secoes:\n"
    "## Resposta\n(para o usuario, em portugues, curto: o que entendeu e o que vai acontecer; pergunte so se faltar algo essencial)\n"
    "## Ações\n```json\n{{\"acoes\": [ ... ]}}\n```\n"
    "Acoes possiveis (ate 6; lista vazia se nao houver o que criar):\n"
    "- {{\"tipo\": \"criar_tarefa\", \"projeto\": \"<nome>\", \"titulo\": \"...\", \"descricao\": \"...\", \"modo\": \"analise|documentacao|"
    "alteracao_codigo|verificacao\", \"criterios\": [\"criterio verificavel\", ...], \"complexidade\": \"simples|normal|complexa\" (opcional), "
    "\"depende_de\": [indices de acoes anteriores desta lista] (opcional)}}\n"
    "{submaster}"
    "Regras: UMA tarefa bem descrita e melhor que varias pequenas; divida so quando as partes forem independentes. Criterios "
    "objetivos ('testes passam', 'arquivo: caminho'). Modos permitidos agora: {modos}. Nao invente arquivos ou fatos que nao estao no "
    "estado abaixo. Quando o lote terminar voce recebe os resultados para consolidar.\n"
)
SUBMASTER_ACAO = ("- {\"tipo\": \"criar_submaster\", \"projeto\": \"<nome>\", \"objetivo\": \"...\"}  (SO quando o pedido envolver 2 ou "
                  "mais projetos diferentes: cada projeto ganha um coordenador proprio)\n")


class AcaoTarefa(BaseModel):
    model_config = ConfigDict(extra="ignore")
    tipo: Literal["criar_tarefa"]
    projeto: str = Field(min_length=1, max_length=200)
    titulo: str = Field(min_length=3, max_length=200)
    descricao: str = Field("", max_length=3500)
    modo: Literal["analise", "documentacao", "alteracao_codigo", "verificacao"] = "analise"
    criterios: list[str] = Field(default_factory=list, max_length=10)
    complexidade: Literal["", "simples", "normal", "complexa"] = ""
    depende_de: list[int] = Field(default_factory=list, max_length=6)


class AcaoSubmaster(BaseModel):
    model_config = ConfigDict(extra="ignore")
    tipo: Literal["criar_submaster"]
    projeto: str = Field(min_length=1, max_length=200)
    objetivo: str = Field(min_length=3, max_length=3500)


def extrair(texto: str) -> tuple[str, list[dict[str, Any]], list[str]]:
    """(resposta para o usuario, acoes brutas, avisos de formato). Tolerante: sem JSON valido = nenhuma acao."""
    m = _RESPOSTA.search(texto or "")
    resposta = (m.group(1) if m else texto or "").strip()
    resposta = _JSON.sub("", resposta).strip()[:6000]
    blocos = _JSON.findall(texto or "")
    if not blocos:
        return resposta, [], []
    try:
        dados = json.loads(blocos[-1])
    except ValueError:
        return resposta, [], ["o bloco de acoes nao era JSON valido; nada foi criado"]
    acoes = dados.get("acoes") if isinstance(dados, dict) else None
    return resposta, [a for a in acoes if isinstance(a, dict)] if isinstance(acoes, list) else [], []


class CoordenacaoServico:
    def __init__(self, servico: Any, perfil_de: Any = None, relogio: Relogio | None = None) -> None:
        self.servico = servico
        self.perfil_de = perfil_de  # () -> PerfilTrabalho (modos permitidos pela autonomia)
        self.relogio = relogio or RelogioSistema()
        self.executar = True  # preferencia 'master_executar': True = tarefas criadas ja executam; False = ficam prontas
        self.consolidar = True  # turno de consolidacao quando o lote termina

    # ------------------------------------------------------------------ coordenadores e conversa
    def _ts(self) -> str:
        return iso(self.relogio.agora())

    def master(self) -> dict[str, Any]:
        with self.servico.repo.escrita() as t:
            ativos = t.listar(T.Coordenacao, tipo="master", estado="ativo", limite=1)
            if ativos:
                return ativos[0]
            agora = self._ts()
            return t.inserir(T.Coordenacao, id=f"COORD-{novo()}", tipo="master", pai_id=None, projeto_id=None, titulo="Master", objetivo="", estado="ativo", chamadas_usadas=0,
                             max_chamadas=ORCAMENTO["master"], criado_em=agora, atualizado_em=agora)

    def obter(self, coord_id: str) -> dict[str, Any]:
        with self.servico.repo.leitura() as t:
            c = t.obter(T.Coordenacao, coord_id)
        if c is None:
            raise NaoEncontrado(f"Coordenador {coord_id} nao encontrado.")
        return c

    def _msg(self, coord_id: str, papel: str, conteudo: str, dados: dict | None = None, tarefa_id: str | None = None) -> dict[str, Any]:
        with self.servico.repo.escrita() as t:
            m = t.inserir(T.MensagemCoordenacao, id=f"MC-{novo()}", coordenacao_id=coord_id, papel=papel,
                          conteudo=sanitizar_texto(redigir_segredos(conteudo))[:8000], dados=dados, tarefa_id=tarefa_id, criado_em=self._ts())
            t.emitir_evento("coordenacao.mensagem", self._ts(), {"coordenacao_id": coord_id, "papel": papel}, tarefa_id=tarefa_id)
        return m

    def conversa(self, coord_id: str, limite: int = 200) -> list[dict[str, Any]]:
        with self.servico.repo.leitura() as t:
            return t.listar(T.MensagemCoordenacao, ordem=T.MensagemCoordenacao.criado_em, coordenacao_id=coord_id, limite=limite)

    def painel(self) -> dict[str, Any]:
        m = self.master()
        with self.servico.repo.leitura() as t:
            todos = t.listar(T.Coordenacao, limite=500)
            tarefas = [x for x in t.listar(T.Tarefa, limite=5000) if (x.get("entrada") or {}).get("coordenacao_id")]
        por_coord: dict[str, list[dict]] = {}
        for x in tarefas:
            por_coord.setdefault(x["entrada"]["coordenacao_id"], []).append(
                {"id": x["id"], "titulo": x["titulo"], "estado": x["estado"], "modo": x["modo"]})
        filhos = [c for c in todos if c["pai_id"] == m["id"]]
        return {"master": {**m, "tarefas": por_coord.get(m["id"], [])},
                "submasters": [{**c, "tarefas": por_coord.get(c["id"], [])} for c in filhos],
                "conversa": self.conversa(m["id"])}

    def encerrar(self, coord_id: str) -> dict[str, Any]:
        c = self.obter(coord_id)
        with self.servico.repo.escrita() as t:
            t.atualizar(T.Coordenacao, coord_id, estado="encerrado", atualizado_em=self._ts())
        self._msg(c["pai_id"] or coord_id, "sistema", f"{c['titulo']} encerrado.")
        return {**c, "estado": "encerrado"}

    def falar(self, texto: str, coord_id: str | None = None, ator: str = "operador") -> dict[str, Any]:
        """Uma fala do usuario: registra e dispara um turno do coordenador (master por padrao)."""
        c = self.obter(coord_id) if coord_id else self.master()
        if c["estado"] != "ativo":
            raise Conflito("Este coordenador foi encerrado.")
        texto = (texto or "").strip()
        if not texto:
            raise ValidacaoDominio("Escreva o pedido.")
        self._msg(c["id"], "usuario", texto[:8000])
        turno = self._turno(c, "pedido", texto)
        return {"coordenacao_id": c["id"], **turno}

    # ------------------------------------------------------------------ turno do coordenador (tarefa interna)
    def _estado(self, c: dict[str, Any]) -> str:
        """Estado atual montado SEM LLM: so o que o coordenador precisa para decidir (compacto)."""
        linhas = []
        with self.servico.repo.leitura() as t:
            projetos = {p["id"]: p for p in t.listar(T.Projeto, limite=500) if p["nome"] not in (PROJETO_INTERNO, "forja-estudos")}
            tarefas = [x for x in t.listar(T.Tarefa, limite=5000) if (x.get("entrada") or {}).get("coordenacao_id") == c["id"]]
            filhos = [x for x in t.listar(T.Coordenacao, pai_id=c["id"], limite=50)]
        if c["tipo"] == "master":
            nomes = [p["nome"] for p in projetos.values()][:30]
            linhas.append("Projetos existentes: " + (", ".join(nomes) if nomes else "nenhum (crie pelo nome)"))
            for f in filhos:
                linhas.append(f"Sub-master '{f['titulo']}' ({f['estado']})")
        else:
            p = projetos.get(c["projeto_id"] or "")
            linhas.append(f"Voce coordena SO o projeto '{p['nome'] if p else c['titulo']}'. Objetivo: {c['objetivo'][:800]}")
            if p and p.get("pastas"):
                linhas.append("Pastas do projeto: " + ", ".join(f"{x['papel']}:{x['caminho'].rsplit(chr(92), 1)[-1].rsplit('/', 1)[-1]}"
                                                               for x in p["pastas"][:8]))
        for x in tarefas[-15:]:
            linhas.append(f"- tarefa {x['id']} [{x['estado']}] {x['titulo'][:90]}")
        return "\n".join(linhas)[:2500]

    def _turno(self, c: dict[str, Any], tipo: Literal["pedido", "consolidar"], texto: str) -> dict[str, Any]:
        if c["chamadas_usadas"] >= c["max_chamadas"]:
            self._msg(c["id"], "sistema", f"Orçamento de turnos do {c['titulo']} esgotado ({c['max_chamadas']}). Encerre e abra outro, "
                                          "ou fale direto com as tarefas.")
            return {"tarefa_id": None, "execucao_id": None, "recusado": "orcamento"}
        perfil = self.perfil_de() if self.perfil_de else None
        modos = sorted((perfil.modos if perfil else {"analise", "documentacao"}) - {"estudo"})
        papel = "MASTER" if c["tipo"] == "master" else f"SUB-MASTER do projeto '{c['titulo']}'"
        prot = PROTOCOLO.format(papel=papel, modos=", ".join(modos), submaster=SUBMASTER_ACAO if c["tipo"] == "master" else "")
        recentes = [m for m in self.conversa(c["id"])[-8:] if m["papel"] in ("usuario", "master", "submaster", "sistema")]
        historico = "\n".join(f"{m['papel']}: {' '.join(m['conteudo'].split())[:300]}" for m in recentes[:-1] if tipo == "pedido") or "(inicio)"
        cod = spotlight.codigo()
        corpo = (prot + "\nEstado atual (dados):\n" + spotlight.envolver("ESTADO", self._estado(c), cod) + "\nConversa recente:\n"
                 + spotlight.envolver("CONVERSA", historico, cod) + "\n"
                 + (f"Pedido do usuario:\n{texto}" if tipo == "pedido" else f"O lote terminou. Resultados:\n{texto}\nConsolide para o "
                    "usuario em '## Resposta' e crie novas tarefas SO se forem necessarias para concluir o pedido."))
        s = self.servico
        projeto = next(iter(s.listar(T.Projeto, nome=PROJETO_INTERNO)), None) or s.criar_projeto(
            ProjetoIn(nome=PROJETO_INTERNO, descricao="Turnos internos do master e dos sub-masters"))[0]
        objetivo = next(iter(s.listar(T.Objetivo, projeto_id=projeto["id"], titulo=c["titulo"][:200])), None) or s.criar_objetivo(
            ObjetivoIn(projeto_id=projeto["id"], titulo=c["titulo"][:200], prioridade=2))[0]
        tarefa, _ = s.criar_tarefa(TarefaIn(
            objetivo_id=objetivo["id"], titulo=f"{c['titulo']}: {'consolidar' if tipo == 'consolidar' else texto[:60]}"[:200],
            descricao=f"Turno do coordenador {c['id']} ({tipo}).", modo="analise", especialidade="coordenacao",
            criterios_aceite=["Resposta ao usuario e acoes validas"], politicas=Politicas(contexto="nenhum"),
            entrada={"coordenacao": {"id": c["id"], "turno": tipo, "prompt": corpo[:15000]}}))
        for destino in (ET.CLASSIFICADA, ET.PREPARADA):
            tarefa, _ = s.transicionar(tarefa["id"], TransicaoIn(para=destino, expected_version=tarefa["versao_estado"]), ator="sistema:coordenacao")
        with s.repo.escrita() as t:
            t.atualizar(T.Coordenacao, c["id"], chamadas_usadas=c["chamadas_usadas"] + 1, atualizado_em=self._ts())
        ex = s.criar_execucao(tarefa["id"])
        s.iniciar_execucao(ex["id"], ator="sistema:coordenacao")
        return {"tarefa_id": tarefa["id"], "execucao_id": ex["id"]}

    # ------------------------------------------------------------------ gancho pos-execucao
    def ao_finalizar(self, execucao_id: str, res: ResultadoAgente) -> None:
        try:
            s = self.servico
            ex = s.obter(T.Execucao, execucao_id)
            tarefa = s.obter(T.Tarefa, ex["tarefa_id"])
            entrada = tarefa.get("entrada") or {}
            if entrada.get("coordenacao"):
                self._processar_turno(entrada["coordenacao"], tarefa, res)
            elif entrada.get("coordenacao_id"):
                self._retorno_de_tarefa(entrada["coordenacao_id"], tarefa, res)
        except Exception:  # noqa: BLE001 - ganchos nunca alteram o resultado da execucao
            log.exception("falha na coordenacao", extra={"execucao_id": execucao_id})

    def _processar_turno(self, info: dict[str, Any], tarefa: dict[str, Any], res: ResultadoAgente) -> None:
        c = self.obter(info["id"])
        texto = next((a.conteudo for a in res.artefatos if a.nome.endswith(".md")), "") or "\n".join(m.conteudo for m in res.mensagens)
        if res.estado not in ("concluida",) or not texto.strip():
            self._msg(c["id"], "sistema", f"O {c['titulo']} não conseguiu responder agora ({res.estado}): {res.resumo[:200]}",
                      tarefa_id=tarefa["id"])
            return
        resposta, brutas, avisos = extrair(texto)
        criadas, recusadas = self._aplicar(c, brutas)
        papel = "master" if c["tipo"] == "master" else "submaster"
        self._msg(c["id"], papel, resposta or "(sem resposta)", {"criadas": criadas, "recusadas": recusadas + avisos, "simulado": res.mock},
                  tarefa_id=tarefa["id"])
        if c["tipo"] == "submaster" and c["pai_id"]:  # o sub-master reporta ao master (e o master consolida quando todos terminam)
            self._msg(c["pai_id"], "submaster", f"[{c['titulo']}] {resposta[:1500]}")
            if info.get("turno") == "consolidar":
                self._talvez_consolidar(self.obter(c["pai_id"]))

    def _aplicar(self, c: dict[str, Any], brutas: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
        s = self.servico
        criadas: list[dict[str, Any]] = []
        recusadas: list[str] = []
        perfil = self.perfil_de() if self.perfil_de else None
        permitidos = perfil.modos if perfil else frozenset({"analise", "documentacao"})
        with s.repo.leitura() as t:
            abertas = sum(1 for x in t.listar(T.Tarefa, limite=5000)
                          if (x.get("entrada") or {}).get("coordenacao_id") == c["id"] and x["estado"] not in TERMINAIS)
            subs_ativos = [x for x in t.listar(T.Coordenacao, pai_id=c["id"], estado="ativo", limite=50)]
        projetos_no_lote = {str(a.get("projeto", "")).strip().casefold() for a in brutas if a.get("projeto")}
        multiplos = len(projetos_no_lote) >= 2 or bool(subs_ativos)
        ids_por_indice: dict[int, str] = {}
        for i, bruta in enumerate(brutas[:MAX_ACOES]):
            try:
                if bruta.get("tipo") == "criar_submaster":
                    a = AcaoSubmaster.model_validate(bruta)
                    if c["tipo"] != "master":
                        recusadas.append(f"acao {i}: sub-master nao cria sub-master (profundidade maxima 2)")
                        continue
                    if not multiplos:  # um projeto so: vira uma tarefa (mais barato que um coordenador a mais)
                        bruta = {"tipo": "criar_tarefa", "projeto": a.projeto, "titulo": a.objetivo[:120], "descricao": a.objetivo,
                                 "modo": "analise", "criterios": ["objetivo atendido e explicado"], "complexidade": "complexa"}
                    elif len(subs_ativos) >= MAX_SUBMASTERS:
                        recusadas.append(f"acao {i}: limite de {MAX_SUBMASTERS} sub-masters ativos")
                        continue
                    else:
                        criadas.append(self._criar_submaster(c, a))
                        continue
                a = AcaoTarefa.model_validate(bruta)
                if c["tipo"] == "submaster":  # sub-master so age no proprio projeto
                    a.projeto = self._nome_projeto(c["projeto_id"]) or a.projeto
                if a.modo not in permitidos:
                    recusadas.append(f"acao {i}: modo '{a.modo}' nao permitido no nivel de autonomia atual")
                    continue
                if abertas >= MAX_ABERTAS:
                    recusadas.append(f"acao {i}: limite de {MAX_ABERTAS} tarefas abertas deste coordenador")
                    continue
                deps = [ids_por_indice[d] for d in a.depende_de if d in ids_por_indice]
                tarefa = self._criar_tarefa(c, a, deps)
                ids_por_indice[i] = tarefa["id"]
                abertas += 1
                criadas.append({"tipo": "tarefa", "id": tarefa["id"], "titulo": tarefa["titulo"]})
            except (ValidationError, ErroDominio) as e:
                recusadas.append(f"acao {i}: {getattr(e, 'mensagem', None) or 'formato invalido'}"[:200])
        for item in criadas:
            if item["tipo"] == "tarefa" and self.executar:
                self._executar_se_pronta(item["id"])
        return criadas, recusadas

    def _nome_projeto(self, projeto_id: str | None) -> str | None:
        if not projeto_id:
            return None
        with self.servico.repo.leitura() as t:
            p = t.obter(T.Projeto, projeto_id)
        return p["nome"] if p else None

    def _projeto(self, nome: str) -> dict[str, Any]:
        s = self.servico
        nome = nome.strip()[:200]
        if nome.casefold() in (PROJETO_INTERNO, "forja-estudos"):
            raise ValidacaoDominio("projeto reservado")
        existente = next((p for p in s.listar(T.Projeto, limite=500) if p["nome"].casefold() == nome.casefold()), None)
        return existente or s.criar_projeto(ProjetoIn(nome=nome, descricao="criado pelo master"))[0]

    def _criar_tarefa(self, c: dict[str, Any], a: AcaoTarefa, deps: list[str]) -> dict[str, Any]:
        s = self.servico
        p = self._projeto(a.projeto)
        objetivo = next(iter(s.listar(T.Objetivo, projeto_id=p["id"], titulo=f"Pedido ao {c['titulo']}"[:200])), None) or s.criar_objetivo(
            ObjetivoIn(projeto_id=p["id"], titulo=f"Pedido ao {c['titulo']}"[:200], prioridade=3))[0]
        tarefa, _ = s.criar_tarefa(TarefaIn(
            objetivo_id=objetivo["id"], titulo=a.titulo, descricao=a.descricao, modo=a.modo, especialidade="geral",
            criterios_aceite=[x[:200] for x in a.criterios if x.strip()] or ["entregar o pedido com evidencias"], dependencias=deps,
            politicas=Politicas(complexidade=a.complexidade), entrada={"coordenacao_id": c["id"]}))
        for destino in (ET.CLASSIFICADA, ET.PREPARADA):
            tarefa, _ = s.transicionar(tarefa["id"], TransicaoIn(para=destino, expected_version=tarefa["versao_estado"]), ator="sistema:coordenacao")
        return tarefa

    def _executar_se_pronta(self, tarefa_id: str) -> None:
        s = self.servico
        try:
            if s.obter(T.Tarefa, tarefa_id)["estado"] == ET.PRONTA.value:
                ex = s.criar_execucao(tarefa_id)
                s.iniciar_execucao(ex["id"], ator="sistema:coordenacao")
        except ErroDominio as e:
            log.info("tarefa do coordenador nao iniciou: %s", e.codigo)

    def _criar_submaster(self, master: dict[str, Any], a: AcaoSubmaster) -> dict[str, Any]:
        p = self._projeto(a.projeto)
        agora = self._ts()
        with self.servico.repo.escrita() as t:
            ativo = next((x for x in t.listar(T.Coordenacao, pai_id=master["id"], estado="ativo", limite=50) if x["projeto_id"] == p["id"]), None)
            sub = ativo or t.inserir(T.Coordenacao, id=f"COORD-{novo()}", tipo="submaster", pai_id=master["id"], projeto_id=p["id"],
                                     titulo=f"Sub-master {p['nome']}"[:200], objetivo=a.objetivo, estado="ativo", chamadas_usadas=0,
                                     max_chamadas=ORCAMENTO["submaster"], criado_em=agora, atualizado_em=agora)
        self._msg(sub["id"], "master", a.objetivo)
        self._turno(self.obter(sub["id"]), "pedido", a.objetivo)
        return {"tipo": "submaster", "id": sub["id"], "titulo": sub["titulo"]}

    def publicar_status(self, tarefa_id: str, texto: str, origem: str) -> None:
        """Relato de status (StatusServico) de uma tarefa criada por um coordenador vai tambem para a conversa dele."""
        with self.servico.repo.leitura() as t:
            tarefa = t.obter(T.Tarefa, tarefa_id)
        coord = ((tarefa or {}).get("entrada") or {}).get("coordenacao_id")
        if coord and origem == "modelo":  # o deterministico ja chega como mensagem do sistema (retorno da tarefa)
            self._msg(coord, "status", texto, {"origem": origem}, tarefa_id=tarefa_id)

    # ------------------------------------------------------------------ retorno dos trabalhadores
    def _retorno_de_tarefa(self, coord_id: str, tarefa: dict[str, Any], res: ResultadoAgente) -> None:
        estado = self.servico.obter(T.Tarefa, tarefa["id"])["estado"]
        icone = {"concluida": "✓ Concluída", "bloqueada": "⚠ Precisa de você", "falhou": "✗ Falhou", "cancelada": "■ Cancelada",
                 "expirada": "⌛ Expirou"}.get(estado, estado)
        extra = " Responda na conversa da tarefa." if estado == "bloqueada" else ""
        self._msg(coord_id, "sistema", f"{icone}: {tarefa['titulo']} — {res.resumo[:240]}{extra}", {"estado": estado}, tarefa_id=tarefa["id"])
        self._talvez_consolidar(self.obter(coord_id))

    def _talvez_consolidar(self, c: dict[str, Any]) -> None:
        """Lote terminado (todas as tarefas e sub-masters do coordenador parados) -> UM turno de consolidacao."""
        if not self.consolidar or c["estado"] != "ativo":
            return
        with self.servico.repo.leitura() as t:
            tarefas = [x for x in t.listar(T.Tarefa, limite=5000) if (x.get("entrada") or {}).get("coordenacao_id") == c["id"]]
            subs = t.listar(T.Coordenacao, pai_id=c["id"], estado="ativo", limite=50)
            msgs = t.listar(T.MensagemCoordenacao, ordem=T.MensagemCoordenacao.criado_em, coordenacao_id=c["id"], limite=500)
        if (not tarefas and not subs) or any(x["estado"] not in TERMINAIS for x in tarefas):
            return
        if any(not self._sub_consolidou(sb["id"]) for sb in subs):
            return
        ja = {tid for m in msgs if (m.get("dados") or {}).get("consolidou") for tid in m["dados"]["consolidou"]}
        novas = [x for x in tarefas if x["id"] not in ja]
        novos_subs = [sb for sb in subs if sb["id"] not in ja]
        if not (novas or novos_subs):
            return
        linhas = [f"- {x['titulo'][:100]}: {x['estado']} ({(x['motivo_estado'] or '')[:160]})" for x in novas]
        for sb in novos_subs:
            ultima = next((m["conteudo"] for m in reversed(msgs) if m["papel"] == "submaster" and m["conteudo"].startswith(f"[{sb['titulo']}]")), "")
            linhas.append(f"- {sb['titulo']}: {ultima[:600] or 'sem relato'}")
        self._msg(c["id"], "sistema", f"Lote terminado: {len(linhas)} item(ns). Consolidando.",
                  {"consolidou": [x["id"] for x in novas] + [sb["id"] for sb in novos_subs]})
        self._turno(c, "consolidar", "\n".join(linhas)[:3000])

    def _sub_consolidou(self, sub_id: str) -> bool:
        """O sub-master terminou: tarefas paradas e ja RESPONDEU ao seu turno de consolidacao."""
        with self.servico.repo.leitura() as t:
            tarefas = [x for x in t.listar(T.Tarefa, limite=5000) if (x.get("entrada") or {}).get("coordenacao_id") == sub_id]
            msgs = t.listar(T.MensagemCoordenacao, ordem=T.MensagemCoordenacao.criado_em, coordenacao_id=sub_id, limite=500)
        if any(x["estado"] not in TERMINAIS for x in tarefas):
            return False
        marcos = [i for i, m in enumerate(msgs) if (m.get("dados") or {}).get("consolidou")]
        return bool(marcos) and any(m["papel"] == "submaster" for m in msgs[marcos[-1] + 1:])


def novo() -> str:
    import uuid

    return uuid.uuid4().hex[:12]
