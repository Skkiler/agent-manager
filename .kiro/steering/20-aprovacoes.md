# Pedidos de autorização: por ação, agrupados, com adendo

- Peça autorização pela **ação**, em linguagem natural, não pelo comando bruto. Ex.: em vez de `rm -rf dist build`,
  pergunte "Posso excluir forçadamente as pastas `dist` e `build`?".
- **Agrupe**: se x, y e z são necessários, faça UM pedido com os três itens e deixe o usuário aprovar todos, alguns ou nenhum.
  Evite pedir permissão individual para cada passo de uma mesma ação.
- Permita **adendos**: toda autorização aceita uma observação livre do usuário; registre-a e a respeite.
- Peça uma vez e reaproveite a decisão dentro da mesma tarefa quando a ação for idêntica.
- Nunca peça (nem execute) ações que leiam ou exponham segredos, `.env`, chaves ou dados privados: recuse e explique.
- Ações de alto risco (exclusão forçada, publicar, descartar alterações) devem declarar o risco e o que será afetado.
