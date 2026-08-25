# tests/test_alertas.py
"""
Alertas de lotes atrasados: qué lleva demasiado tiempo en un taller sin
cerrarse. Lo que convierte la app de un registro pasivo en algo que avisa.
"""
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.models.empresa import Empresa
from app.models.enums import RolUsuario, TipoIncidencia
from app.models.lote import Lote
from app.models.taller import Taller
from app.models.usuario import Usuario
from app.schemas.asignacion_taller import (
    AsignacionTallerCreate,
    AsignacionTallerRegistrarDevolucion,
)
from app.schemas.incidencia import IncidenciaCreate
from app.services.alerta_service import AlertaService
from app.services.asignacion_taller_service import AsignacionTallerService
from app.services.incidencia_service import IncidenciaService

HOY = date(2026, 3, 1)
RUTA_CORREO = "app.services.alerta_service.enviar_email"


def _asignar(db: Session, empresa: Empresa, lote: Lote, taller: Taller, cantidad, dias_atras):
    return AsignacionTallerService(db).crear(
        empresa.id,
        AsignacionTallerCreate(
            lote_id=lote.id,
            taller_id=taller.id,
            cantidad_asignada=cantidad,
            fecha_asignacion=HOY - timedelta(days=dias_atras),
        ),
    )


# --- Detección ---

def test_sin_atrasos_no_hay_alertas(db: Session, empresa: Empresa, lote: Lote, taller: Taller):
    _asignar(db, empresa, lote, taller, 100, dias_atras=3)

    resumen = AlertaService(db).resumen(empresa.id, hoy=HOY)

    assert resumen.total_atrasadas == 0
    assert resumen.unidades_comprometidas == 0


def test_detecta_lo_que_pasa_el_umbral(db: Session, empresa: Empresa, lote: Lote, taller: Taller):
    _asignar(db, empresa, lote, taller, 100, dias_atras=20)

    resumen = AlertaService(db).resumen(empresa.id, hoy=HOY)

    assert resumen.total_atrasadas == 1
    assert resumen.atrasadas[0].dias_fuera == 20
    assert resumen.atrasadas[0].cantidad_pendiente == 100


def test_una_asignacion_cerrada_no_alerta(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    """Si el taller ya entregó todo, no hay nada que reclamar por más viejo
    que sea."""
    asignacion = _asignar(db, empresa, lote, taller, 100, dias_atras=40)
    AsignacionTallerService(db).registrar_devolucion(
        asignacion.id,
        empresa.id,
        AsignacionTallerRegistrarDevolucion(
            cantidad_devuelta=100, fecha_devolucion=datetime(2026, 2, 20, tzinfo=timezone.utc)
        ),
    )

    resumen = AlertaService(db).resumen(empresa.id, hoy=HOY)
    assert resumen.total_atrasadas == 0


def test_lo_pendiente_descuenta_devoluciones_y_merma(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    """La alerta debe decir cuánto falta DE VERDAD, no lo asignado original."""
    asignacion = _asignar(db, empresa, lote, taller, 200, dias_atras=30)
    IncidenciaService(db).crear(
        empresa.id,
        IncidenciaCreate(
            asignacion_id=asignacion.id,
            tipo=TipoIncidencia.PRODUCTO_DANADO,
            cantidad_afectada=20,
            descripcion="daño",
            fecha=date(2026, 2, 10),
        ),
    )
    AsignacionTallerService(db).registrar_devolucion(
        asignacion.id,
        empresa.id,
        AsignacionTallerRegistrarDevolucion(
            cantidad_devuelta=50, fecha_devolucion=datetime(2026, 2, 15, tzinfo=timezone.utc)
        ),
    )

    resumen = AlertaService(db).resumen(empresa.id, hoy=HOY)

    assert resumen.atrasadas[0].cantidad_pendiente == 130
    assert resumen.unidades_comprometidas == 130


def test_el_umbral_es_configurable_por_empresa(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    """Una confección tarda una semana y un mueble un mes: el mismo umbral
    para todos no sirve."""
    _asignar(db, empresa, lote, taller, 100, dias_atras=10)
    assert AlertaService(db).resumen(empresa.id, hoy=HOY).total_atrasadas == 0

    empresa.dias_alerta_atraso = 7
    db.commit()

    assert AlertaService(db).resumen(empresa.id, hoy=HOY).total_atrasadas == 1


def test_ordena_del_mas_atrasado_al_menos(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    _asignar(db, empresa, lote, taller, 10, dias_atras=20)
    _asignar(db, empresa, lote, taller, 10, dias_atras=60)
    _asignar(db, empresa, lote, taller, 10, dias_atras=35)

    resumen = AlertaService(db).resumen(empresa.id, hoy=HOY)

    assert [a.dias_fuera for a in resumen.atrasadas] == [60, 35, 20]
    assert resumen.dias_del_mas_atrasado == 60


def test_no_mezcla_atrasos_de_otra_empresa(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    _asignar(db, empresa, lote, taller, 100, dias_atras=30)
    otra = Empresa(nombre="Vecina", activo=True)
    db.add(otra)
    db.commit()

    assert AlertaService(db).resumen(otra.id, hoy=HOY).total_atrasadas == 0


# --- Resumen por correo ---

def test_manda_el_resumen_a_los_admins(
    db: Session, empresa: Empresa, admin: Usuario, lote: Lote, taller: Taller
):
    _asignar(db, empresa, lote, taller, 100, dias_atras=30)

    with patch(RUTA_CORREO) as correo:
        enviados = AlertaService(db).enviar_resumenes_pendientes(hoy=HOY)

    assert enviados == [empresa.id]
    correo.assert_called_once()
    assert correo.call_args.args[0] == admin.email


def test_sin_atrasos_no_manda_nada(
    db: Session, empresa: Empresa, admin: Usuario, lote: Lote, taller: Taller
):
    """Un correo diario diciendo "todo bien" entrena a la gente a ignorarlos,
    y entonces tampoco leen el que sí importa."""
    _asignar(db, empresa, lote, taller, 100, dias_atras=2)

    with patch(RUTA_CORREO) as correo:
        enviados = AlertaService(db).enviar_resumenes_pendientes(hoy=HOY)

    assert enviados == []
    correo.assert_not_called()


def test_no_repite_el_resumen_el_mismo_dia(
    db: Session, empresa: Empresa, admin: Usuario, lote: Lote, taller: Taller
):
    """Correr el script dos veces no debe mandar dos correos."""
    _asignar(db, empresa, lote, taller, 100, dias_atras=30)
    servicio = AlertaService(db)

    with patch(RUTA_CORREO) as correo:
        servicio.enviar_resumenes_pendientes(hoy=HOY)
        servicio.enviar_resumenes_pendientes(hoy=HOY)

    assert correo.call_count == 1


def test_vuelve_a_avisar_al_dia_siguiente(
    db: Session, empresa: Empresa, admin: Usuario, lote: Lote, taller: Taller
):
    _asignar(db, empresa, lote, taller, 100, dias_atras=30)
    servicio = AlertaService(db)

    with patch(RUTA_CORREO) as correo:
        servicio.enviar_resumenes_pendientes(hoy=HOY)
        empresa.ultima_alerta_at = datetime.now(timezone.utc) - timedelta(days=1)
        db.commit()
        servicio.enviar_resumenes_pendientes(hoy=HOY)

    assert correo.call_count == 2


def test_no_avisa_a_empresas_pausadas(
    db: Session, empresa: Empresa, admin: Usuario, lote: Lote, taller: Taller
):
    """Si no pagó, no se le sigue prestando el servicio -- tampoco el de
    avisarle."""
    _asignar(db, empresa, lote, taller, 100, dias_atras=30)
    empresa.activo = False
    db.commit()

    with patch(RUTA_CORREO) as correo:
        assert AlertaService(db).enviar_resumenes_pendientes(hoy=HOY) == []
    correo.assert_not_called()


# --- Cuando el correo no sale ---

def test_si_no_sale_ningun_correo_no_se_marca_como_avisada(
    db: Session, empresa: Empresa, admin: Usuario, lote: Lote, taller: Taller
):
    """`enviar_email` devuelve False si Resend falla o si falta la clave.

    Antes se marcaba la empresa como avisada pase lo que pase, así que ese
    fallo se comía la ventana de 20 horas y el aviso del día se perdía en
    silencio. Fue justo lo que pasó en producción: el log decía "enviado a 1
    empresa" sin haber mandado nada.
    """
    _asignar(db, empresa, lote, taller, 100, dias_atras=30)

    with patch(RUTA_CORREO, return_value=False):
        enviados = AlertaService(db).enviar_resumenes_pendientes(hoy=HOY)

    assert enviados == []
    assert empresa.ultima_alerta_at is None, "se quemó la ventana sin haber enviado"


def test_reintenta_en_la_corrida_siguiente_si_fallo(
    db: Session, empresa: Empresa, admin: Usuario, lote: Lote, taller: Taller
):
    """La consecuencia práctica del arreglo: un fallo pasajero no cuesta el
    aviso del día. La siguiente corrida vuelve a intentarlo."""
    _asignar(db, empresa, lote, taller, 100, dias_atras=30)

    with patch(RUTA_CORREO, return_value=False):
        AlertaService(db).enviar_resumenes_pendientes(hoy=HOY)

    with patch(RUTA_CORREO, return_value=True) as correo:
        enviados = AlertaService(db).enviar_resumenes_pendientes(hoy=HOY)

    assert enviados == [empresa.id]
    correo.assert_called_once()


def test_basta_con_que_le_llegue_a_un_admin(
    db: Session, empresa: Empresa, admin: Usuario, lote: Lote, taller: Taller
):
    """Con varios administradores, que uno de los correos rebote no puede
    dejar a los demás sin aviso ni disparar un reintento innecesario."""
    segundo = Usuario(
        empresa_id=empresa.id,
        nombre="Segundo Admin",
        email="segundo@prueba.com",
        password_hash=admin.password_hash,
        rol=RolUsuario.ADMIN,
    )
    db.add(segundo)
    db.commit()
    _asignar(db, empresa, lote, taller, 100, dias_atras=30)

    with patch(RUTA_CORREO, side_effect=[False, True]):
        enviados = AlertaService(db).enviar_resumenes_pendientes(hoy=HOY)

    assert enviados == [empresa.id]
    assert empresa.ultima_alerta_at is not None
