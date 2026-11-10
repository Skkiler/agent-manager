# ADR-014 — Dados do usuário fora do Git, menu de preferências e política de pastas

- Status: aceito
- Contexto: o repositório é público e o orquestrador aprende com o uso (memória, notas, credenciais, integrações, permissões).
  Código e lógica precisam subir ao Git; tudo que é do usuário não pode. Além disso, as ferramentas de arquivo dependiam de uma
  variável de ambiente (`APP_TOOLS_ROOTS`) sem lista de pastas proibidas, e as opções estavam espalhadas.
- Decisões:
  1. **Perfil de usuário fora do repositório** (`forja/usuario/layout.py`): `<base>/perfis/<perfil>/{credenciais,dados,notas,ferramentas,config,artefatos,logs,workspace,backups}`.
     Base = `APP_USER_HOME` ou a pasta de dados do SO (Windows: `%LOCALAPPDATA%\Forja`); perfil = `APP_PROFILE` ou o usuário do SO.
     O servidor **recusa** iniciar com dados dentro do repositório se o Git não os ignorar. `APP_DATA_DIR`/`APP_LOG_DIR` explícitos continuam valendo (testes).
  2. **Modo legado** (existe `./data/forja.sqlite3` e não há `data/MIGRADO.txt`): continua usando `./data` com aviso. A migração
     (`scripts/migrar_dados_usuario.py`) é cópia **não destrutiva**, com simulação por padrão e `--executar` explícito; nunca apaga a origem.
  3. **Credenciais**: `<perfil>/credenciais/.env` tem prioridade sobre o `.env` do repositório; tokens continuam só em variáveis de ambiente.
  4. **Registro declarativo de preferências** (`forja/preferencias/registro.py`): cada opção tem categoria, nível geral/avançado, explicação,
     exemplos (baixo/médio/alto), consequências de ligar/desligar e risco. O mesmo registro valida no servidor e desenha o menu. Valores ficam
     no perfil; eventos carregam só IDs (valores podem ser caminhos pessoais). Escrita versionada (concorrência otimista).
  5. **Política de pastas** (`forja/seguranca/pastas.py`): leitura de arquivos **desligada no código**; o usuário liga e escolhe pastas permitidas e
     proibidas pela tela. Proibida vence permitida. São sempre protegidos (não liberáveis): os dados do próprio perfil e qualquer `.git`.
     Raiz de disco é recusada. A checagem vale para caminhos pedidos e para percursos de diretório, com a mesma mensagem genérica (sem oráculo de existência).
  6. **Limite de requisições configurável**; arquivos estáticos do painel não contam por padrão.
- Rejeitado: copiar/mover dados automaticamente; dividir o banco em vários arquivos; configurar só por variáveis de ambiente; permitir liberar `.git` ou o perfil.
- Consequências: a pasta do perfil precisa de backup próprio (não está no Git); trocar de computador exige copiar o perfil.
  Reescrever o histórico do Git (e-mail do autor) é decisão separada e destrutiva, não feita aqui.
