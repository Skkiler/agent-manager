---
name: revisao-seguranca
description: Revisar segurança de código e repositório open source, incluindo segredos, permissões, ACP/MCP, LAN e memória privada.
---

# Revisão de segurança do ecossistema

- Verifique `.gitignore`, `.kiroignore`, `.env.example`, hooks de CI e material rastreado por Git.
- Analise riscos de path traversal, shell injection, prompt injection, SSRF, XSS/CSRF, aprovação insegura, acesso entre namespaces e MCP com privilégios.
- Observe limitações da licença Kiro empresarial e ausência de permissão para publicar código privado.
- Não acesse valores reais de `.env`; examine apenas nomes e padrões seguros.
- Classifique achados por gravidade, evidência, impacto e remediação concreta; não alegue scanners executados se não executou.
