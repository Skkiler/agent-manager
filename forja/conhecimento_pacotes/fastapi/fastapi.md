---
titulo: FastAPI
pai: Python
tags: fastapi, api, web
tipo: semantica
relacionados: Tipagem e contratos em Python
---
Framework web ASGI que usa anotações de tipo para validar entrada, serializar saída e gerar o OpenAPI automaticamente.
Subtópicos: [[Injeção de dependências no FastAPI]], [[Validação com Pydantic no FastAPI]], [[Ciclo de vida (lifespan) no FastAPI]],
[[Testes de API com TestClient]] e [[Segurança de APIs FastAPI]].
Regra prática: rotas finas (só traduzem HTTP), regras no serviço, persistência no repositório.
+++
---
titulo: Injeção de dependências no FastAPI
pai: FastAPI
tags: fastapi, dependencias
tipo: procedimental
---
- `Depends(fn)` resolve a dependência por requisição; dependências podem depender de outras (árvore cacheada por requisição).
- Use `Annotated[Tipo, Depends(fn)]` para reaproveitar a mesma dependência em várias rotas sem repetir.
- Dependência com `yield` faz limpeza depois da resposta (ex.: fechar sessão de banco).
- Em testes, troque com `app.dependency_overrides[fn] = falso` em vez de monkeypatch.
- Autenticação como dependência no `APIRouter(dependencies=[...])` vale para todas as rotas do router.
+++
---
titulo: Validação com Pydantic no FastAPI
pai: FastAPI
tags: fastapi, pydantic, validacao
tipo: procedimental
---
- Corpo, query e path são validados pelos tipos; erro vira HTTP 422 com o campo exato.
- `model_config = ConfigDict(extra="forbid")` recusa campos desconhecidos (evita mass assignment).
- Limite tamanhos com `Field(max_length=...)`, `Query(le=...)` e `Path(pattern=...)` na fronteira de confiança.
- Separe modelos de entrada e de saída: nunca devolva o modelo do banco direto (vaza campos internos).
+++
---
titulo: Ciclo de vida (lifespan) no FastAPI
pai: FastAPI
tags: fastapi, lifespan
tipo: procedimental
---
- `FastAPI(lifespan=fn)` com `@asynccontextmanager`: o código antes do `yield` roda na subida, o depois no encerramento.
- Abra pools, migre o banco e inicie tarefas de fundo na subida; feche tudo no encerramento (desligamento gracioso).
- Guarde serviços em `app.state` e leia nas rotas via `request.app.state` ou dependências.
- Os eventos antigos `on_startup`/`on_shutdown` estão obsoletos.
+++
---
titulo: Testes de API com TestClient
pai: FastAPI
tags: fastapi, testes, pytest
tipo: procedimental
relacionados: Pirâmide de testes
---
- `with TestClient(app) as c:` executa o lifespan (subida e encerramento) dentro do teste.
- Teste o contrato HTTP (status, corpo, cabeçalhos) e deixe regras para testes do serviço, mais rápidos.
- Use banco temporário por teste (cópia de um banco já migrado acelera muito a suíte).
- Para chamadas externas, use `httpx.MockTransport` em vez de rede real.
+++
---
titulo: Segurança de APIs FastAPI
pai: FastAPI
tags: fastapi, seguranca, api
tipo: procedimental
---
- Autenticação por dependência; compare tokens com `hmac.compare_digest` (tempo constante).
- Valide o cabeçalho Host e a Origin em métodos que alteram estado (proteção contra DNS rebinding e CSRF).
- Limite a taxa por cliente e o tamanho das requisições; nunca devolva stack trace (handler de exceção próprio).
- Docs interativas (`/docs`) expõem o esquema: proteja ou desligue em produção.
