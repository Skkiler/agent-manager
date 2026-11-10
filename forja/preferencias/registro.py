"""Registro declarativo das preferencias do usuario.

Cada preferencia diz: onde aparece (categoria, geral/avancado), o que e, exemplos (baixo/medio/alto), o que muda ao ligar ou
desligar e o risco. A MESMA estrutura valida os valores no servidor e desenha o menu na tela, entao nao ha opcao sem explicacao.
Preferencias nao-secretas ficam no perfil do usuario (fora do Git). Segredos nunca passam por aqui (ver integracoes/ambiente).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from forja.agentes import estilo as _estilo


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
    tipo: str  # bool | int | selecao | pastas | modelos | revisao | perfil | info
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
        max_texto=_estilo.MAX_OBSERVACOES),    # ------------------------------------------------------------------ aparencia
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
        "oficina_pixel", "cosmetica", "geral", "Oficina pixel art", "bool",
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
        "revisao_esquema", "manutencao", "geral", "Revisão do esquema", "revisao",
        "Pede a um agente que reavalie a plataforma: há melhorias que valem o custo (novos modelos, pesquisas, bibliotecas) ou o esquema está num "
        "ponto agradável? Entrega fatos medidos e exige fontes.", None, persistida=False),
)

POR_ID: dict[str, Preferencia] = {p.id: p for p in PREFERENCIAS}
EDITAVEIS = {p.id for p in PREFERENCIAS if p.persistida}
