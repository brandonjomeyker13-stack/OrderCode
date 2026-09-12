# app/models/enums.py
import enum


class RolUsuario(str, enum.Enum):
    """Quién es quién en la planta.

    No son niveles de privilegio sino PUESTOS: cada uno hace una parte del
    flujo y no le toca la del otro. La separación entre CORTE y BODEGA es
    además el control central del producto -- quien manda al taller no es
    quien cuenta lo que vuelve -- así que fundirlos rompería la razón de ser
    de la aplicación, no solo los permisos.
    """

    ADMIN = "admin"
    #: Registra el corte, cuenta lo que sale y lo asigna a los talleres.
    CORTE = "corte"
    #: Recibe lo que devuelven los talleres y lo cuenta A CIEGAS.
    BODEGA = "bodega"
    #: Ve qué hay listo para vender y registra las salidas.
    VENTAS = "ventas"


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


class EstadoConteo(str, enum.Enum):
    """En qué punto está lo que bodega contó.

    Son dos y no tres a propósito: no hay "rechazado". Si la cifra no cuadra,
    corte no rechaza nada -- llama a bodega, hablan, y bodega corrige su
    propio reporte. Un estado de rechazo convertiría una conversación de dos
    minutos en un trámite, y dejaría filas muertas que nadie vuelve a mirar.
    """

    #: Bodega ya contó y lo dejó anotado. Todavía no descuenta nada.
    REPORTADO = "reportado"
    #: Corte lo dio por bueno. En este momento nació la Devolucion.
    CONFIRMADO = "confirmado"


class TipoIncidencia(str, enum.Enum):
    PRODUCTO_DANADO = "producto_danado"
    MATERIA_PRIMA_DANADA = "materia_prima_danada"
    OTRO = "otro"


class EstadoNotificacion(str, enum.Enum):
    ENVIADO = "enviado"
    FALLIDO = "fallido"


class CanalNotificacion(str, enum.Enum):
    """Por dónde se le mandó la ficha técnica al taller. WhatsApp es el
    preferido (los talleres lo revisan más), el correo es el respaldo."""
    WHATSAPP = "whatsapp"
    CORREO = "correo"