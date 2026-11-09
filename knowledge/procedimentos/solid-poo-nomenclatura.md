# SOLID, orientacao a objetos e nomenclatura

## SOLID em pratica
- Responsabilidade unica: uma classe ou funcao muda por um unico motivo.
- Aberto/fechado: estenda por novas implementacoes de uma interface, nao editando condicionais longas.
- Substituicao de Liskov: subtipos honram o contrato do tipo base (mesmas pre e pos-condicoes).
- Segregacao de interfaces: interfaces pequenas e focadas; ninguem depende de metodos que nao usa.
- Inversao de dependencia: servicos dependem de abstracoes (Protocol/ABC), injetadas no construtor.

## POO
- Prefira composicao a heranca. Use heranca so para relacao "e um" estavel.
- Encapsule estado; exponha comportamento, nao atributos soltos.
- Objetos de valor imutaveis (dataclass frozen / Pydantic) para contratos.

## Nomenclatura (Python)
- `snake_case` para funcoes, variaveis e modulos; `PascalCase` para classes; `UPPER_SNAKE` para constantes.
- Nomes dizem intencao (`calcular_total_pedido`, nao `proc2`). Booleanos como pergunta (`esta_ativo`).
- Tipagem em assinaturas publicas; docstring curta explicando o porque, nao o como.
