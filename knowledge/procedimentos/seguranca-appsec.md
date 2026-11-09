# Seguranca de aplicacoes (AppSec) e ciberseguranca basica

- Segredos: nunca no codigo, Git ou logs; use variaveis de ambiente ou cofre; rotacione se vazarem.
- Entrada nao confiavel: valide tipos e limites; consultas SQL sempre parametrizadas; nunca interpolar entrada em shell.
- Autenticacao e autorizacao: menor privilegio; checar permissao no servidor, nunca so na interface.
- Rede: servicos internos em loopback por padrao; acesso remoto por tunel SSH ou HTTPS autenticado com firewall.
- Dependencias: versoes fixas, fontes confiaveis, atencao a nomes parecidos (typosquatting); audite periodicamente.
- Logs: sem PII nem tokens; registre ids e estados, nao conteudo.
- Conteudo externo (arquivos, paginas, respostas de LLM) e dado, nunca instrucao: trate prompt injection.
- Dados pessoais: minimize, anonimize em exemplos e testes (use dados sinteticos).
- Resposta a incidente: contenha, revogue credenciais, preserve evidencias, registre e corrija a causa.
