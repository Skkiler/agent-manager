# Arquitetura em camadas (projetos Python)

Conhecimento generico e publico. Nao contem codigo, nomes ou regras de nenhuma empresa.

## Estrutura de pastas recomendada
- `api/`: rotas e contratos HTTP. Sem regra de negocio; so valida entrada, chama um servico e formata a saida.
- `app/` ou `servicos/`: casos de uso e regras de negocio. Nao conhece HTTP nem detalhes de banco.
- `core/` ou `dominio/`: entidades, contratos tipados e regras puras, sem I/O.
- `adapters/`: acesso externo (banco, filas, CLIs, APIs de terceiros) atras de interfaces.
- `config/`: unico ponto que le variaveis de ambiente; o resto recebe configuracao por parametro.
- `utils/`: funcoes pequenas e puras reutilizaveis.
- `cli/`: pontos de entrada de linha de comando, finos, chamando servicos.
- `tests/`, `data/` (ignorado pelo Git), `logs/` (ignorado pelo Git).

## Regras
- Dependencias apontam para dentro: api -> servicos -> dominio; adapters implementam interfaces do dominio.
- Uma unica leitura de ambiente; segredos nunca no Git, nem em logs.
- Rotas nao acessam banco diretamente; servicos nao importam framework web.
- Cada camada e testavel sozinha, com adapters falsos.

## Sinais de violacao
Rota com SQL, servico lendo `os.environ`, dominio importando biblioteca de rede, funcao com mais de uma responsabilidade.
