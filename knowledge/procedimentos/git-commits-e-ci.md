# Git, commits convencionais, CI e DevOps

## Conventional Commits
Formato: `tipo(escopo): resumo no imperativo`. Tipos: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`, `ci`.
Corpo explica o porque; rodape `BREAKING CHANGE:` quando houver quebra de compatibilidade.
Um commit = uma mudanca logica. Nunca commitar segredos, bancos locais ou logs.

## Branches e revisao
Trabalhe em branch curta; PR pequeno com descricao do que mudou e do que foi testado. Nada de force push em `main`.

## Pipeline de CI minimo
1. instalar dependencias com versoes fixas; 2. lint (ruff); 3. testes (pytest) com cobertura; 4. varredura de segredos;
5. build/empacotamento. Falha em qualquer etapa bloqueia o merge.

## Deploy
Somente com aprovacao explicita; ambientes separados; configuracao por variavel de ambiente; rollback documentado.
Infra como codigo versionada; alteracao em producao nunca manual e sem registro.
