# OrdersCode — API

Backend de la plataforma de gestión de producción tercerizada: una empresa
registra lotes de producto, los asigna a talleres externos, y controla lo que
vuelve (devoluciones) y lo que se pierde en el camino (merma).

Multi-empresa: cada cliente ve únicamente sus propios datos.

## Puesta en marcha

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt -r requirements-dev.txt
copy .env.example .env         # y rellenar los valores
alembic upgrade head
uvicorn app.main:app --reload
```

Con `ENVIRONMENT=development`, la documentación interactiva queda en
http://localhost:8000/docs (en producción se oculta a propósito).

## Tests

```bash
pytest
```

Corren contra SQLite en memoria, no tocan ninguna base real, y no necesitan
configuración adicional más allá del `.env`. Se ejecutan solos en cada push
(ver `.github/workflows/tests.yml`).

## Migraciones

El esquema se versiona con Alembic. **Nunca se modifica la base a mano.**

```bash
alembic revision --autogenerate -m "qué cambió"   # tras tocar un modelo
alembic upgrade head                              # aplicar
```

Revisa siempre el archivo generado antes de aplicarlo: autogenerate acierta
casi siempre, pero no adivina renombres ni migraciones de datos.

> En una base que ya tenía las tablas creadas a mano antes de adoptar Alembic,
> el primer paso es `alembic stamp a13f7a3aca7a` (marcar como al día), no
> `upgrade`. Ver la nota dentro de esa revisión.

## Cómo está organizado

```
app/
  api/v1/endpoints/   HTTP: validar entrada, delegar, devolver
  services/           Reglas de negocio (dónde vive el "por qué")
  repositories/       Acceso a datos
  models/             Tablas (SQLAlchemy)
  schemas/            Contratos de entrada/salida (Pydantic)
  core/               Config, seguridad, y clientes externos (correo, WhatsApp, PDF)
```

**Regla de oro del aislamiento entre empresas:** todo método de repositorio que
lea o escriba una fila exige `empresa_id` como parámetro obligatorio. Esa es la
barrera que impide que un cliente vea datos de otro, y no depende de que el
endpoint se acuerde de filtrar. La única excepción documentada es buscar un
usuario por email al iniciar sesión, que ocurre antes de saber a qué empresa
pertenece.

## Cosas que conviene saber antes de tocar el código

- **El `empresa_id` nunca se lee del body ni de la query.** Sale siempre del
  token de sesión (`get_empresa_id`). Aceptarlo del cliente permitiría pedir
  datos de otra empresa cambiando un número.
- **`empresas.activo` es el interruptor de cobro** y se activa a mano en la
  base. A propósito no se puede cambiar por la API: si se pudiera, el admin de
  una empresa pausada por falta de pago se reactivaría solo.
- **Los envíos de correo y WhatsApp son best-effort.** Si fallan, se registran
  y el flujo de negocio continúa: crear una asignación no puede depender de que
  Meta responda.
- **La merma no devuelve stock.** Las unidades dañadas salen de lo pendiente
  del taller, pero no vuelven a estar disponibles en el lote.

## Tareas periódicas

```bash
python -m scripts.purgar_cuentas_eliminadas
```

Borra definitivamente las cuentas que pidieron la baja y ya cumplieron el
periodo de gracia. Correrlo de más es inofensivo.
