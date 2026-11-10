# ADR-017 — Projetos com pastas, anexos de tarefa e busca híbrida como fallback

- Status: aceito (projetos e anexos); proposto (fallback híbrido, aguarda aprovação por ser recurso pesado)

## Decisões

1. **Projetos com pastas (estilo Codex):** cada projeto guarda `[{caminho, papel}]` (migração 0010).
   - `trabalho`: vira o diretório da sessão do Kiro. O que o agente faz ali depende do nível de autonomia.
   - `consulta`: somente leitura. Nos níveis liberado e total, a leitura dispensa pergunta; a escrita é **negada automaticamente** em qualquer nível.
   - Pastas protegidas (perfil da Forja, `.git`) e as pastas proibidas da tela não entram. Uma pasta que deixar de ser válida some da execução seguinte.
   - Sem pasta de trabalho, o agente usa o diretório isolado de antes.
2. **Explorador e @menção:** listagem e busca por nome dentro das pastas do projeto, sem links, sem `..`, sem `.git`/dependências e sem arquivos sensíveis.
3. **Anexos:** arquivo do projeto, ou **enviado pelo usuário de qualquer pasta**. Do envio, só aquele conteúdo fica visível; o caminho de origem nem é guardado.
   - Texto é redigido (segredos mascarados) e limitado a 20 mil caracteres por anexo e 60 mil no total. Imagens (até 1,5 MB) vão como blocos de imagem ACP quando o Kiro anuncia suporte.
   - No prompt, anexos são marcados como DADOS, não instruções. Arquivos de credencial nunca são anexados.
4. **Busca híbrida como fallback** (proposta do usuário), medida em 300 perguntas sobre cerca de 2.300 arquivos reais (recall@5):

   | estratégia | recall@5 | híbrido usado em |
   |---|---|---|
   | busca atual | 0,163 | 0% |
   | híbrido sempre | 0,218 | 100% |
   | fallback por cobertura do 1º resultado | 0,218 | ~100% |
   | fallback por margem 1º–2º < 0,05 | 0,202 | 57% |
   | fallback por margem < 0,15 | 0,215 | 75% |
   | fallback por margem < 0,30 | 0,222 | 86% |

   Com perguntas em linguagem natural sobre código, a busca lexical quase nunca está "segura", e o gatilho por cobertura dispara sempre.
   O melhor gatilho (margem entre o 1º e o 2º resultado) mantém a qualidade e até supera o híbrido permanente, mas economiza só 14% a 43% das consultas.
   O custo dominante é **indexar** (338 a 440 s de CPU para cerca de 11 mil blocos, modelo de ~220 MB), não consultar (dezenas de ms por pergunta).
   O fallback não evita esse custo, porque o índice precisa existir antes da pergunta.

   Proposta: híbrido **opcional**, com índice incremental em segundo plano (só arquivos alterados), checagem de hardware e gatilho "margem < 0,30".
   Fica desligado até o usuário aprovar o download do modelo e o uso de CPU.

## Achados reais

- O explorador deixava listar o conteúdo de `node_modules` por caminho direto (o filtro ignorava o último componente). Corrigido e coberto por teste.
- Duas trocas rápidas de preferência (nível de detalhe) saíam em paralelo com a mesma versão e a segunda levava 409. As gravações de atalho agora vão em fila (achado no navegador real).
