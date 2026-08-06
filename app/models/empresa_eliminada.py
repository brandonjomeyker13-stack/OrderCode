# app/models/empresa_eliminada.py
from datetime import datetime

from sqlalchemy import DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class EmpresaEliminada(Base, TimestampMixin):
    """
    Rastro mínimo y ANONIMIZADO de una empresa ya purgada.

    Existe por el deber legal de conservar soportes contables (Código de
    Comercio: 10 años) aunque el titular ejerza su derecho de supresión:
    la Ley 1581 permite negar el borrado cuando hay un deber legal de
    conservación. La forma de cumplir ambos es esta -- se borra todo lo
    personal e identificable y queda solo lo económico/estadístico.

    REGLA: aquí NO va nada que identifique a una persona. Ni nombres, ni
    correos, ni teléfonos, ni el nombre de la empresa. Si algún día se
    agrega facturación, los montos sí pueden vivir acá; los datos del
    titular no.
    """
    __tablename__ = "empresas_eliminadas"

    id: Mapped[int] = mapped_column(primary_key=True)
    # El id de la empresa original, sin FK: la fila de `empresas` ya no
    # existe, y esto es solo una referencia histórica para cuadrar cuentas.
    empresa_id_original: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    fecha_alta: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fecha_solicitud_eliminacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    fecha_purga: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
