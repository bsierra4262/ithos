# Guía de contribución

Convenciones del proyecto **ITHOS**.

## Flujo de trabajo

1. Crear una rama desde `main`: `git checkout -b feat/mi-cambio`.
2. Realizar cambios atómicos y acompañados de tests.
3. Ejecutar las baterías antes de abrir el Pull Request: `python tests/probar_requerimientos.py`
   (115 requerimientos transversales, sin red) y `python tests/probar_todo.py`.
4. Abrir un Pull Request describiendo el qué y el porqué del cambio.

## Mensajes de commit — [Conventional Commits](https://www.conventionalcommits.org/es/)

```
<tipo>(ámbito opcional): <descripción en imperativo, minúscula, sin punto>
```

Tipos: `feat`, `fix`, `docs`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`.

Ejemplos:

```
feat(planka): rollover mensual por bloques con archivo MENSUAL
fix(triage): no re-categoriza un ticket asignado a mano por el técnico
docs(readme): agrega diagrama de arquitectura
test(rollover): regresión del arrastre de tarjetas al cambiar de mes
```

## Reglas del proyecto

- **Cada defecto detectado incorpora un test de regresión** (en `tests/`) que falle con el bug
  y pase con el arreglo, para impedir su reaparición.
- **Sin secretos ni datos reales en el repositorio.** Las credenciales se piden al instalar y
  se cargan en `clientes.json`/`.env` (ver [`.gitignore`](.gitignore) y [SECURITY.md](SECURITY.md)).
- **Cada cambio se aplica en todo por igual**: todos los proveedores de IA, todos los canales
  y todos los sistemas integrados. Nada que funcione en uno y no en otro.
- **Multiplataforma**: rutas portables (`pathlib`), codificación UTF-8 explícita, sin
  dependencias atadas a un sistema operativo.

## Estilo

- Python 3.11+, PEP 8, indentación de 4 espacios. Código legible de nivel senior.
- Validar antes de commitear: `python -m py_compile <archivos>` y la batería de `tests/`.
- Mantener la documentación al día: `README.md`, `DOCUMENTO_MAESTRO.md`, los `docs/*.md`
  relevantes y los `requirements.txt` ante cualquier cambio que lo amerite.
