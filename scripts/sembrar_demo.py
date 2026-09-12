"""
Crea una empresa de demostración con datos realistas, para enseñar el producto.

    python -m scripts.sembrar_demo              # la crea
    python -m scripts.sembrar_demo --rehacer    # la borra y la vuelve a crear
    python -m scripts.sembrar_demo --borrar     # solo la borra
    ... --forzar                                # sin pedir confirmación

Por qué existe: con los datos reales de hoy, el ranking sale en ceros y con el
aviso rojo de "sin tarifa", porque las asignaciones viejas son anteriores a
que existieran los precios. Delante de un cliente potencial eso se ve como un
producto roto, aunque sea el comportamiento correcto.

Las fechas se calculan hacia atrás desde HOY, así que la demo nunca se ve
vieja: siempre muestra los últimos dos meses de "producción".

SOLO toca la empresa cuyo nombre coincide exactamente con NOMBRE_DEMO. No
puede tocar datos de un cliente real por accidente.
"""
import logging
import secrets
import sys
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, func, select

from app.core.config import settings
from app.core.fechas import hoy_local, zona
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.asignacion_taller import AsignacionTaller
from app.models.devolucion import Devolucion
from app.models.empresa import Empresa
from app.models.enums import (
    EstadoAsignacion,
    EstadoLote,
    RolUsuario,
    TipoIncidencia,
)
from app.models.incidencia import Incidencia
from app.models.lote import Lote
from app.models.notificacion_leida import NotificacionLeida
from app.models.password_reset_token import PasswordResetToken
from app.models.qr_code import QRCode
from app.models.refresh_token import RefreshToken
from app.models.taller import Taller
from app.models.tipo_producto import TipoProducto
from app.models.usuario import Usuario
from app.services.asignacion_taller_service import recalcular_estado_asignacion
from app.services.empresa_service import EmpresaService

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("demo")

NOMBRE_DEMO = "Confecciones Andina S.A.S."
EMAIL_ADMIN = "demo@orderscode.com"
EMAIL_OPERARIO = "operario@orderscode.com"

# Palabra que hay que escribir para confirmar un borrado, igual que en
# scripts/restaurar.py.
CONFIRMACION = "BORRAR"

# (nombre, número, teléfono, correo, dirección, sigue activo)
_TALLERES = (
    ("Confecciones El Sol", "001", "3151234567", "elsol@correo.com", "Av. 4 #12-45", True),
    ("Taller Marisol Ríos", "002", "3157654321", "marisol@correo.com", "Cl. 9 #3-21", True),
    ("Maquilas del Norte", "003", "3159876543", None, "Km 3 vía Pamplona", True),
    ("Taller La Esperanza", "004", "3152223344", "esperanza@correo.com", None, True),
    ("Taller Nuevo Amanecer", "005", "3155556677", None, "Barrio La Libertad", True),
    # Inactivo pero con movimiento: aparece marcado en el ranking porque se le
    # puede deber plata del corte anterior a haberlo dado de baja.
    ("Costuras Vélez", "006", "3158889900", None, None, False),
)

# (nombre, referencia, precio por unidad)
_PRODUCTOS = (
    ("Legging deportivo tiro alto", "LEG-001", "4200"),
    ("Biker short compresión", "BIK-002", "3800"),
    ("Top deportivo espalda cruzada", "TOP-003", "3200"),
    ("Vestido casual en punto", "VES-004", "6500"),
    ("Camiseta básica algodón", "CAM-005", "2600"),
)

# Cada lote: (producto, cantidad, días atrás en que se registró, asignaciones)
# Cada asignación: (taller, cantidad, días atrás, [(días atrás, cantidad)], merma)
#
# El reparto está pensado para que el ranking cuente una historia clara:
#   El Sol      -> mucho volumen, poca merma, rápido        (el mejor)
#   Marisol     -> volumen medio, muy limpio                (el más confiable)
#   Del Norte   -> merma alta                               (el problema de calidad)
#   La Esperanza-> un lote sin entregar hace 40 días        (dispara la alerta)
#   Amanecer    -> recién asignado, sin entregar todavía    (sin promedio de días)
#   Vélez       -> entregó y después se dio de baja         (inactivo con plata)
_PRODUCCION = (
    (0, 1200, 62, (
        (0, 500, 60, ((54, 260), (48, 240)), 0),
        (1, 400, 60, ((52, 400),), 0),
        (5, 300, 58, ((50, 290),), 10),
    )),
    (1, 900, 45, (
        (0, 400, 44, ((38, 400),), 0),
        (2, 500, 44, ((36, 210), (30, 240)), 50),
    )),
    (2, 700, 34, (
        (0, 300, 32, ((26, 300),), 0),
        (1, 400, 32, ((25, 200), (19, 195)), 5),
    )),
    (3, 600, 26, (
        (3, 350, 40, (), 0),          # <- el atrasado: 40 días sin entregar nada
        (2, 250, 24, ((18, 130),), 20),
    )),
    (4, 1500, 20, (
        (0, 600, 18, ((12, 320), (6, 270)), 10),
        (1, 500, 18, ((10, 500),), 0),
        (4, 400, 4, (), 0),           # <- recién asignado, todavía sin entregas
    )),
    (0, 800, 12, (
        (0, 450, 11, ((5, 450),), 0),
        (2, 350, 11, ((4, 300),), 25),
    )),
)


def _instante(dias_atras: int) -> datetime:
    """Un momento a mediodía local, convertido a UTC.

    Mediodía y no medianoche a propósito: en Colombia (UTC-5) la medianoche
    local cae en el día anterior en UTC, y los cortes por fecha quedarían
    corridos un día en la demo.
    """
    dia = hoy_local() - timedelta(days=dias_atras)
    return datetime.combine(dia, time(12, 0), tzinfo=zona()).astimezone(timezone.utc)


def _fecha(dias_atras: int):
    return hoy_local() - timedelta(days=dias_atras)


def _destino_legible() -> str:
    """A qué base apunta, sin exponer la contraseña en pantalla."""
    url = settings.DATABASE_URL
    return url.split("@", 1)[1] if "@" in url else url


def _contenido_de(db, empresa_id: int) -> dict[str, int]:
    """Cuántas filas tiene esa empresa, para poder ENSEÑAR qué se va a borrar
    antes de borrarlo. Sin esto el script confía solo en el nombre, y el día
    que un cliente real se llame igual se lleva sus datos por delante."""
    conteos = {}
    for modelo in EmpresaService.ORDEN_DE_BORRADO:
        n = db.execute(
            select(func.count()).select_from(modelo).where(modelo.empresa_id == empresa_id)
        ).scalar_one()
        if n:
            conteos[modelo.__tablename__] = n
    usuarios = db.execute(
        select(func.count()).select_from(Usuario).where(Usuario.empresa_id == empresa_id)
    ).scalar_one()
    if usuarios:
        conteos["usuarios"] = usuarios
    return conteos


def _confirmar_borrado(db, empresa, forzar: bool) -> bool:
    """Muestra qué se va a borrar y pide confirmación escrita.

    Mismo criterio que scripts/restaurar.py: una operación destructiva no se
    ejecuta porque sí, se ejecuta porque alguien la leyó y la aceptó.
    """
    if forzar:
        return True

    conteos = _contenido_de(db, empresa.id)
    logger.warning("Vas a BORRAR la empresa '%s' (id %s) con todo su contenido:",
                   empresa.nombre, empresa.id)
    if conteos:
        for tabla, n in sorted(conteos.items()):
            logger.warning("    %-28s %s", tabla, n)
    else:
        logger.warning("    (vacía)")
    logger.warning("Base de datos: %s", _destino_legible())

    respuesta = input(f'\nEscribe "{CONFIRMACION}" para continuar: ').strip()
    if respuesta != CONFIRMACION:
        logger.info("Cancelado, no se tocó nada.")
        return False
    return True


def _borrar(db) -> bool:
    """Borra la empresa de demostración si existe. Devuelve si borró algo.

    Reusa el orden de borrado de EmpresaService para no repetirlo: si mañana
    se agrega una tabla nueva, esta función la hereda sola. No escribe el
    registro anonimizado de EmpresaEliminada porque esto no es una baja de
    cliente, es limpiar un juguete.
    """
    empresa = db.execute(
        select(Empresa).where(Empresa.nombre == NOMBRE_DEMO)
    ).scalars().first()
    if empresa is None:
        return False

    empresa_id = empresa.id
    for modelo in EmpresaService.ORDEN_DE_BORRADO:
        db.execute(delete(modelo).where(modelo.empresa_id == empresa_id))

    ids_usuarios = select(Usuario.id).where(Usuario.empresa_id == empresa_id)
    for modelo in (RefreshToken, PasswordResetToken, NotificacionLeida):
        db.execute(delete(modelo).where(modelo.usuario_id.in_(ids_usuarios)))

    empresa.usuario_propietario_id = None
    db.flush()
    db.execute(delete(Usuario).where(Usuario.empresa_id == empresa_id))
    db.delete(empresa)
    db.commit()
    return True


def _sembrar(db, clave: str) -> None:
    empresa = Empresa(nombre=NOMBRE_DEMO, activo=True)
    db.add(empresa)
    db.flush()

    admin = Usuario(
        empresa_id=empresa.id,
        nombre="Ana Gómez",
        email=EMAIL_ADMIN,
        password_hash=hash_password(clave),
        rol=RolUsuario.ADMIN,
        email_verificado=True,
    )
    operario = Usuario(
        empresa_id=empresa.id,
        nombre="Carlos Peña",
        email=EMAIL_OPERARIO,
        password_hash=hash_password(clave),
        rol=RolUsuario.CORTE,
        email_verificado=True,
    )
    db.add_all([admin, operario])
    db.flush()
    empresa.usuario_propietario_id = admin.id

    talleres = []
    for nombre, numero, telefono, correo, direccion, activo in _TALLERES:
        taller = Taller(
            empresa_id=empresa.id,
            nombre=nombre,
            numero_taller=numero,
            telefono=telefono,
            email=correo,
            direccion=direccion,
            activo=activo,
        )
        db.add(taller)
        talleres.append(taller)

    productos = []
    for nombre, referencia, precio in _PRODUCTOS:
        qr = QRCode(empresa_id=empresa.id, token=secrets.token_urlsafe(32))
        db.add(qr)
        db.flush()
        producto = TipoProducto(
            empresa_id=empresa.id,
            nombre=nombre,
            referencia=referencia,
            precio_unitario=Decimal(precio),
            qr_code_id=qr.id,
        )
        db.add(producto)
        productos.append(producto)
    db.flush()

    total_asignado = total_devuelto = total_merma = 0

    for idx_producto, cantidad_lote, dias_lote, asignaciones in _PRODUCCION:
        producto = productos[idx_producto]
        lote = Lote(
            empresa_id=empresa.id,
            tipo_producto_id=producto.id,
            cantidad_total=cantidad_lote,
            fecha_registro=_fecha(dias_lote),
            estado=EstadoLote.ASIGNADO_A_TALLER,
        )
        db.add(lote)
        db.flush()

        for idx_taller, cantidad, dias_asig, entregas, merma in asignaciones:
            asignacion = AsignacionTaller(
                empresa_id=empresa.id,
                lote_id=lote.id,
                taller_id=talleres[idx_taller].id,
                cantidad_asignada=cantidad,
                fecha_asignacion=_fecha(dias_asig),
                # Copia del precio vigente, igual que en el flujo real.
                precio_unitario=producto.precio_unitario,
                estado=EstadoAsignacion.ASIGNADO,
            )
            db.add(asignacion)
            db.flush()
            total_asignado += cantidad

            if merma:
                db.add(
                    Incidencia(
                        empresa_id=empresa.id,
                        asignacion_id=asignacion.id,
                        tipo=TipoIncidencia.PRODUCTO_DANADO,
                        cantidad_afectada=merma,
                        descripcion="Unidades con defecto de costura",
                        fecha=_fecha(max(dias_asig - 3, 0)),
                    )
                )
                total_merma += merma

            acumulado = 0
            ultima = None
            for dias_entrega, cantidad_entrega in entregas:
                momento = _instante(dias_entrega)
                db.add(
                    Devolucion(
                        empresa_id=empresa.id,
                        asignacion_id=asignacion.id,
                        cantidad=cantidad_entrega,
                        fecha=momento,
                    )
                )
                acumulado += cantidad_entrega
                ultima = momento
                total_devuelto += cantidad_entrega

            if acumulado:
                asignacion.cantidad_devuelta = acumulado
                asignacion.fecha_devolucion = ultima
            # Mismo cálculo de estado que usa el flujo real, para que la demo
            # no muestre estados que el sistema nunca produciría.
            recalcular_estado_asignacion(asignacion, merma)

        pendiente = any(
            a.estado != EstadoAsignacion.ENTREGADO_COMPLETO
            for a in db.execute(
                select(AsignacionTaller).where(AsignacionTaller.lote_id == lote.id)
            ).scalars()
        )
        lote.estado = (
            EstadoLote.ENTREGADO_PARCIAL if pendiente else EstadoLote.ENTREGADO_COMPLETO
        )

    db.commit()

    logger.info("")
    logger.info("Empresa de demostración creada: %s", NOMBRE_DEMO)
    logger.info("  talleres              %s", len(_TALLERES))
    logger.info("  productos             %s", len(_PRODUCTOS))
    logger.info("  lotes                 %s", len(_PRODUCCION))
    logger.info("  unidades asignadas    %s", total_asignado)
    logger.info("  unidades entregadas   %s", total_devuelto)
    logger.info("  unidades en merma     %s", total_merma)
    logger.info("")
    logger.info("Entra con:")
    logger.info("  admin     %s", EMAIL_ADMIN)
    logger.info("  operario  %s   (para mostrar que NO ve el ranking)", EMAIL_OPERARIO)
    logger.info("  clave     %s", clave)
    logger.info("")
    logger.info("Guarda esa clave: no se puede recuperar, solo cambiar.")


def main() -> int:
    argumentos = sys.argv[1:]
    rehacer = "--rehacer" in argumentos
    solo_borrar = "--borrar" in argumentos
    forzar = "--forzar" in argumentos

    clave = secrets.token_urlsafe(9)
    for arg in argumentos:
        if arg.startswith("--clave="):
            clave = arg.split("=", 1)[1]

    db = SessionLocal()
    try:
        if solo_borrar or rehacer:
            empresa = db.execute(
                select(Empresa).where(Empresa.nombre == NOMBRE_DEMO)
            ).scalars().first()
            if empresa is not None and not _confirmar_borrado(db, empresa, forzar):
                return 1
            if _borrar(db):
                logger.info("Empresa de demostración anterior borrada.")
            else:
                logger.info("No había empresa de demostración previa.")
            if solo_borrar:
                return 0

        existe = db.execute(
            select(Empresa.id).where(Empresa.nombre == NOMBRE_DEMO)
        ).scalars().first()
        if existe:
            logger.error(
                "Ya existe la empresa de demostración. Usa --rehacer para "
                "borrarla y volver a crearla desde cero."
            )
            return 1

        _sembrar(db, clave)
    except Exception:
        db.rollback()
        logger.exception("Falló la siembra. No se dejó nada a medias.")
        return 1
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
