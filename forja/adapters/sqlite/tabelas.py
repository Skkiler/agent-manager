"""Tabelas SQLAlchemy (persistencia interna). Datas em ISO-8601 UTC (texto)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Projeto(Base):
    __tablename__ = "projeto"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    nome: Mapped[str] = mapped_column(String(200), unique=True)
    descricao: Mapped[str] = mapped_column(Text, default="")
    estado: Mapped[str] = mapped_column(String(32), default="ativo")
    criado_em: Mapped[str] = mapped_column(String(40))
    # [{caminho, papel}] papel: trabalho (agente le e altera, conforme o nivel de autonomia) | consulta (so leitura)
    pastas: Mapped[Any] = mapped_column(JSON, default=list, server_default="[]")
    versao: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class Objetivo(Base):
    __tablename__ = "objetivo"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    projeto_id: Mapped[str] = mapped_column(ForeignKey("projeto.id"), index=True)
    titulo: Mapped[str] = mapped_column(String(200))
    descricao: Mapped[str] = mapped_column(Text, default="")
    prioridade: Mapped[int] = mapped_column(Integer, default=3)
    criterios_sucesso: Mapped[Any] = mapped_column(JSON)
    orcamento: Mapped[Any] = mapped_column(JSON)
    criado_em: Mapped[str] = mapped_column(String(40))


class Tarefa(Base):
    __tablename__ = "tarefa"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    objetivo_id: Mapped[str] = mapped_column(ForeignKey("objetivo.id"), index=True)
    projeto_id: Mapped[str] = mapped_column(ForeignKey("projeto.id"), index=True)
    titulo: Mapped[str] = mapped_column(String(200))
    descricao: Mapped[str] = mapped_column(Text, default="")
    criterios_aceite: Mapped[Any] = mapped_column(JSON)
    dependencias: Mapped[Any] = mapped_column(JSON)
    especialidade: Mapped[str] = mapped_column(String(200))
    modo: Mapped[str] = mapped_column(String(32))
    recursos: Mapped[Any] = mapped_column(JSON)
    orcamento: Mapped[Any] = mapped_column(JSON)
    politicas: Mapped[Any] = mapped_column(JSON)
    entrada: Mapped[Any] = mapped_column(JSON)
    contexto_refs: Mapped[Any] = mapped_column(JSON)
    estado: Mapped[str] = mapped_column(String(32), index=True)
    versao_estado: Mapped[int] = mapped_column(Integer, default=1)
    tentativas: Mapped[int] = mapped_column(Integer, default=0)
    motivo_estado: Mapped[str] = mapped_column(Text, default="")
    correlation_id: Mapped[str] = mapped_column(String(64))
    criado_em: Mapped[str] = mapped_column(String(40))
    atualizado_em: Mapped[str] = mapped_column(String(40))


class Execucao(Base):
    __tablename__ = "execucao"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tarefa_id: Mapped[str] = mapped_column(ForeignKey("tarefa.id"), index=True)
    estado: Mapped[str] = mapped_column(String(32), index=True)
    agente_id: Mapped[str] = mapped_column(String(200))
    tentativa: Mapped[int] = mapped_column(Integer, default=0)
    checkpoint: Mapped[Any] = mapped_column(JSON)
    resultado: Mapped[Any] = mapped_column(JSON, nullable=True)
    deadline: Mapped[str | None] = mapped_column(String(40), nullable=True)
    iniciado_em: Mapped[str | None] = mapped_column(String(40), nullable=True)
    finalizado_em: Mapped[str | None] = mapped_column(String(40), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(64))
    criado_em: Mapped[str] = mapped_column(String(40))


class Evento(Base):
    __tablename__ = "evento"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True)
    dedup_key: Mapped[str | None] = mapped_column(String(200), unique=True, nullable=True)
    tipo: Mapped[str] = mapped_column(String(100), index=True)
    ts: Mapped[str] = mapped_column(String(40))
    projeto_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    tarefa_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    execucao_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[Any] = mapped_column(JSON)


class Artefato(Base):
    __tablename__ = "artefato"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tarefa_id: Mapped[str | None] = mapped_column(ForeignKey("tarefa.id"), nullable=True, index=True)
    execucao_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    nome: Mapped[str] = mapped_column(String(200))
    tipo: Mapped[str] = mapped_column(String(32))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    caminho_relativo: Mapped[str] = mapped_column(String(300))
    tamanho: Mapped[int] = mapped_column(Integer)
    origem: Mapped[str] = mapped_column(String(100))
    criado_em: Mapped[str] = mapped_column(String(40))


class Evidencia(Base):
    __tablename__ = "evidencia"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tarefa_id: Mapped[str] = mapped_column(ForeignKey("tarefa.id"), index=True)
    execucao_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tipo: Mapped[str] = mapped_column(String(200))
    resumo: Mapped[str] = mapped_column(Text)
    artefato_id: Mapped[str | None] = mapped_column(ForeignKey("artefato.id"), nullable=True)
    simulada: Mapped[bool] = mapped_column(Boolean, default=False)
    criado_em: Mapped[str] = mapped_column(String(40))


class Aprovacao(Base):
    __tablename__ = "aprovacao"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tarefa_id: Mapped[str] = mapped_column(ForeignKey("tarefa.id"), index=True)
    execucao_id: Mapped[str] = mapped_column(String(64))
    acao: Mapped[str] = mapped_column(String(200))
    justificativa: Mapped[str] = mapped_column(Text, default="")
    estado: Mapped[str] = mapped_column(String(32), index=True)
    decidido_por: Mapped[str | None] = mapped_column(String(100), nullable=True)
    decidido_em: Mapped[str | None] = mapped_column(String(40), nullable=True)
    criado_em: Mapped[str] = mapped_column(String(40))
    # Aprovacao por ACAO (grupo): varios itens, uma decisao, adendo livre do operador.
    origem: Mapped[str] = mapped_column(String(32), default="pre_execucao", server_default="pre_execucao")
    itens: Mapped[Any] = mapped_column(JSON, nullable=True)  # [{id, descricao, categoria, risco, alvos, ...}]
    escopo: Mapped[Any] = mapped_column(JSON, nullable=True)  # {"aprovados": [ids], "lembrar": bool}
    adendo: Mapped[str] = mapped_column(Text, default="", server_default="")


class RecursoLock(Base):
    __tablename__ = "recurso_lock"
    recurso: Mapped[str] = mapped_column(String(300), primary_key=True)
    titular: Mapped[str] = mapped_column(String(64), index=True)
    adquirido_em: Mapped[str] = mapped_column(String(40))
    expira_em: Mapped[str] = mapped_column(String(40))


class Idempotencia(Base):
    __tablename__ = "idempotencia"
    escopo: Mapped[str] = mapped_column(String(200), primary_key=True)
    chave: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int] = mapped_column(Integer)
    resposta: Mapped[Any] = mapped_column(JSON)
    criado_em: Mapped[str] = mapped_column(String(40))


Index("ix_evento_seq_projeto", Evento.projeto_id, Evento.seq)
Index("ix_evento_execucao_seq", Evento.execucao_id, Evento.seq)  # replay da execucao, telemetria e custos


# ============================ Memoria / segundo cerebro (Fase 3) ============================
# Tres grafos NAO misturados: execucao (tarefa/execucao), conhecimento (no/aresta_conhecimento) e codigo
# (arquivo_indexado/simbolo). Tudo e filtrado por `namespace` ANTES da busca.
# Conteudo guardado ja redigido (PII/segredos).


class Memoria(Base):
    __tablename__ = "memoria"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tipo: Mapped[str] = mapped_column(String(32), index=True)
    titulo: Mapped[str] = mapped_column(String(200))
    resumo: Mapped[str] = mapped_column(Text, default="")
    conteudo: Mapped[str] = mapped_column(Text, default="")
    namespace: Mapped[str] = mapped_column(String(200), index=True)
    sensibilidade: Mapped[str] = mapped_column(String(16))
    fonte: Mapped[Any] = mapped_column(JSON)  # {tipo, repositorio, commit, caminho, hash}
    precondicoes: Mapped[Any] = mapped_column(JSON)
    estado: Mapped[str] = mapped_column(String(16), index=True)
    validado_por: Mapped[str | None] = mapped_column(String(200), nullable=True)
    versao: Mapped[int] = mapped_column(Integer, default=1)
    validade_inicio: Mapped[str | None] = mapped_column(String(40), nullable=True)
    validade_fim: Mapped[str | None] = mapped_column(String(40), nullable=True)
    confianca: Mapped[float] = mapped_column(Float, default=0.0)  # NAO calibrada: nao e probabilidade
    tags: Mapped[Any] = mapped_column(JSON)
    refs: Mapped[Any] = mapped_column(JSON)
    afirma: Mapped[Any] = mapped_column(JSON, nullable=True)  # {"sujeito": ..., "valor": ...} p/ detectar contradicao
    necessita_revalidacao: Mapped[bool] = mapped_column(Boolean, default=False)
    substituida_por: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hash_conteudo: Mapped[str] = mapped_column(String(64))
    sinalizadores: Mapped[Any] = mapped_column(JSON)  # {pii_redigida: [...], suspeita_injecao: [...]}
    expira_em: Mapped[str | None] = mapped_column(String(40), nullable=True)
    criado_em: Mapped[str] = mapped_column(String(40))
    atualizado_em: Mapped[str] = mapped_column(String(40))
    # Utilidade medida: quantas vezes a memoria entrou no contexto E foi citada pela resposta (reforco leve no ranking)
    usos: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    ultimo_uso: Mapped[str | None] = mapped_column(String(40), nullable=True)


class MemoriaVersao(Base):
    __tablename__ = "memoria_versao"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    memoria_id: Mapped[str] = mapped_column(ForeignKey("memoria.id"), index=True)
    versao: Mapped[int] = mapped_column(Integer)
    titulo: Mapped[str] = mapped_column(String(200))
    resumo: Mapped[str] = mapped_column(Text)
    conteudo: Mapped[str] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(String(16))
    motivo: Mapped[str] = mapped_column(Text, default="")
    ator: Mapped[str] = mapped_column(String(100))
    criado_em: Mapped[str] = mapped_column(String(40))


class MemoriaEvidencia(Base):
    __tablename__ = "memoria_evidencia"
    memoria_id: Mapped[str] = mapped_column(ForeignKey("memoria.id"), primary_key=True)
    evidencia_id: Mapped[str] = mapped_column(ForeignKey("evidencia.id"), primary_key=True)
    vinculado_por: Mapped[str] = mapped_column(String(100))
    vinculado_em: Mapped[str] = mapped_column(String(40))


class NoConhecimento(Base):
    __tablename__ = "no_conhecimento"
    __table_args__ = (UniqueConstraint("namespace", "tipo", "nome", name="uq_no_ns_tipo_nome"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tipo: Mapped[str] = mapped_column(String(32), index=True)
    nome: Mapped[str] = mapped_column(String(200))
    namespace: Mapped[str] = mapped_column(String(200), index=True)
    props: Mapped[Any] = mapped_column(JSON)
    fonte: Mapped[Any] = mapped_column(JSON)
    estado: Mapped[str] = mapped_column(String(16))
    versao: Mapped[int] = mapped_column(Integer, default=1)
    criado_em: Mapped[str] = mapped_column(String(40))


class ArestaConhecimento(Base):
    __tablename__ = "aresta_conhecimento"
    __table_args__ = (UniqueConstraint("origem", "destino", "tipo", "namespace", name="uq_aresta"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    origem: Mapped[str] = mapped_column(ForeignKey("no_conhecimento.id"), index=True)
    destino: Mapped[str] = mapped_column(ForeignKey("no_conhecimento.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(32))
    namespace: Mapped[str] = mapped_column(String(200), index=True)  # escopo da aresta
    fonte: Mapped[Any] = mapped_column(JSON)
    hash: Mapped[str] = mapped_column(String(64))
    estado: Mapped[str] = mapped_column(String(16))
    observado_em: Mapped[str | None] = mapped_column(String(40), nullable=True)
    valido_de: Mapped[str | None] = mapped_column(String(40), nullable=True)
    valido_ate: Mapped[str | None] = mapped_column(String(40), nullable=True)
    revisado_por: Mapped[str | None] = mapped_column(String(100), nullable=True)
    versao: Mapped[int] = mapped_column(Integer, default=1)
    criado_em: Mapped[str] = mapped_column(String(40))


class ArquivoIndexado(Base):
    __tablename__ = "arquivo_indexado"
    __table_args__ = (UniqueConstraint("namespace", "repositorio", "caminho", name="uq_arquivo"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    namespace: Mapped[str] = mapped_column(String(200), index=True)
    repositorio: Mapped[str] = mapped_column(String(200))
    caminho: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64))
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    linguagem: Mapped[str] = mapped_column(String(32))
    tamanho: Mapped[int] = mapped_column(Integer)
    estado: Mapped[str] = mapped_column(String(16), default="ativo")  # ativo | removido
    erro_parse: Mapped[str | None] = mapped_column(String(200), nullable=True)
    indexado_em: Mapped[str] = mapped_column(String(40))


class Simbolo(Base):
    __tablename__ = "simbolo"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    arquivo_id: Mapped[str] = mapped_column(ForeignKey("arquivo_indexado.id"), index=True)
    nome: Mapped[str] = mapped_column(String(300), index=True)
    tipo: Mapped[str] = mapped_column(String(16))
    linha: Mapped[int] = mapped_column(Integer)
    assinatura: Mapped[str] = mapped_column(String(300), default="")
    # Colunas normalizadas e INDEXADAS: permitem buscar por nome sem varrer a tabela (lower(nome) impediria o uso de indice).
    nome_norm: Mapped[str] = mapped_column(String(300), index=True, default="", server_default="")
    nome_final: Mapped[str] = mapped_column(String(300), index=True, default="", server_default="")  # apos o ultimo '.'


class CodigoTrecho(Base):
    """Mapa (arquivo, linhas) -> rowid de `codigo_fts`. Filtrar o FTS5 por coluna UNINDEXED varre a tabela inteira;
    esta tabela comum, indexada, torna remocao e consulta por arquivo/linha O(log n). `id` == rowid no FTS5."""

    __tablename__ = "codigo_trecho"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    arquivo_id: Mapped[str] = mapped_column(ForeignKey("arquivo_indexado.id"))
    linha_ini: Mapped[int] = mapped_column(Integer)
    linha_fim: Mapped[int] = mapped_column(Integer)
    __table_args__ = (Index("ix_codigo_trecho_arquivo_linha", "arquivo_id", "linha_ini"),)


# ============================ Conversa e uso de contexto (Fase 4) ============================
class Mensagem(Base):
    """Conversa de uma tarefa entre o agente e o desenvolvedor: briefing em secoes, decisoes agrupadas, respostas."""

    __tablename__ = "mensagem"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tarefa_id: Mapped[str] = mapped_column(ForeignKey("tarefa.id"), index=True)
    ordem: Mapped[int] = mapped_column(Integer)  # monotonica por tarefa (timestamps podem empatar)
    execucao_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    papel: Mapped[str] = mapped_column(String(16))  # agente | operador | sistema
    tipo: Mapped[str] = mapped_column(
        String(32)
    )  # entendimento | resposta | premissas | decisoes | ... | resposta_operador
    conteudo: Mapped[str] = mapped_column(Text)
    dados: Mapped[Any] = mapped_column(JSON, nullable=True)  # ex.: decisoes estruturadas
    criado_em: Mapped[str] = mapped_column(String(40))


class ContextoUso(Base):
    """O que entrou no prompt de uma execucao e o que o agente realmente USOU (base do aprendizado futuro)."""

    __tablename__ = "contexto_uso"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tarefa_id: Mapped[str] = mapped_column(ForeignKey("tarefa.id"), index=True)
    execucao_id: Mapped[str] = mapped_column(String(64), unique=True)
    itens: Mapped[Any] = mapped_column(JSON)  # [{ref, origem, id, tokens, pontuacao, texto}]
    tokens_contexto: Mapped[int] = mapped_column(Integer, default=0)
    tokens_prompt: Mapped[int] = mapped_column(
        Integer, default=0
    )  # ESTIMADO (~4 caracteres/token), nao contagem do provedor
    orcamento: Mapped[int] = mapped_column(Integer, default=0)
    omitidos: Mapped[Any] = mapped_column(JSON)
    termos: Mapped[Any] = mapped_column(JSON)
    uteis: Mapped[Any] = mapped_column(JSON, nullable=True)
    criado_em: Mapped[str] = mapped_column(String(40))


# ============================ Quadro de comunicacao (blackboard, orientacao 7.4) ============================
class MensagemQuadro(Base):
    """Mensagem tipada entre master, operador, sistema e agentes. Dado (payload sanitizado) + referencias, nunca historico."""

    __tablename__ = "mensagem_quadro"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    versao: Mapped[int] = mapped_column(Integer, default=1)
    origem: Mapped[str] = mapped_column(String(60))
    destino: Mapped[str] = mapped_column(String(60))
    tipo: Mapped[str] = mapped_column(String(16))  # comando | evento | apontamento | pergunta | resultado
    prioridade: Mapped[int] = mapped_column(Integer, default=3)  # 1 = mais urgente ... 5
    assunto: Mapped[str] = mapped_column(String(200))
    payload: Mapped[Any] = mapped_column(JSON)
    referencias: Mapped[Any] = mapped_column(JSON)
    tarefa_id: Mapped[str | None] = mapped_column(ForeignKey("tarefa.id"), nullable=True, index=True)
    estado: Mapped[str] = mapped_column(String(16))  # pendente | entregue | resolvida | expirada
    dedup_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(64))
    criado_em: Mapped[str] = mapped_column(String(40))
    expira_em: Mapped[str | None] = mapped_column(String(40), nullable=True)
    entregue_em: Mapped[str | None] = mapped_column(String(40), nullable=True)
    resolvida_em: Mapped[str | None] = mapped_column(String(40), nullable=True)
    resolvida_por: Mapped[str | None] = mapped_column(String(100), nullable=True)
    nota_resolucao: Mapped[str] = mapped_column(Text, default="")
    __table_args__ = (
        UniqueConstraint("origem", "dedup_key", name="uq_quadro_origem_dedup"),
        Index("ix_quadro_destino_estado_prio", "destino", "estado", "prioridade"),
    )


# ============================ Configuracao do orquestrador ============================
class Configuracao(Base):
    """Pares chave/valor versionados (concorrencia otimista). Hoje: `sistema` = modelo por parte e nivel de detalhe."""

    __tablename__ = "configuracao"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    valor: Mapped[Any] = mapped_column(JSON)
    versao: Mapped[int] = mapped_column(Integer, default=1)
    atualizado_em: Mapped[str] = mapped_column(String(40))


class AcaoExterna(Base):
    """Escrita em servico externo (comentar, criar, transicionar). Nasce PENDENTE e so executa apos aprovacao do operador.
    `parametros` guarda apenas o conteudo da acao (ex.: texto do comentario), nunca segredo; `resultado` e um resumo curto."""

    __tablename__ = "acao_externa"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    versao: Mapped[int] = mapped_column(Integer, default=1)
    integracao: Mapped[str] = mapped_column(String(60))
    acao: Mapped[str] = mapped_column(String(60))
    parametros: Mapped[Any] = mapped_column(JSON)
    descricao: Mapped[str] = mapped_column(String(400))
    risco: Mapped[str] = mapped_column(String(16))
    estado: Mapped[str] = mapped_column(String(16), index=True)  # pendente | negada | executando | executada | falhou | expirada
    solicitado_por: Mapped[str] = mapped_column(String(100))
    tarefa_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dedup_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    decidido_por: Mapped[str | None] = mapped_column(String(100), nullable=True)
    adendo: Mapped[str] = mapped_column(Text, default="")
    resultado: Mapped[str] = mapped_column(Text, default="")
    criado_em: Mapped[str] = mapped_column(String(40))
    decidido_em: Mapped[str | None] = mapped_column(String(40), nullable=True)
    executado_em: Mapped[str | None] = mapped_column(String(40), nullable=True)
    __table_args__ = (UniqueConstraint("solicitado_por", "dedup_key", name="uq_acao_externa_dedup"),)


class LigacaoGrafo(Base):
    """Ligacao tipada criada pelo usuario na tela do grafo. Pontas podem ser memoria ou no (validadas no servico, com ACL);
    o tipo segue a mesma ontologia das arestas de conhecimento. Fica no namespace mais restrito das duas pontas."""

    __tablename__ = "ligacao_grafo"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    origem: Mapped[str] = mapped_column(String(64))
    destino: Mapped[str] = mapped_column(String(64))
    tipo: Mapped[str] = mapped_column(String(32))
    namespace: Mapped[str] = mapped_column(String(200), index=True)
    nota: Mapped[str] = mapped_column(String(300), default="")
    criado_por: Mapped[str] = mapped_column(String(100))
    criado_em: Mapped[str] = mapped_column(String(40))
    __table_args__ = (UniqueConstraint("origem", "destino", "tipo", name="uq_ligacao_grafo"),)


class Anexo(Base):
    """Arquivo anexado ao contexto de uma tarefa. `origem`: projeto (arquivo de uma pasta do projeto; `caminho` relativo a ela)
    ou envio (escolhido pelo usuario, de qualquer lugar: so ESTE conteudo fica visivel, nunca a pasta de onde veio).
    `texto` e o conteudo legivel ja redigido (segredos mascarados) e limitado; imagens ficam no armazenamento de artefatos."""

    __tablename__ = "anexo"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tarefa_id: Mapped[str] = mapped_column(ForeignKey("tarefa.id"), index=True)
    nome: Mapped[str] = mapped_column(String(200))
    origem: Mapped[str] = mapped_column(String(16))
    caminho: Mapped[str | None] = mapped_column(String(500), nullable=True)
    mime: Mapped[str] = mapped_column(String(100))
    tamanho: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    texto: Mapped[str] = mapped_column(Text, default="")
    truncado: Mapped[bool] = mapped_column(Boolean, default=False)
    criado_em: Mapped[str] = mapped_column(String(40))


class VetorSemantico(Base):
    """Embedding de um documento ja indexado (trecho de codigo ou memoria), usado SO quando a busca semantica estiver ligada.
    `chave` = 'c:<id do trecho>' ou 'm:<id da memoria>'; `sha` detecta mudanca (reindexa so o que mudou). O texto nunca e
    guardado aqui: a fonte continua sendo o FTS/memoria (ja redigidos). Vetor float32 normalizado (cosseno = produto escalar)."""
    __tablename__ = "vetor_semantico"
    chave: Mapped[str] = mapped_column(String(80), primary_key=True)
    origem: Mapped[str] = mapped_column(String(16), index=True)
    ref: Mapped[str] = mapped_column(String(64), index=True)
    namespace: Mapped[str] = mapped_column(String(200), index=True)
    sha: Mapped[str] = mapped_column(String(64))
    modelo: Mapped[str] = mapped_column(String(120), index=True)
    dim: Mapped[int] = mapped_column(Integer)
    vetor: Mapped[bytes] = mapped_column(LargeBinary)


# ============================ Melhorias de mercado (9.x): desfazer, isolamento, roteamento, revisao ============================
class PontoRestauracao(Base):
    """Foto da pasta de trabalho ANTES de uma execucao que escreve (blobs enderecados por conteudo fora do Git).
    `antes`/`depois`: {caminho relativo: sha256}. Desfazer so restaura arquivos que ninguem mexeu depois da execucao."""

    __tablename__ = "ponto_restauracao"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    execucao_id: Mapped[str] = mapped_column(String(64), index=True)
    tarefa_id: Mapped[str] = mapped_column(String(64), index=True)
    pasta: Mapped[str] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(String(16), index=True)  # capturado | finalizado | desfeito | sem_mudancas
    antes: Mapped[Any] = mapped_column(JSON)
    depois: Mapped[Any] = mapped_column(JSON, nullable=True)
    resumo: Mapped[Any] = mapped_column(JSON, nullable=True)  # {alterados, adicionados, removidos, ignorados}
    parcial: Mapped[bool] = mapped_column(Boolean, default=False)
    criado_em: Mapped[str] = mapped_column(String(40))
    finalizado_em: Mapped[str | None] = mapped_column(String(40), nullable=True)
    desfeito_em: Mapped[str | None] = mapped_column(String(40), nullable=True)


class AreaIsolada(Base):
    """Pasta isolada (git worktree) criada quando duas execucoes disputam a mesma pasta de trabalho."""

    __tablename__ = "area_isolada"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # = execucao_id
    tarefa_id: Mapped[str] = mapped_column(String(64), index=True)
    pasta_origem: Mapped[str] = mapped_column(Text)
    caminho: Mapped[str] = mapped_column(Text)
    branch: Mapped[str] = mapped_column(String(200))
    estado: Mapped[str] = mapped_column(String(16), index=True)  # ativa | removida
    criado_em: Mapped[str] = mapped_column(String(40))
    removida_em: Mapped[str | None] = mapped_column(String(40), nullable=True)


class EstatisticaRota(Base):
    """Taxa de sucesso (media movel exponencial) por nivel/parte/modelo: base do roteamento que aprende com o uso."""

    __tablename__ = "estatistica_rota"
    chave: Mapped[str] = mapped_column(String(200), primary_key=True)
    nivel: Mapped[str] = mapped_column(String(16), index=True)
    parte: Mapped[str] = mapped_column(String(32))
    modelo: Mapped[str] = mapped_column(String(120))
    execucoes: Mapped[int] = mapped_column(Integer, default=0)
    sucessos: Mapped[int] = mapped_column(Integer, default=0)
    taxa: Mapped[float] = mapped_column(Float, default=1.0)
    atualizado_em: Mapped[str] = mapped_column(String(40))


class SugestaoMemoria(Base):
    """Sugestao da organizacao automatica do segundo cerebro (duplicata, desatualizada, ligacao). Nunca altera nada sozinha:
    vai para a fila de revisao e so vale quando o usuario aceita."""

    __tablename__ = "sugestao_memoria"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tipo: Mapped[str] = mapped_column(String(24), index=True)  # duplicata | desatualizada | ligacao
    chave: Mapped[str] = mapped_column(String(200), unique=True)  # deduplicacao (tipo + memorias ordenadas)
    memorias: Mapped[Any] = mapped_column(JSON)
    namespace: Mapped[str] = mapped_column(String(200), index=True)
    motivo: Mapped[str] = mapped_column(Text, default="")
    dados: Mapped[Any] = mapped_column(JSON, nullable=True)
    estado: Mapped[str] = mapped_column(String(16), index=True)  # pendente | aceita | rejeitada | obsoleta
    criado_em: Mapped[str] = mapped_column(String(40))
    decidido_em: Mapped[str | None] = mapped_column(String(40), nullable=True)
    decidido_por: Mapped[str | None] = mapped_column(String(100), nullable=True)


# ============================ Contas de acesso ao painel (usuario e senha) ============================
class Usuario(Base):
    """Conta local do painel. A senha so existe como hash scrypt com sal (nunca em texto, log ou evento)."""

    __tablename__ = "usuario"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    nome: Mapped[str] = mapped_column(String(64), unique=True)  # normalizado (minusculas)
    senha_hash: Mapped[str] = mapped_column(String(300))
    falhas: Mapped[int] = mapped_column(Integer, default=0)
    bloqueado_ate: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ultimo_acesso: Mapped[str | None] = mapped_column(String(40), nullable=True)
    criado_em: Mapped[str] = mapped_column(String(40))
    atualizado_em: Mapped[str] = mapped_column(String(40))


class Sessao(Base):
    """Sessao de login. `id` = sha256 do token entregue ao navegador (o token em si nunca e guardado)."""

    __tablename__ = "sessao"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    usuario_id: Mapped[str] = mapped_column(String(64), index=True)
    criado_em: Mapped[str] = mapped_column(String(40))
    ultimo_uso: Mapped[str] = mapped_column(String(40))
    expira_em: Mapped[str] = mapped_column(String(40), index=True)  # absoluto; a inatividade e conferida por ultimo_uso
