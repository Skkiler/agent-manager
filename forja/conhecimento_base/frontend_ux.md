---
titulo: Front-end
pai: Base de conhecimento da Forja
tags: frontend, web, javascript, css
tipo: estrutural
---
Interfaces rápidas, acessíveis e seguras, que mostram estados reais.
Subtópicos: [[Acessibilidade (WCAG)]], [[Desempenho web]], [[Estado e componentes de UI]], [[Segurança no front-end]].
Relacionado: [[UI e UX design]].
+++
---
titulo: Acessibilidade (WCAG)
pai: Front-end
tags: acessibilidade, a11y, wcag, aria
relacionados: Cores e contraste; Formulários e feedback
---
- HTML semântico primeiro (button, nav, main, label); ARIA só quando o HTML não basta.
- Tudo operável por teclado, com foco visível e ordem lógica; janelas modais prendem e devolvem o foco.
- Contraste mínimo AA: 4,5:1 para texto normal, 3:1 para texto grande e componentes.
- Todo controle tem nome acessível (label, aria-label); imagens informativas têm texto alternativo.
- Respeite `prefers-reduced-motion` e não dependa só de cor para transmitir estado.
- Mensagens dinâmicas em região `aria-live`; erros de formulário ligados ao campo.
- Teste com axe e com navegação real por teclado/leitor de tela.
+++
---
titulo: Desempenho web
pai: Front-end
tags: performance, web vitals, carregamento
relacionados: Estado e componentes de UI; Índices e desempenho de consultas
---
- Meça: LCP (carregamento), INP (resposta à interação), CLS (estabilidade visual).
- Menos JavaScript enviado; carregue sob demanda o que não é da primeira tela.
- Agrupe rajadas de eventos (debounce) e evite re-renderizar o que não mudou.
- Imagens no tamanho certo e formatos modernos; reserve espaço para evitar deslocamento.
- Cache com controle de versão dos estáticos; API com paginação e respostas pequenas.
+++
---
titulo: Estado e componentes de UI
pai: Front-end
tags: estado, componentes, loading, erro
relacionados: Formulários e feedback; Desempenho web
---
- Toda tela tem estados explícitos: carregando, vazio, erro, sucesso e sem permissão.
- Uma fonte de verdade para cada dado; derive o resto.
- Componentes pequenos, com entrada clara e sem acesso direto a banco ou CLI (só pela API).
- Concorrência na UI: ignore respostas antigas (só a última requisição escreve) e trate conflito de versão.
- Tokens de design (cores, espaçamento, tipografia, camadas) em variáveis; nada de valor solto repetido.
+++
---
titulo: Segurança no front-end
pai: Front-end
tags: xss, csp, front, seguranca
relacionados: Validação de entrada e injeção; Autenticação e autorização
---
- Conteúdo vindo do servidor/usuário entra por `textContent`; nunca `innerHTML`, `eval` ou `new Function`.
- CSP restritiva (`default-src 'self'`, sem `unsafe-inline`), `object-src 'none'`, `base-uri 'none'`.
- Token de API em memória ou sessão da aba; nunca em localStorage compartilhado nem em URL de log.
- A autorização real é do servidor; esconder botão não protege nada.
- Não exiba stack trace, token ou dado pessoal na tela.
+++
---
titulo: UI e UX design
pai: Base de conhecimento da Forja
tags: ux, ui, design, usabilidade
tipo: estrutural
---
Interface boa reduz o esforço de quem usa: clara, consistente, previsível e acessível.
Subtópicos: [[Heurísticas de Nielsen]], [[Hierarquia visual e tipografia]], [[Cores e contraste]],
[[Formulários e feedback]], [[Movimento e microinterações]].
Relacionado: [[Front-end]], [[Acessibilidade (WCAG)]].
+++
---
titulo: Heurísticas de Nielsen
pai: UI e UX design
tags: heuristicas, usabilidade, avaliacao
relacionados: Formulários e feedback; Hierarquia visual e tipografia
---
Dez princípios para avaliar uma interface.
1. Visibilidade do estado do sistema (feedback rápido).
2. Correspondência com o mundo real (linguagem do usuário).
3. Controle e liberdade (desfazer, cancelar, sair).
4. Consistência e padrões (o mesmo tipo de controle reage igual).
5. Prevenção de erros (confirmação para ação destrutiva, valores padrão seguros).
6. Reconhecer em vez de lembrar (opções visíveis, exemplos).
7. Flexibilidade e eficiência (atalhos para quem sabe).
8. Estética e minimalismo (sem informação irrelevante; detalhes sob demanda).
9. Ajudar a reconhecer e corrigir erros (mensagem clara com a saída).
10. Ajuda e documentação contextuais.
+++
---
titulo: Hierarquia visual e tipografia
pai: UI e UX design
tags: tipografia, hierarquia, layout, espacamento
relacionados: Cores e contraste; Heurísticas de Nielsen
---
- Uma família de fonte (mais uma monoespaçada para código) e uma escala de tamanhos fixa (ex.: 11/12/13/15/18).
- Hierarquia por tamanho, peso e espaço antes de cor.
- Espaçamento em múltiplos de 4 px; alinhamento em grade.
- O texto se adapta ao controle (reticências e dica com o texto inteiro); o controle não cresce por causa do texto.
- Textos longos: resumo visível e "ler mais".
- Telas secundárias em janelas e menus sobrepostos para não deslocar o conteúdo principal.
+++
---
titulo: Cores e contraste
pai: UI e UX design
tags: cores, contraste, tema, paleta
relacionados: Acessibilidade (WCAG); Hierarquia visual e tipografia
---
- Paleta por papéis (fundo, superfície, texto, mudo, acento, ok, aviso, erro), não por cor solta.
- Um acento principal; cores semânticas só para estado.
- Verifique contraste de cada par usado (AA 4,5:1) em todos os temas.
- Tema claro e escuro com os mesmos papéis; respeite a preferência do sistema.
- Nunca use só cor para informar (acrescente ícone, texto ou forma).
+++
---
titulo: Formulários e feedback
pai: UI e UX design
tags: formularios, validacao, feedback, erros
relacionados: Heurísticas de Nielsen; Estado e componentes de UI
---
- Rótulo visível em todo campo; exemplo ou formato esperado ao lado.
- Valide cedo, mas mostre erro depois que o usuário sai do campo; mensagem diz como corrigir.
- Ação principal destacada; destrutiva separada e com confirmação.
- Botão desabilitado durante o envio; resultado confirmado (aviso de sucesso ou erro).
- Preserve o que foi digitado em caso de erro; avise antes de fechar com alterações não salvas.
+++
---
titulo: Movimento e microinterações
pai: UI e UX design
tags: animacao, microinteracao, hover, transicao
relacionados: Acessibilidade (WCAG); Hierarquia visual e tipografia
---
- Movimento curto (120-200 ms) e com propósito: mostrar origem, mudança de estado ou relação.
- Hover, foco, pressionado e desabilitado com resposta visual consistente em todo controle do mesmo tipo.
- Animação nunca bloqueia a ação nem esconde informação.
- Desligue animações com `prefers-reduced-motion`.
- Cenas lúdicas (ex.: pixel art) só projetam o estado real e podem ser desligadas.
