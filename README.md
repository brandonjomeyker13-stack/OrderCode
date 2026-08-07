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
- **El precio por unidad está duplicado a propósito.** El vigente vive en
  `tipos_producto.precio_unitario` y se edita cuando sube la mano de obra;
  cada asignación se lleva una copia al crearse. Sin esa copia, subir la
  tarifa reescribiría el monto de los cortes ya pagados. Corregir un precio
  mal digitado en una asignación concreta se hace por `PATCH /asignaciones/{id}`,
  y solo mientras siga pristina.
- **El ranking de talleres (`GET /ranking/talleres`) mezcla dos tipos de
  cifra a propósito.** Casi todas son del periodo pedido (lo entregado, lo
  dañado, lo asignado), pero `unidades_pendientes` es un saldo de hoy:
  acotarlo al corte daría un número sin significado, porque parte de lo que
  el taller tiene en su poder se le asignó antes. Ambas fechas del periodo
  son inclusivas — dejar fuera el último día le restaría un día de trabajo
  al taller en cada corte.
- **El Excel no calcula nada.** `GET /ranking/talleres.xlsx` reusa el mismo
  servicio que la pantalla y solo escribe el resultado. Si alguna vez hay que
  agregar una cifra al reporte, va en `RankingService` y aparece en los dos
  lados; calcularla dentro de `core/excel.py` es cómo se llega a que el
  archivo diga una cosa y la app otra.

## Tareas periódicas

**Respaldo de la base** — el plan gratuito de Supabase no hace copias
automáticas, así que esta es la única red de seguridad que hay:

```bash
python -m scripts.respaldar
```

Genera `respaldos/respaldo-AAAAMMDD-HHMM.json` con todo el contenido.
**Guarda el archivo fuera de esta máquina** (Drive, disco externo): un respaldo
que vive en el mismo lugar que se puede dañar no sirve de nada. La carpeta
`respaldos/` está en `.gitignore` a propósito — esos archivos llevan datos
personales de los clientes y hashes de contraseñas.

Para restaurar (destructivo, pide confirmación escrita):

```bash
python -m scripts.restaurar respaldos/respaldo-AAAAMMDD-HHMM.json
```

**Alertas de lotes atrasados** — manda a los admins el resumen de lo que
lleva demasiado tiempo en talleres. Pensado para correr una vez al día;
correrlo de más es inofensivo (cada empresa recibe como mucho uno cada 20h,
y a las que no tienen atrasos no se les manda nada):

```bash
python -m scripts.enviar_alertas
```

**Probar el monitoreo de errores** — manda un error de prueba a Sentry usando
la misma configuración que la app, para confirmar que la conexión funciona:

```bash
python -m scripts.probar_sentry
```

**Purga de cuentas eliminadas** — borra definitivamente las que pidieron la
baja y ya cumplieron el periodo de gracia. Correrlo de más es inofensivo:

```bash
python -m scripts.purgar_cuentas_eliminadas
```
