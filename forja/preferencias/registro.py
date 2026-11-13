"""Registro declarativo das preferencias do usuario.

Cada preferencia diz: onde aparece (categoria, geral/avancado), o que e, exemplos (baixo/medio/alto), o que muda ao ligar ou
desligar e o risco. A MESMA estrutura valida os valores no servidor e desenha o menu na tela, entao nao ha opcao sem explicacao.
Preferencias nao-secretas ficam no perfil do usuario (fora do Git). Segredos nunca passam por aqui (ver integracoes/ambiente).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from forja.agentes import estilo as _estilo


def _pacotes() -> list[dict[str, Any]]:
    try:
        from forja.memoria.base import pacotes_disponiveis

        return pacotes_disponiveis()
    except Exception:  # noqa: BLE001 - pacote com formato invalido nao derruba as preferencias (os testes da base acusam)
        return []


@dataclass(frozen=True)
class Exemplo:
    rotulo: str
    valor: Any
    descricao: str


@dataclass(frozen=True)
class Categoria:
    id: str
    rotulo: str
    descricao: str


@dataclass(frozen=True)
class Preferencia:
    id: str
    categoria: str
    nivel: str  # geral | avancado
    rotulo: str
    tipo: str  # bool | int | selecao | pastas | tags | texto | regras | modelos | revisao | perfil | info
    explicacao: str
    padrao: Any = None
    exemplos: tuple[Exemplo, ...] = ()
    se_ligar: str = ""
    se_desligar: str = ""
    risco: str = "baixo"  # baixo | medio | alto
    minimo: int | None = None
    maximo: int | None = None
    unidade: str = ""
    opcoes: tuple[tuple[str, str], ...] = ()
    reinicia: bool = False
    persistida: bool = True  # False = so exibicao/atalho (modelos, revisao, perfil, info)
    texto: str = field(default="", compare=False)  # conteudo fixo dos tipos 'info'
    detalhes: tuple[dict[str, Any], ...] = ()  # tipo 'tags': o que cada tag faz (mostrado na tela)
    max_texto: int = 0  # tipo 'texto'


CATEGORIAS: tuple[Categoria, ...] = (
    Categoria("agentes", "Agentes", "Quanta liberdade os agentes têm e como eles trabalham. Combine métodos como tags e escreva suas regras."),
    Categoria("cosmetica", "Aparência", "Como a interface se parece e quanto detalhe ela mostra. Não muda o que o sistema faz."),
    Categoria("eficiencia", "Eficiência", "Quanto contexto os agentes recebem. Mais contexto ajuda a acertar, mas custa tokens."),
    Categoria("consumo", "Consumo", "Qual modelo de IA cada parte usa. É aqui que o custo em créditos mais muda."),
    Categoria("privacidade", "Privacidade", "O que os agentes podem ler no seu computador e o que fica oculto."),
    Categoria("seguranca", "Segurança", "Limites e proteções. As proteções essenciais não podem ser desligadas."),
    Categoria("manutencao", "Manutenção", "Seus dados locais e a revisão periódica do esquema."),
)

PREFERENCIAS: tuple[Preferencia, ...] = (
    # ------------------------------------------------------------------ agentes
    Preferencia(
        "nivel_autonomia", "agentes", "geral", "Nível de autonomia", "selecao",
        "Quanto o agente faz sozinho. Em qualquer nível: segredos nunca são lidos, e excluir, publicar, descartar alterações, instalar "
        "dependências, acessar a rede, agir fora da pasta de trabalho ou ações não identificadas sempre perguntam.",
        "restrito", tuple(Exemplo(n.rotulo, n.id, n.descricao) for n in _estilo.NIVEIS),
        se_ligar="Mais autonomia: menos interrupções e tarefas mais longas sem você; toda aprovação automática fica registrada nos eventos.",
        se_desligar="Restrito: você aprova cada ação; mais seguro e mais lento.", risco="alto",
        opcoes=tuple((n.id, n.rotulo) for n in _estilo.NIVEIS)),
    Preferencia(
        "metodos_acao", "agentes", "geral", "Métodos de ação (tags)", "tags",
        "Marque quantas quiser: cada tag acrescenta UMA característica ao modo de trabalho do agente (uma linha curta no pedido). "
        "Tags que se contradizem não podem ser marcadas juntas.",
        [], se_ligar="Cada tag custa poucas dezenas de tokens por tarefa.", se_desligar="Sem tags, o agente usa o comportamento padrão.",
        opcoes=tuple((m.id, m.rotulo) for m in _estilo.METODOS),
        detalhes=tuple({"id": m.id, "descricao": m.descricao, "instrucao": m.instrucao, "conflitos": list(m.conflitos), "efeito": m.efeito}
                       for m in _estilo.METODOS)),
    Preferencia(
        "observacoes_guia", "agentes", "geral", "Observações guia", "texto",
        "Regras, boas práticas e observações escritas por você, enviadas ao agente em toda tarefa (ex.: 'use português nos commits', "
        "'prefira pytest', 'nunca altere a pasta migrations sem perguntar'). Não coloque segredos: o texto vai ao provedor de IA.",
        "", se_ligar="O agente segue suas regras; cada caractere conta no custo da tarefa.", se_desligar="Vazio: nenhum texto extra.",
        max_texto=_estilo.MAX_OBSERVACOES),
    Preferencia(
        "correcao_automatica", "agentes", "avancado", "Conferir com os testes do projeto (uma rodada de correção)", "selecao",
        "Depois que o agente altera código, a Forja roda os testes do projeto (pytest, npm test, cargo ou go, conforme o projeto declara). "
        "Se falharem, devolve a falha ao agente UMA vez para ele corrigir e roda de novo. O resultado vira evidência real. "
        "Rodar testes executa código do projeto: pede sua aprovação, exceto no nível 'Acesso total'.", "uma_rodada",
        (Exemplo("Desligada", "desligada", "A Forja não roda nada; vale a palavra do agente (marcada como não verificada)."),
         Exemplo("Uma rodada", "uma_rodada", "Testes conferidos de verdade; no máximo um turno extra do agente.")),
        se_ligar="Mais confiança no resultado; custa o tempo dos testes e, se falharem, um turno do agente.",
        se_desligar="Mais rápido e barato; 'os testes passaram' fica sem prova.", risco="medio",
        opcoes=(("desligada", "Desligada"), ("uma_rodada", "Uma rodada"))),
    Preferencia(
        "limite_ferramentas_por_execucao", "agentes", "avancado", "Limite de chamadas de ferramenta por execução", "int",
        "Orçamento rígido: passou disso, a Forja interrompe o turno e bloqueia a tarefa com o motivo (a resposta parcial é guardada). "
        "Independente do limite, a MESMA chamada repetida 6 vezes seguidas é tratada como laço e também interrompe.",
        200, (Exemplo("Curto", 60, "Tarefas pequenas; corta cedo agentes que se perdem."), Exemplo("Médio", 200, "Padrão."),
              Exemplo("Longo", 800, "Refatorações grandes.")),
        se_ligar="Mais alto: tarefas longas terminam; um agente perdido gasta mais antes de parar.",
        se_desligar="Mais baixo: economia e proteção contra laços; tarefas grandes podem parar no meio.",
        minimo=20, maximo=2000, unidade="chamadas"),
    Preferencia(
        "testes_tempo_maximo", "agentes", "avancado", "Tempo máximo dos testes da Forja", "int",
        "Se a suíte de testes passar deste tempo, a execução é interrompida e registrada como 'tempo esgotado' (não como sucesso).",
        300, (Exemplo("Curto", 60, "Projetos pequenos."), Exemplo("Médio", 300, "Padrão."), Exemplo("Longo", 1200, "Suítes grandes.")),
        se_ligar="Mais longo: suítes grandes terminam; a tarefa demora mais.", se_desligar="Mais curto: resposta rápida; suítes grandes não terminam.",
        minimo=10, maximo=3600, unidade="segundos"),
    Preferencia(
        "pontos_restauracao", "agentes", "avancado", "Permitir desfazer as alterações de cada tarefa", "bool",
        "Antes de uma tarefa que altera arquivos, a Forja guarda uma cópia da pasta de trabalho (fora do projeto e fora do Git). "
        "Depois, o cartão da tarefa ganha 'Desfazer alterações': volta só os arquivos que a tarefa mexeu e que ninguém alterou "
        "depois. Arquivos com cara de segredo (.env, chaves), pastas como .git e node_modules e arquivos acima de 5 MB ficam de fora.",
        True, se_ligar="Você pode voltar atrás em qualquer tarefa; custa alguns segundos e espaço em disco por tarefa que escreve.",
        se_desligar="Nada é copiado; desfazer depende só do seu Git."),
    Preferencia(
        "isolar_paralelas", "agentes", "avancado", "Pasta isolada para tarefas em paralelo (git worktree)", "bool",
        "Se duas tarefas vão escrever na mesma pasta ao mesmo tempo, a segunda ganha uma cópia isolada do repositório "
        "(git worktree em .worktrees/, num branch forja/...). Você revisa e junta o branch quando quiser; nada é mesclado sozinho. "
        "Sem Git (ou desligado), a segunda tarefa espera: ela fica bloqueada com o motivo.",
        True, se_ligar="Tarefas paralelas não se atropelam; cada uma deixa um branch para revisar.",
        se_desligar="Uma tarefa por pasta de cada vez; as outras ficam bloqueadas até a pasta liberar."),
    Preferencia(
        "isolamento_testes", "agentes", "avancado", "Isolamento dos testes rodados pela Forja", "selecao",
        "Os testes rodam presos a um grupo de processos (o tempo esgotado mata todos), com teto de memória e pasta temporária própria. "
        "'Estrito' também troca a pasta pessoal (HOME) por uma caixa de areia e corta a rede por proxy. Não é contêiner: protege contra "
        "efeitos colaterais comuns, não contra código malicioso.", "basico",
        (Exemplo("Básico", "basico", "Compatível com quase todo projeto."),
         Exemplo("Estrito", "estrito", "Testes não escrevem na sua pasta pessoal nem acessam a rede; alguns projetos podem falhar.")),
        se_ligar="Estrito: menos efeitos colaterais; testes que dependem de rede ou do HOME falham.",
        se_desligar="Básico: compatível; o teste ainda pode escrever na sua pasta pessoal.", risco="medio",
        opcoes=(("basico", "Básico"), ("estrito", "Estrito"))),
    Preferencia(
        "subagentes", "agentes", "avancado", "Dividir tarefas complexas em subtarefas", "selecao",
        "No planejamento de uma tarefa complexa o agente pode propor até 4 subtarefas independentes. 'Propor' cria as subtarefas "
        "no Backlog para você revisar; 'Executar' já as prepara e executa em paralelo (cada uma em pasta isolada quando possível) "
        "e cria uma tarefa final que junta e confere os resultados.", "propor",
        (Exemplo("Desligado", "desligado", "O agente faz tudo numa tarefa só."),
         Exemplo("Propor", "propor", "Você decide quais subtarefas valem a pena."),
         Exemplo("Executar", "executar", "Mais rápido em tarefas grandes; gasta mais créditos.")),
        se_ligar="Tarefas grandes andam em paralelo; cada subtarefa consome suas próprias chamadas de modelo.",
        se_desligar="Uma tarefa por vez, mais barato e mais lento.", risco="medio",
        opcoes=(("desligado", "Desligado"), ("propor", "Propor"), ("executar", "Executar"))),
    Preferencia(
        "roteamento_aprende", "agentes", "avancado", "Roteamento que aprende com o uso", "bool",
        "A Forja mede a taxa de sucesso de cada nível de tarefa (simples, normal, complexa) com o modelo usado. Se um nível falha "
        "demais (menos de 60% de sucesso em pelo menos 5 execuções), as próximas tarefas desse nível sobem um degrau (mais "
        "planejamento e esforço). Nunca rebaixa sozinho.", True,
        se_ligar="Menos falhas repetidas; tarefas promovidas custam mais.",
        se_desligar="A classificação usa só as regras fixas."),
    Preferencia(
        "retomar_apos_queda", "agentes", "avancado", "Retomar tarefas após uma queda do servidor", "selecao",
        "Se o servidor cair no meio de uma execução, ao voltar a tarefa fica bloqueada e retomável pelo checkpoint. "
        "'Automático' retoma sozinho, no máximo uma vez por execução (uma tarefa que derruba o servidor não entra em laço).",
        "manual", (Exemplo("Manual", "manual", "Você decide quando retomar."),
                   Exemplo("Automático", "automatico", "Volta a trabalhar sozinho ao reiniciar.")),
        se_ligar="Automático: nada fica parado; gasta créditos sem você olhar.", se_desligar="Manual: você retoma pelo cartão.",
        opcoes=(("manual", "Manual"), ("automatico", "Automático"))),
    Preferencia(
        "controle_escopo", "agentes", "avancado", "Controle de escopo (o agente não 'estica' a tarefa)", "selecao",
        "A Forja confere os arquivos que o agente alterou contra o plano e um limite por nível (simples 3, normal 10, complexa 25). "
        "Durante a execução, passar do limite faz cada nova escrita perguntar. Ao terminar, se saiu do escopo (arquivos demais, fora "
        "do plano ou documentação não pedida), 'Pausar' deixa a tarefa esperando você: desfaça com um clique ou responda aceitando.",
        "pausar", (Exemplo("Pausar", "pausar", "Nada fora do escopo passa sem você ver."),
                   Exemplo("Avisar", "avisar", "Conclui e só avisa na conversa."),
                   Exemplo("Desligado", "desligado", "Sem conferência (como antes).")),
        se_ligar="Menos surpresas e diffs menores; tarefas grandes podem pedir uma confirmação a mais.",
        se_desligar="O agente pode fazer mais do que foi pedido sem aviso.", risco="medio",
        opcoes=(("pausar", "Pausar"), ("avisar", "Avisar"), ("desligado", "Desligado"))),
    Preferencia(
        "master_executar", "agentes", "avancado", "O master já executa as tarefas que cria", "selecao",
        "Quando você conversa com o master, ele decide as tarefas (e sub-masters por projeto). 'Executar' já as coloca para rodar "
        "(as aprovações por ação continuam valendo); 'Propor' deixa prontas no quadro para você iniciar.", "executar",
        (Exemplo("Executar", "executar", "Você só conversa; o trabalho anda sozinho."),
         Exemplo("Propor", "propor", "Você revisa as tarefas antes de rodar.")),
        se_ligar="Mais rápido; gasta créditos sem você iniciar cada tarefa.", se_desligar="Mais controle; você inicia cada tarefa.",
        risco="medio", opcoes=(("executar", "Executar"), ("propor", "Propor"))),
    # ------------------------------------------------------------------ aparencia
    Preferencia(
        "nivel_detalhe", "cosmetica", "geral", "Nível de detalhe da interface", "selecao",
        "Quantos detalhes técnicos a interface mostra: IDs, número de tentativas, JSON dos dados, estados internos.",
        "simples", (Exemplo("Simples", "simples", "Só o essencial. Recomendado para o dia a dia."),
                    Exemplo("Avançado", "avancado", "Mostra IDs, tentativas, dados estruturados e custos. Útil para investigar problemas.")),
        se_ligar="Avançado: telas mais densas, com informação para depurar e auditar.",
        se_desligar="Simples: telas limpas; o que está escondido continua funcionando normalmente.",
        opcoes=(("simples", "Simples"), ("avancado", "Avançado"))),
    Preferencia(
        "tema", "cosmetica", "geral", "Tema", "selecao",
        "Cores da interface. 'Automático' acompanha o tema claro ou escuro do seu sistema; as outras opções fixam a aparência, "
        "independentemente do sistema. Não afeta nenhuma função.", "auto",
        (Exemplo("Automático", "auto", "Segue o tema do seu sistema."), Exemplo("Claro", "claro", "Fundo branco; melhor com muita luz."),
         Exemplo("Escuro", "escuro", "Fundo escuro; confortável à noite.")),
        opcoes=(("auto", "Automático"), ("claro", "Claro"), ("escuro", "Escuro"))),
    Preferencia(
        "paleta_escura", "cosmetica", "geral", "Paleta do tema escuro", "selecao",
        "Conjunto de cores usado quando o tema está escuro (fixo ou pelo sistema). Todas seguem o contraste mínimo de acessibilidade "
        "(WCAG AA). Não afeta nenhuma função.", "grafite",
        (Exemplo("Grafite", "grafite", "Neutra, acento azul (estilo das IDEs)."), Exemplo("Meia-noite", "meia_noite", "Azul-marinho, acento ciano."),
         Exemplo("Floresta", "floresta", "Verde profundo, acento esmeralda."), Exemplo("Brasa", "brasa", "Carvão quente, acento laranja de forja.")),
        opcoes=(("grafite", "Grafite"), ("meia_noite", "Meia-noite"), ("floresta", "Floresta"), ("brasa", "Brasa"))),
    Preferencia(
        "paleta_clara", "cosmetica", "geral", "Paleta do tema claro", "selecao",
        "Conjunto de cores usado quando o tema está claro (fixo ou pelo sistema). Todas seguem o contraste mínimo de acessibilidade "
        "(WCAG AA). Não afeta nenhuma função.", "neve",
        (Exemplo("Neve", "neve", "Branca, acento azul."), Exemplo("Papel", "papel", "Creme quente, acento terracota; cansa menos a vista."),
         Exemplo("Névoa", "nevoa", "Cinza-azulado frio, acento verde-azulado."), Exemplo("Lavanda", "lavanda", "Lilás suave, acento violeta.")),
        opcoes=(("neve", "Neve"), ("papel", "Papel"), ("nevoa", "Névoa"), ("lavanda", "Lavanda"))),
    Preferencia(
        "oficina_pixel", "cosmetica", "avancado", "Oficina pixel art", "bool",
        "Mostra, no painel inferior, bonequinhos que representam as tarefas ativas. É só uma projeção do estado real: não decide nada.",
        True, se_ligar="Visual lúdico; custo praticamente zero.",
        se_desligar="Painel mais limpo e com um pouco menos de redesenho (útil em computadores fracos)."),
    # ------------------------------------------------------------------ eficiencia
    Preferencia(
        "contexto_ativo", "eficiencia", "geral", "Usar a memória como contexto dos agentes", "bool",
        "Antes de executar uma tarefa, a Forja busca no seu segundo cérebro o que for realmente relevante e anexa ao pedido. "
        "Só entram os namespaces liberados no seu .env (APP_CONTEXT_NAMESPACES, padrão: 'publico').",
        True,
        se_ligar="Respostas mais coerentes com o que você já validou. Custa até o orçamento de tokens abaixo, só quando há algo relevante.",
        se_desligar="Custo de contexto zero, mas o agente 'esquece' o segundo cérebro e pode repetir perguntas."),
    Preferencia(
        "busca_semantica", "eficiencia", "avancado", "Busca semântica (embeddings locais)", "selecao",
        "Como o mercado, a Forja busca por termos e estrutura (rápido, sem modelo). A busca semântica acha textos por SIGNIFICADO "
        "e pode reforçar perguntas vagas. 'Fallback' só a usa quando a busca normal fica em dúvida (o melhor resultado medido); "
        "'Ativa' usa sempre. Exige o pacote opcional fastembed e 8 GB de RAM; na 1ª vez baixa um modelo de ~220 MB (Hugging Face) "
        "e indexa em segundo plano (alguns minutos de CPU). Nenhum texto sai do computador.", "inativo",
        (Exemplo("Inativa", "inativo", "Padrão. Zero custo extra."),
         Exemplo("Fallback", "fallback", "Só nas buscas incertas (~86% das perguntas vagas medidas; quase nunca em nomes exatos)."),
         Exemplo("Ativa", "ativo", "Sempre funde os dois rankings. Mais CPU por consulta.")),
        se_ligar="Mais acertos em perguntas em linguagem natural; custa download, indexação e CPU.",
        se_desligar="Sem custo; nomes exatos e termos continuam sendo achados normalmente.", risco="medio",
        opcoes=(("inativo", "Inativa"), ("fallback", "Fallback"), ("ativo", "Ativa"))),
    Preferencia(
        "registrar_aprendizados", "eficiencia", "avancado", "Registrar decisões e aprendizados no segundo cérebro", "bool",
        "Ao concluir uma tarefa real, a Forja guarda um registro curto (entendimento, plano, premissas, suas decisões, evidências e "
        "pendências) como nota candidata do projeto, ligada ao tópico 'Projeto: <nome>'. Fica em pessoal/projetos/<projeto>.",
        True, se_ligar="O conhecimento cresce a cada tarefa e fica auditável; ocupa um pouco de espaço no banco.",
        se_desligar="Nada é guardado automaticamente; você registra o que quiser à mão."),
    Preferencia(
        "organizacao_memoria", "eficiencia", "avancado", "Organizar o segundo cérebro em segundo plano", "selecao",
        "De tempos em tempos (e quando você pede), a Forja procura notas duplicadas, notas desatualizadas (origem mudou, validade "
        "vencida, contestadas há muito tempo) e notas soltas que deveriam estar ligadas. Tudo vira SUGESTÃO na fila de revisão: "
        "nada é apagado nem alterado sem você aceitar.", "sugerir",
        (Exemplo("Desligada", "desligada", "Só quando você clicar em 'Organizar agora'."),
         Exemplo("Sugerir", "sugerir", "A cada 30 minutos, em segundo plano (consulta leve ao banco local).")),
        se_ligar="O cérebro fica limpo e confiável; custa uma varredura local periódica (sem IA).",
        se_desligar="Sem varredura automática; duplicatas e notas velhas se acumulam.",
        opcoes=(("desligada", "Desligada"), ("sugerir", "Sugerir"))),
    Preferencia(
        "pacotes_conhecimento", "eficiencia", "avancado", "Pacotes de conhecimento opcionais", "pacotes",
        "Notas curadas e versionadas sobre um assunto específico (ex.: FastAPI), instaladas como parte somente leitura da base da "
        "Forja. Marque os que combinam com seus projetos; desmarcar remove o pacote. Nada sai do computador.", [],
        se_ligar="O agente acha conhecimento pronto do assunto; ocupa pouco espaço no banco.",
        se_desligar="Só a base geral da Forja.",
        opcoes=tuple((p["id"], p["descricao"]) for p in _pacotes()),
        detalhes=tuple(_pacotes())),
    Preferencia(
        "contexto_limite_sessao", "eficiencia", "avancado", "Limite de contexto por sessão do agente", "int",
        "Quando o contexto medido pelo Kiro passa deste valor, a Forja abre uma sessão NOVA com uma ficha de estado (objetivo, o que já "
        "foi resolvido, arquivos alterados, testes) em vez de deixar a conversa crescer. A qualidade dos modelos cai com contexto longo "
        "(context rot); o que foi resolvido fica no caderno da tarefa e é consultado sob demanda.", 120_000,
        (Exemplo("Enxuto", 60_000, "Sessões curtas: mais foco, mais trocas."), Exemplo("Médio", 120_000, "Padrão."),
         Exemplo("Longo", 200_000, "Menos trocas; risco de perder qualidade.")),
        se_ligar="Mais alto: menos trocas de sessão, mais risco de o agente se perder.",
        se_desligar="Mais baixo: foco e custo menores; trocas mais frequentes.", minimo=20_000, maximo=400_000, unidade="tokens"),
    Preferencia(
        "status_resumos", "eficiencia", "avancado", "Resumos de status para você", "selecao",
        "Ao terminar ou parar, cada tarefa ganha um resumo curto. 'Marcos' usa um modelo barato (parte 'Resumos de status'), em lote "
        "(várias tarefas numa chamada, até 20 por hora); 'Determinístico' monta a frase sem IA; sem custo.", "marcos",
        (Exemplo("Desligado", "desligado", "Sem resumo."), Exemplo("Determinístico", "deterministico", "Frase montada dos eventos, custo zero."),
         Exemplo("Marcos", "marcos", "Texto legível por modelo barato, só no fim de cada tarefa.")),
        se_ligar="Retorno mais claro; poucas chamadas baratas.", se_desligar="Só os eventos técnicos.",
        opcoes=(("desligado", "Desligado"), ("deterministico", "Determinístico"), ("marcos", "Marcos"))),
    Preferencia(
        "contexto_orcamento_tokens", "eficiencia", "avancado", "Orçamento de contexto por tarefa", "int",
        "Teto de tokens (estimados, ~4 caracteres cada) de memória anexada a cada tarefa. Itens pouco relevantes são descartados antes de atingir o teto.",
        2000, (Exemplo("Baixo", 500, "1 a 2 memórias curtas. Mais barato; pode faltar contexto."),
               Exemplo("Médio (sugerido)", 2000, "Equilíbrio para a maioria das tarefas."),
               Exemplo("Alto", 6000, "Mais memórias; custo maior e risco de ruído.")),
        se_ligar="Mais alto: mais chance de achar a memória certa, porém mais tokens por tarefa.",
        se_desligar="Mais baixo: economia, com risco de o agente não receber uma memória útil.",
        minimo=100, maximo=20000, unidade="tokens"),
    Preferencia(
        "kiro_reusar_sessao", "eficiencia", "avancado", "Reabrir a conversa do Kiro ao retomar uma tarefa", "bool",
        "Quando você responde a uma decisão pendente, a Forja pede ao Kiro para reabrir a sessão anterior (session/load) em vez de "
        "reenviar o resumo da conversa. Só funciona se o Kiro anunciar esse recurso; se a sessão não existir mais, volta ao resumo.",
        True, se_ligar="Prompt de retomada bem menor e o agente mantém o histórico real da conversa.",
        se_desligar="Cada retomada começa uma sessão nova com um resumo (comportamento anterior); um pouco mais de tokens."),
    Preferencia(
        "kiro_mcp_ativo", "eficiencia", "avancado", "Dar ao Kiro as ferramentas da Forja (MCP)", "bool",
        "Anexa à sessão do Kiro um servidor MCP local (sem rede) com 5 ferramentas: listar/executar as ferramentas da Forja, buscar na memória "
        "e usar o quadro. Cada uso ainda passa pelas suas aprovações por ação. O MCP só fala com a Forja em loopback e nunca recebe segredos.",
        False, se_ligar="O agente usa ferramentas baratas e deterministicas em vez de ler arquivos inteiros, e publica no quadro sozinho.",
        se_desligar="O agente trabalha só com as ferramentas nativas do Kiro; nada da Forja é oferecido a ele.", risco="medio"),
    # ------------------------------------------------------------------ consumo
    Preferencia(
        "modelos", "consumo", "geral", "Modelo de IA por parte do sistema", "modelos",
        "Cada parte que usa IA pode ter um modelo e um esforço próprios. Os modelos listados vêm da sua conta Kiro, com o custo relativo em créditos "
        "(1,00x é o padrão; 0,06x é ~16 vezes mais barato). Partes determinísticas (busca, ferramentas) não usam IA.",
        None, (Exemplo("Econômico", "execucao: modelo barato, esforço baixo", "Tarefas rotineiras: gasta pouco."),
               Exemplo("Equilibrado", "execucao: padrão da conta", "Sem escolher nada: a conta decide."),
               Exemplo("Forte só onde importa", "revisao: modelo mais capaz, esforço alto", "Gasta mais apenas nas revisões raras.")),
        se_ligar="Um modelo mais forte melhora o raciocínio e custa mais créditos.",
        se_desligar="Vazio = padrão da conta. Um nome inválido bloqueia a execução (não roda em outro modelo sem avisar).",
        risco="medio", persistida=False),
    Preferencia(
        "codex_ativo", "consumo", "avancado", "Usar também o Codex (OpenAI)", "bool",
        "Liga o Codex como segundo agente, pelo mesmo protocolo (ACP). Exige o adaptador instalado (npm i -g @agentclientprotocol/codex-acp) "
        "e 'codex login' com o seu plano. Por segurança, o Codex só trabalha em pastas SEM arquivos de segredo (.env, chaves): ele não "
        "tem as regras de bloqueio que a Forja aplica no Kiro. Confirme se o uso com código da empresa é permitido.", False,
        se_ligar="Mais capacidade e reserva quando o Kiro estiver sem cota; cada agente mantém o próprio contexto.",
        se_desligar="Só o Kiro.", risco="alto"),
    Preferencia(
        "distribuicao_provedores", "consumo", "avancado", "Como dividir o trabalho entre Kiro e Codex", "selecao",
        "Vale só com o Codex ligado. A retomada de uma conversa sempre volta ao agente que a começou.", "so_kiro",
        (Exemplo("Só Kiro", "so_kiro", "O Codex fica parado."),
         Exemplo("Automático", "auto", "Kiro primeiro; Codex quando o Kiro estiver indisponível ou sem cota."),
         Exemplo("Equilibrar", "equilibrar", "Simples, revisões e resumos no Codex; o resto no Kiro."),
         Exemplo("Codex primeiro", "codex_primeiro", "Codex primeiro; Kiro de reserva.")),
        se_ligar="Usa os dois planos; menos espera por cota.", se_desligar="Tudo num agente só.", risco="medio",
        opcoes=(("so_kiro", "Só Kiro"), ("auto", "Automático"), ("equilibrar", "Equilibrar"), ("codex_primeiro", "Codex primeiro"))),
    # ------------------------------------------------------------------ privacidade
    Preferencia(
        "ferramentas_arquivos_ativas", "privacidade", "geral", "Permitir que os agentes leiam arquivos do computador", "bool",
        "Liga as ferramentas que leem arquivos locais (resumo de arquivos, mapa de repositório, varredura de segredos, cofre de notas, agenda .ics, "
        "e-mail .mbox, bancos SQLite). Mesmo ligada, elas só enxergam as pastas permitidas abaixo.",
        False,
        se_ligar="Os agentes podem ler as pastas permitidas. O que for lido pode ir ao prompt do provedor de IA, portanto saia do seu computador.",
        se_desligar="Nenhuma ferramenta toca em arquivo algum (as que recebem texto continuam funcionando).",
        risco="alto"),
    Preferencia(
        "pastas_permitidas", "privacidade", "geral", "Pastas permitidas", "pastas",
        "As únicas pastas (e subpastas) que os agentes podem ler. Use caminhos completos. Escolha o mínimo necessário.",
        [], (Exemplo("Mínimo", ["C:\\Projetos\\forja"], "Só o repositório público da Forja."),
             Exemplo("Moderado", ["C:\\Projetos\\forja", "C:\\Notas"], "O repositório mais o seu cofre de notas."),
             Exemplo("Amplo (evite)", ["C:\\Users\\voce\\Documentos"], "Muita coisa fica visível; use junto com pastas proibidas.")),
        se_ligar="Cada pasta adicionada amplia o que pode vazar para o prompt.",
        se_desligar="Sem pastas, as ferramentas de arquivo ficam indisponíveis.", risco="alto"),
    Preferencia(
        "pastas_proibidas", "privacidade", "geral", "Pastas proibidas", "pastas",
        "Pastas que NUNCA são lidas, mesmo dentro de uma pasta permitida. A proibição sempre vence a permissão. "
        "Os dados da própria Forja (credenciais, banco, memória) e qualquer .git já são protegidos e não precisam ser listados.",
        [], (Exemplo("Exemplo", ["C:\\Notas\\Pessoal", "C:\\Projetos\\forja\\clientes"], "Subpastas sensíveis dentro de pastas permitidas.")),
        se_ligar="Mais pastas proibidas = menos risco de vazamento.", se_desligar="Sem proibidas, vale só o que está permitido."),
    Preferencia(
        "mascarar_enderecos_email", "privacidade", "avancado", "Mascarar endereços de e-mail", "bool",
        "Ao ler uma caixa de e-mail exportada (.mbox), mostra 'a***@dominio.com' em vez do endereço completo, mesmo que o agente peça o completo.",
        True, se_ligar="Endereços de terceiros não vão ao prompt.",
        se_desligar="Os endereços completos podem ir ao prompt do provedor de IA.", risco="medio"),
    # ------------------------------------------------------------------ seguranca
    Preferencia(
        "protecoes_fixas", "seguranca", "geral", "Proteções que não podem ser desligadas", "info",
        "Estas proteções são invariantes do projeto e não têm opção na tela.", None,
        texto=("O servidor só escuta no próprio computador (loopback); o acesso remoto exige túnel SSH ou HTTPS autenticado.\n"
               "Toda chamada da API exige o token; o token e as credenciais ficam fora do Git.\n"
               "Segredos e tokens nunca aparecem em logs, respostas ou na tela.\n"
               "Ações que alteram arquivos ou rodam comandos pedem a sua aprovação, em linguagem natural e agrupadas.\n"
               "Integrações de rede são somente leitura, HTTPS, restritas ao servidor configurado e nascem desligadas.\n"
               "Pastas dos dados da Forja e qualquer .git nunca são lidas por ferramenta."),
        persistida=False),
    Preferencia(
        "regras_controle", "seguranca", "geral", "Regras de controle (suas)", "regras",
        "Regras que valem antes de cada ação do agente. Cada uma casa por tipo de ação, trecho do comando e/ou caminho (ex.: "
        "'*.sql', 'migrations/*') e decide: negar, sempre perguntar ou aprovar. Quando várias casam, vale a mais restritiva. "
        "Nenhuma regra libera segredos, pastas de consulta ou ações que sempre perguntam (excluir, publicar, rede...).",
        [], (Exemplo("Proteger migrações", [{"nome": "migracoes", "categoria": "modificar_arquivos", "caminho_glob": "*migrations*",
                                             "acao": "perguntar"}], "Sempre pergunta antes de mexer em migrações."),
             Exemplo("Liberar pytest", [{"nome": "pytest", "categoria": "executar_comando", "comando_contem": "pytest", "acao": "aprovar"}],
                     "Roda pytest sem perguntar (dentro da pasta de trabalho).")),
        se_ligar="Você ajusta o equilíbrio entre autonomia e controle; cada decisão por regra fica nos eventos.",
        se_desligar="Sem regras, vale só o nível de autonomia.", risco="medio"),
    Preferencia(
        "limite_requisicoes_por_minuto", "seguranca", "avancado", "Limite de requisições por minuto", "int",
        "Quantas chamadas por minuto o servidor aceita de um mesmo cliente. Protege contra laços de automação e abuso.",
        240, (Exemplo("Baixo", 120, "Uso solo e calmo. Mais proteção; pode dar erro 429 se você abrir muitas telas."),
              Exemplo("Médio (sugerido)", 240, "Confortável para uso diário."),
              Exemplo("Alto", 1000, "Muitas abas ou automações. Menos proteção contra laços.")),
        se_ligar="Mais alto: menos bloqueios por engano, menos proteção.",
        se_desligar="Mais baixo: mais proteção; erro 429 (muitas requisições) fica mais provável.",
        risco="medio", minimo=30, maximo=5000, unidade="requisições/min"),
    Preferencia(
        "contar_estaticos_no_limite", "seguranca", "avancado", "Contar os arquivos da interface no limite", "bool",
        "Cada carga da página baixa ~18 arquivos da interface (scripts e estilos). Por padrão eles NÃO entram na contagem do limite, "
        "para que abrir telas não gaste a sua cota. Só as chamadas da API contam.",
        False, se_ligar="Contagem mais rígida (inclui scripts e estilos); abrir telas gasta cota.",
        se_desligar="Recomendado: o limite protege a API, que é o que importa.", risco="baixo"),
    Preferencia(
        "aprovacao_timeout_segundos", "seguranca", "avancado", "Tempo para responder a um pedido de aprovação", "int",
        "Se você não decidir a tempo, o pedido é NEGADO (nunca aprova por omissão) e a tarefa fica bloqueada.",
        900, (Exemplo("Curto", 120, "2 minutos: bom se você acompanha de perto."),
              Exemplo("Médio (sugerido)", 900, "15 minutos."), Exemplo("Longo", 3600, "1 hora: para deixar rodando e voltar depois.")),
        se_ligar="Mais longo: menos tarefas bloqueadas por demora, porém execuções ficam presas esperando.",
        se_desligar="Mais curto: respostas mais rápidas, e mais negações automáticas.",
        minimo=60, maximo=3600, unidade="segundos"),
    # ------------------------------------------------------------------ manutencao
    Preferencia(
        "dados_do_usuario", "manutencao", "geral", "Onde ficam os seus dados", "perfil",
        "Credenciais, banco de dados (memória e segundo cérebro, tarefas, preferências), notas e ferramentas extras ficam numa pasta só sua, "
        "fora do repositório. O que sobe ao Git é apenas código, lógica, configuração padrão e conhecimento público.", None, persistida=False),
    Preferencia(
        "telemetria", "manutencao", "avancado", "Telemetria OpenTelemetry (local)", "selecao",
        "Ao terminar cada execução, a Forja gera rastros no padrão OpenTelemetry (convenções gen_ai: agente, turnos do modelo, "
        "ferramentas, tokens) para você abrir em Jaeger, Grafana ou similar. 'Arquivo' grava JSON na pasta de logs; 'Coletor local' "
        "envia por OTLP/HTTP SÓ para um endereço do próprio computador (APP_OTEL_ENDPOINT). Nunca leva prompt, resposta ou segredos.",
        "desligada", (Exemplo("Desligada", "desligada", "Nada é gerado."),
                      Exemplo("Arquivo", "arquivo", "logs/telemetria/*.jsonl, um rastro por execução."),
                      Exemplo("Coletor local", "otlp_local", "Envia ao coletor em 127.0.0.1 (e também grava o arquivo).")),
        se_ligar="Você enxerga onde o tempo e os tokens vão; ocupa um pouco de disco.", se_desligar="Sem rastros; os eventos continuam no painel.",
        opcoes=(("desligada", "Desligada"), ("arquivo", "Arquivo"), ("otlp_local", "Coletor local"))),
    Preferencia(
        "revisao_esquema", "manutencao", "geral", "Revisão do esquema", "revisao",
        "Pede a um agente que reavalie a plataforma: há melhorias que valem o custo (novos modelos, pesquisas, bibliotecas) ou o esquema está num "
        "ponto agradável? Entrega fatos medidos e exige fontes.", None, persistida=False),
)

POR_ID: dict[str, Preferencia] = {p.id: p for p in PREFERENCIAS}
EDITAVEIS = {p.id for p in PREFERENCIAS if p.persistida}
