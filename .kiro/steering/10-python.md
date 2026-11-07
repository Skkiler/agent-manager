---
inclusion: fileMatch
fileMatchPattern: ["**/*.py", "**/pyproject.toml", "**/alembic.ini"]
---

# Python — engenharia modular

Use Python tipado, Pydantic/JSON Schema em interfaces, SQLAlchemy/Alembic apenas na persistência interna, `logging` estruturado, testes pytest e Ruff. Código de orquestração não mistura rotas HTTP, persistência e acesso a agentes. Evite execução de shell com interpolação de entrada não confiável. Alterações exigem teste e evidência. Não instale modelos locais como dependência obrigatória.
