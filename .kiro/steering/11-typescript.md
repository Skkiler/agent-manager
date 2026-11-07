---
inclusion: fileMatch
fileMatchPattern: ["**/*.ts", "**/*.tsx", "**/*.css", "**/*.html"]
---

# Front-end — estados reais e acessibilidade

Toda UI consome a API autorizada, nunca lê banco ou CLI diretamente. Priorize HTML semântico, estados de loading/erro, acessibilidade, navegação por teclado e reduced motion. Cena pixel art deve apenas projetar eventos do backend e pode ser desabilitada. Nunca exibir token, stack trace ou PII.
