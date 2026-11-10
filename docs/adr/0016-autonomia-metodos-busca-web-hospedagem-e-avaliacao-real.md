# ADR-016 — Autonomia e métodos dos agentes, busca web, hospedagem local instalável e avaliação da busca no corpus real

- Status: aceito

## Decisões

1. **Perfil de trabalho** (`forja/agentes/estilo.py`), definido pelo usuário em Configurações > Agentes:
   - **Nível de autonomia:** restrito (padrão: análise e documentação, tudo pergunta), liberado (também altera código; leituras e edições dentro da
     pasta de trabalho dispensam pergunta) e total (também move e executa comandos sozinho). Em **qualquer** nível: segredos são negados, e excluir,
     publicar, descartar alterações, instalar dependências, acessar a rede, agir fora da pasta de trabalho ou ações não identificadas sempre perguntam.
     Toda aprovação automática vira o evento `kiro.permissao_automatica` (auditável). Se as preferências não puderem ser lidas, vale o restrito.
   - **Métodos de ação como tags combináveis** (Cauteloso, Pesquisador, Direto, Orientado a testes, Econômico, Segurança primeiro, Didático, Documentador).
     Cada tag acrescenta uma linha curta ao pedido. A tela mostra o que ela faz e o texto exato enviado. Tags contraditórias são bloqueadas (com checagem simétrica).
     "Econômico" também corta pela metade o contexto de memória. O perfil padrão não acrescenta nenhum token.
   - **Observações guia:** texto livre de até 2.000 caracteres, recusado se parecer credencial, enviado como "regras do usuário". Não se sobrepõe à segurança.
2. **Busca web** (`integracoes/busca_web.py`): Brave Search API (chave no ambiente) ou SearXNG próprio. A consulta é checada antes de sair (tamanho e segredo).
   `web.ler_pagina` só lê URLs vindas de uma busca recente (30 min) ou de domínios liberados, sempre por HTTPS, com IP público, sem redirecionamento e com teto de tamanho.
   O texto é extraído sem scripts e tratado como dado não confiável. A chave da Brave nunca vai às páginas lidas.
3. **Ligações tipadas no grafo (4.22):** tabela `ligacao_grafo` (migração 0009). As pontas podem ser memória ou nó, o tipo segue a ontologia `ARESTAS`
   e a ligação fica no escopo mais privado das pontas. A ACL não serve de oráculo. Na tela: seção na nota (teclado) e Shift+arrastar no grafo.
4. **Hospedagem:** continua como **app web local** (servidor em loopback + navegador), que é o que sustenta o modelo de segurança. Para parecer app de desktop:
   PWA instalável (manifesto e ícones) e `python -m forja --abrir`. Electron/Tauri foram rejeitados (outro runtime e mais superfície de ataque sem ganho funcional).
5. **CI e acessibilidade (4.21):** GitHub Actions com lint, testes e painel em navegador real (interações, layout estreito de 420 px, axe-core WCAG 2.1 A/AA,
   falhando em violação crítica ou séria). `permissions: contents: read`, só dados sintéticos. A auditoria automática não substitui teste com leitor de tela.
6. **Avaliação no corpus real (4.8 e 4.9),** pela metodologia CodeSearchNet: a docstring é a pergunta e o arquivo é a resposta, com as docstrings removidas
   do índice e cópias idênticas contadas como acerto (`scripts/avaliar_busca_codigo.py`, cópia temporária apagada no fim e só números na saída).
   Medido em 300 perguntas sobre cerca de 2.300 arquivos Python do usuário (recall@5 / MRR / nDCG@5):
   - baseline lexical: 0,067 / 0,046 / 0,050
   - busca atual: 0,137 / 0,104 / 0,106
   - embeddings sozinhos (MiniLM multilíngue, fastembed/ONNX em CPU): 0,106 / 0,079 / 0,078
   - híbrido RRF (atual + embeddings): 0,177 / 0,122 / 0,131

   Decisão do 4.9: embeddings **sozinhos não entram** (perdem para a busca atual). O **híbrido** ganha cerca de 29% em recall, mas custa 229 s de CPU
   para 10.872 blocos e um modelo de cerca de 220 MB. Pela regra de recursos pesados, fica como opção a ativar com aprovação do usuário.
   O glossário PT/EN e a extensão `sinonimos.json` foram medidos e **não** melhoraram (ver ADR-010), por isso continuam desligados.

## Achados reais desta etapa

- `node --check arquivo.js` aceita módulo ESM inválido no Node 24. Uma template string corrompida passou e quebrou o painel. O teste agora valida cada módulo
  com `--input-type=module` via stdin.
- O axe-core encontrou contraste insuficiente e uma região rolável sem foco de teclado. Ambos foram corrigidos (0 violações nas 6 vistas).
- A extensão de sinônimos nunca era carregada (configuração morta). Foi medida e documentada como opcional.
- Código morto removido: `ocupa_recursos`, `_ATIVOS`, `memoria_fts.contar` e `validar_nivel`. Toda rota da API tem cliente (painel, scripts ou testes).
- Arquivos com BOM (criados pelo PowerShell 5) quebrariam o `pip` no CI. Foram limpos, e um teste de higiene impede que voltem.
