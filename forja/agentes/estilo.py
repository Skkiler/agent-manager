"""Perfil de trabalho dos agentes: NIVEL DE AUTONOMIA + METODOS DE ACAO (tags combinaveis) + OBSERVACOES GUIA.

Puro e deterministico. A mesma definicao (1) desenha a tela, (2) gera o texto curto anexado ao prompt e (3) decide quais
pedidos de ferramenta podem ser aprovados sem perguntar. Invariantes que NENHUM nivel muda:
  * acao que envolve segredo/credencial e negada sempre (mediador);
  * acao destrutiva ou sem retorno (excluir, publicar, descartar alteracoes) sempre pergunta;
  * acao fora do workspace, instalacao de dependencias, rede e acoes nao identificadas sempre perguntam;
  * toda aprovacao automatica e registrada como evento (auditavel).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from forja.dominio.erros import ValidacaoDominio

MAX_OBSERVACOES = 2000


@dataclass(frozen=True)
class Nivel:
    id: str
    rotulo: str
    descricao: str
    modos: frozenset[str]  # modos de tarefa que o provedor aceita neste nivel
    automaticas: frozenset[str]  # categorias de acao aprovadas sem perguntar (dentro do workspace)
    instrucao: str  # como o agente deve tratar perguntas/decisoes


NIVEIS: tuple[Nivel, ...] = (
    Nivel("restrito", "Acesso restrito",
          "Somente análise e documentação. Toda ação de ferramenta (ler, editar, executar) pergunta antes. É o padrão.",
          frozenset({"analise", "documentacao"}), frozenset(),
          "Pergunte sempre que houver duvida; nao modifique arquivos."),
    Nivel("liberado", "Acesso liberado",
          "Também altera código e roda verificações. Leituras e edições dentro da pasta de trabalho são aprovadas sozinhas; "
          "comandos, rede, instalação, exclusão, publicação e qualquer coisa fora da pasta continuam perguntando.",
          frozenset({"analise", "documentacao", "alteracao_codigo", "verificacao"}), frozenset({"ler", "ferramenta_forja", "modificar_arquivos"}),
          "Trabalhe sozinho no que for reversivel. Liste em 'Decisoes para voce' so o que for destrutivo, fora do escopo ou uma escolha real entre opcoes."),
    Nivel("total", "Acesso total",
          "O agente trabalha de forma independente: lê, edita, move e executa comandos na pasta de trabalho sem perguntar. "
          "Só pergunta o que for destrutivo ou sem retorno (excluir, publicar, descartar), fora da pasta, instalação, rede ou ações não identificadas.",
          frozenset({"analise", "documentacao", "alteracao_codigo", "verificacao"}),
          frozenset({"ler", "ferramenta_forja", "modificar_arquivos", "mover", "executar_comando"}),
          "Trabalhe de forma independente ate concluir. So pergunte o que for destrutivo/sem retorno, fora do escopo, ou quando houver "
          "duvida real entre opcoes com consequencias diferentes; nos demais casos decida, registre em 'Premissas' e siga."),
)
POR_NIVEL = {n.id: n for n in NIVEIS}
SEMPRE_PERGUNTA = frozenset({"excluir", "excluir_forcado", "publicar", "descartar_alteracoes", "instalar_dependencias", "acessar_rede", "outra"})


@dataclass(frozen=True)
class Metodo:
    id: str
    rotulo: str
    descricao: str  # o que muda, mostrado na tela
    instrucao: str  # texto curto anexado ao prompt (economia: uma linha)
    conflitos: tuple[str, ...] = ()
    efeito: str = ""  # efeito tecnico alem do texto (mostrado na tela)


METODOS: tuple[Metodo, ...] = (
    Metodo("cauteloso", "Cauteloso", "Valida a cada passo: confirma premissas, prefere mudanças pequenas e reversíveis e verifica o resultado antes de seguir.",
           "Cauteloso: confirme premissas, faca mudancas pequenas e reversiveis e verifique cada passo antes do proximo."),
    Metodo("pesquisador", "Pesquisador", "Antes de implementar algo comum ou novo, procura referências (documentação oficial, boas práticas, bugs conhecidos) e cita as fontes.",
           "Pesquisador: antes de implementar, busque referencias (doc oficial, boas praticas, bugs conhecidos) com a busca web disponivel (nativa ou web.buscar da Forja) e cite as fontes.",
           ("direto",), "Usa a busca web da Forja quando estiver configurada (Integrações > Busca web)."),
    Metodo("direto", "Direto", "Implementa direto com base no conhecimento e ajusta conforme os resultados, sem pesquisa prévia nem perguntas óbvias.",
           "Direto: implemente com base no seu conhecimento e ajuste pelos resultados; nao pesquise nem pergunte o obvio.", ("pesquisador",)),
    Metodo("testador", "Orientado a testes", "Escreve ou atualiza testes junto com a mudança e só conclui com os testes passando.",
           "Testes: escreva/atualize testes junto com a mudanca e so conclua com eles passando (cite o comando e o resultado)."),
    Metodo("economico", "Econômico", "Respostas curtas e leitura mínima. Também corta pela metade o contexto de memória anexado à tarefa.",
           "Economico: respostas curtas, leia so o necessario, prefira ferramentas de resumo.", ("didatico",), "Orçamento de contexto da memória × 0,5 nesta execução."),
    Metodo("seguranca", "Segurança primeiro", "Avalia riscos (segredos, injeção, permissões, dados pessoais) e os cita antes de propor a solução.",
           "Seguranca: avalie riscos (segredos, injecao, permissoes, PII) e cite-os em 'Riscos' antes da solucao."),
    Metodo("didatico", "Didático", "Explica o raciocínio, as alternativas consideradas e por que a escolhida venceu.",
           "Didatico: explique o raciocinio e as alternativas consideradas, em linguagem simples.", ("economico",)),
    Metodo("documentador", "Documentador", "Atualiza documentação e comentários e registra as decisões tomadas.",
           "Documentacao: atualize docs/comentarios afetados e registre as decisoes tomadas."),
)
POR_METODO = {m.id: m for m in METODOS}
for _m in METODOS:  # conflitos sao simetricos (detectado cedo, nao em producao)
    assert all(_m.id in POR_METODO[c].conflitos for c in _m.conflitos), _m.id


def validar_metodos(valor: Any) -> list[str]:
    if not isinstance(valor, list) or not all(isinstance(v, str) for v in valor):
        raise ValidacaoDominio("metodos: informe uma lista de tags")
    desconhecidos = [v for v in valor if v not in POR_METODO]
    if desconhecidos:
        raise ValidacaoDominio(f"metodos desconhecidos: {', '.join(desconhecidos)}")
    escolhidos = list(dict.fromkeys(valor))
    for m in escolhidos:
        for c in POR_METODO[m].conflitos:
            if c in escolhidos:
                raise ValidacaoDominio(f"'{POR_METODO[m].rotulo}' e '{POR_METODO[c].rotulo}' se contradizem; escolha um dos dois")
    return escolhidos


def validar_observacoes(valor: Any) -> str:
    from forja.ferramentas.segredos import suspeita  # import tardio: evita ciclo

    if not isinstance(valor, str):
        raise ValidacaoDominio("observacoes: informe um texto")
    texto = valor.strip()
    if len(texto) > MAX_OBSERVACOES:
        raise ValidacaoDominio(f"observacoes: no maximo {MAX_OBSERVACOES} caracteres")
    if any(suspeita(linha) for linha in texto.splitlines()):
        raise ValidacaoDominio("observacoes: o texto parece conter uma credencial; ele vai ao prompt do provedor de IA e nao pode ter segredos")
    return texto


@dataclass(frozen=True)
class PerfilTrabalho:
    nivel: str = "restrito"
    metodos: tuple[str, ...] = ()
    observacoes: str = ""

    @property
    def modos(self) -> frozenset[str]:
        return POR_NIVEL[self.nivel].modos

    def fator_contexto(self) -> float:
        return 0.5 if "economico" in self.metodos else 1.0

    def instrucoes(self) -> str:
        """Bloco curto para o prompt. Vazio no perfil padrao (sem custo extra)."""
        linhas = []
        if self.nivel != "restrito":
            linhas.append(f"Autonomia ({POR_NIVEL[self.nivel].rotulo}): {POR_NIVEL[self.nivel].instrucao}")
        linhas += [f"- {POR_METODO[m].instrucao}" for m in self.metodos if m in POR_METODO]
        if self.observacoes:
            from forja.observabilidade.sanitizar import sanitizar_texto

            linhas.append("Orientacoes do usuario (regras; valem mais que as preferencias acima, nunca mais que seguranca):\n"
                          + sanitizar_texto(self.observacoes)[:MAX_OBSERVACOES])
        return ("\nModo de trabalho:\n" + "\n".join(linhas) + "\n") if linhas else ""

    def aprova_sozinho(self, item: dict[str, Any]) -> bool:
        """True se o pedido pode ser aprovado sem perguntar. Nunca para sensivel, destrutivo, fora do workspace ou desconhecido."""
        if item.get("sensivel") or item.get("fora_do_workspace") or item.get("risco") in ("alto", "critico"):
            return False
        cat = item.get("categoria", "outra")
        return cat not in SEMPRE_PERGUNTA and cat in POR_NIVEL[self.nivel].automaticas


PADRAO = PerfilTrabalho()


def catalogo() -> dict[str, Any]:
    """Para a tela: cada nivel e cada tag com o que fazem, para o usuario verificar antes de escolher."""
    return {
        "niveis": [{"id": n.id, "rotulo": n.rotulo, "descricao": n.descricao, "modos": sorted(n.modos), "automaticas": sorted(n.automaticas)} for n in NIVEIS],
        "sempre_pergunta": sorted(SEMPRE_PERGUNTA),
        "metodos": [{"id": m.id, "rotulo": m.rotulo, "descricao": m.descricao, "instrucao": m.instrucao, "conflitos": list(m.conflitos),
                     "efeito": m.efeito} for m in METODOS],
        "max_observacoes": MAX_OBSERVACOES,
    }
