# app/models/enums.py
import enum


class RolUsuario(str, enum.Enum):
    ADMIN = "admin"
    OPERADOR = "operador"


class EstadoLote(str, enum.Enum):
    PENDIENTE_ASIGNACION = "pendiente_asignacion"
    ASIGNADO_A_TALLER = "asignado_a_taller"
    ENTREGADO_PARCIAL = "entregado_parcial"
    ENTREGADO_COMPLETO = "entregado_completo"
    EN_REVISION_INCIDENCIA = "en_revision_incidencia"
    CERRADO_CLIENTE = "cerrado_cliente"


class EstadoAsignacion(str, enum.Enum):
    ASIGNADO = "asignado"
    ENTREGADO_PARCIAL = "entregado_parcial"
    ENTREGADO_COMPLETO = "entregado_completo"


class TipoIncidencia(str, enum.Enum):
    PRODUCTO_DANADO = "producto_danado"
    MATERIA_PRIMA_DANADA = "materia_prima_danada"
    OTRO = "otro"


class EstadoNotificacion(str, enum.Enum):
    ENVIADO = "enviado"
    FALLIDO = "fallido"