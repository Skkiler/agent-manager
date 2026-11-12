---
titulo: RPA (automação robótica de processos)
pai: Base de conhecimento da Forja
tags: rpa, automacao, robos, bots
tipo: estrutural
---
Robôs que operam sistemas como um humano faria: precisam ser robustos, idempotentes, auditáveis e seguros.
Subtópicos: [[Seletores e esperas robustas]], [[Exceções de negócio e de sistema]], [[Idempotência e retentativa]],
[[Credenciais e auditoria em robôs]].
Antes de automatizar pela tela, procure API, arquivo ou banco: são mais estáveis.
+++
---
titulo: Seletores e esperas robustas
pai: RPA (automação robótica de processos)
tags: seletores, playwright, selenium, esperas
relacionados: Exceções de negócio e de sistema; Testes instáveis (flaky)
---
- Prefira seletores por papel e nome acessível ou atributos estáveis (data-testid) a XPath posicional.
- Espere por condição (elemento visível, resposta de rede), nunca por tempo fixo.
- Valide que a tela certa abriu antes de agir (título, URL, texto âncora).
- Isole seletores num mapa por tela (page object): mudança de layout se corrige num lugar.
- Capture tela e HTML no erro para diagnóstico, sem dados sensíveis.
+++
---
titulo: Exceções de negócio e de sistema
pai: RPA (automação robótica de processos)
tags: excecoes, rpa, tratamento, fila
relacionados: Tratamento de erros; Idempotência e retentativa
---
- Exceção de negócio: o dado não permite seguir (CPF inválido, item já processado). Não retente; registre e siga.
- Exceção de sistema: falha técnica (tela não carregou, timeout). Retente com limite e recupere o estado (reabrir app).
- Cada item da fila tem estado (novo, em processamento, ok, erro de negócio, erro de sistema) e motivo.
- Pare o robô após N falhas de sistema seguidas (disjuntor) e avise alguém.
+++
---
titulo: Idempotência e retentativa
pai: RPA (automação robótica de processos)
tags: idempotencia, retentativa, checkpoint
relacionados: Transações e concorrência no banco; Exceções de negócio e de sistema
---
- Toda etapa deve poder rodar de novo sem duplicar efeito (verifique se já foi feito antes de fazer).
- Chave de idempotência por item; registre checkpoint após cada etapa concluída.
- Retentativa com atraso exponencial e limite; registre cada tentativa.
- Retome de onde parou após queda, sem reprocessar o que já terminou.
+++
---
titulo: Credenciais e auditoria em robôs
pai: RPA (automação robótica de processos)
tags: credenciais, auditoria, rpa, logs
relacionados: Gestão de segredos; Observabilidade
---
- Credenciais em cofre ou gerenciador do orquestrador; nunca no script, planilha ou log.
- Conta de serviço por robô, com o menor privilégio necessário e rotação.
- Log de auditoria por item: quem (robô), o quê, quando, resultado; sem dados sensíveis em claro.
- Mascarar dados pessoais em capturas de tela e relatórios.
