# app/services/importacion_service.py
"""
Carga inicial de talleres y tipos de producto desde un Excel.

Dos pasos a propósito: primero se PREVISUALIZA (no escribe nada) y después se
CONFIRMA. Revisar tres filas malas antes de importar es trivial; deshacer
ochenta talleres mal creados no lo es -- un taller con historial de
asignaciones ni siquiera se puede borrar.

Y es todo o nada: si una sola fila tiene un problema, no se crea ninguna. Una
carga a medias deja al usuario adivinando qué entró y qué no.
"""
import secrets

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, ValidationError
from app.core.importacion import (
    HOJA_PRODUCTOS,
    HOJA_TALLERES,
    ArchivoLeido,
    Problema,
    leer_archivo,
    normalizar,
)
from app.models.qr_code import QRCode
from app.models.taller import Taller
from app.models.tipo_producto import TipoProducto
from app.repositories.taller_repository import TallerRepository
from app.repositories.tipo_producto_repository import TipoProductoRepository
from app.schemas.importacion import (
    ProblemaImportacion,
    ResultadoImportacion,
    ResumenImportacion,
)


class ImportacionService:
    def __init__(self, db: Session):
        self.db = db
        self.taller_repo = TallerRepository(db)
        self.tipo_repo = TipoProductoRepository(db)

    # --- Paso 1: mirar sin tocar ---

    def previsualizar(self, empresa_id: int, contenido: bytes) -> ResumenImportacion:
        leido = self._leer_y_validar(empresa_id, contenido)
        return self._resumir(leido)

    # --- Paso 2: escribir ---

    def confirmar(self, empresa_id: int, contenido: bytes) -> ResultadoImportacion:
        leido = self._leer_y_validar(empresa_id, contenido)
        resumen = self._resumir(leido)
        if not resumen.se_puede_importar:
            raise ValidationError(
                f"El archivo tiene {len(resumen.problemas)} problema(s) y no se importó nada. "
                f"Revisa la vista previa, corrige el archivo y vuelve a subirlo."
            )

        talleres = self._construir_talleres(empresa_id, leido)
        productos = self._construir_productos(empresa_id, leido)

        try:
            self.db.commit()
        except IntegrityError:
            # Otro admin importando al mismo tiempo pudo quedarse con un
            # número de taller o una referencia. Nadie ve una carga a medias.
            self.db.rollback()
            raise ConflictError(
                "Alguien más está cargando datos en este momento. Vuelve a intentarlo."
            )

        return ResultadoImportacion(
            talleres_creados=len(talleres), productos_creados=len(productos)
        )

    # --- Construcción, dentro de una sola transacción ---

    def _construir_talleres(self, empresa_id: int, leido: ArchivoLeido) -> list[Taller]:
        """Los números se calculan UNA vez y se van incrementando en memoria.

        TallerService.crear hace un commit por taller y recalcula el
        consecutivo cada vez: correcto para un alta suelta, inviable para
        ochenta filas que además deben entrar o no entrar juntas.
        """
        usados = [n for n in self.taller_repo.numeros_asignados(empresa_id) if n.isdigit()]
        siguiente = max((int(n) for n in usados), default=0) + 1

        talleres = []
        for fila in leido.talleres:
            talleres.append(
                Taller(
                    empresa_id=empresa_id,
                    numero_taller=f"{siguiente:03d}",
                    nombre=fila.nombre,
                    telefono=fila.telefono,
                    email=fila.email,
                    direccion=fila.direccion,
                )
            )
            siguiente += 1

        self.db.add_all(talleres)
        return talleres

    def _construir_productos(self, empresa_id: int, leido: ArchivoLeido) -> list[TipoProducto]:
        if not leido.productos:
            return []

        # Un QR por producto, todos de una vez: con un flush por fila serían
        # tantos viajes a la base como productos tenga el archivo.
        codigos = [
            QRCode(empresa_id=empresa_id, token=secrets.token_urlsafe(32))
            for _ in leido.productos
        ]
        self.db.add_all(codigos)
        self.db.flush()

        productos = [
            TipoProducto(
                empresa_id=empresa_id,
                nombre=fila.nombre,
                referencia=fila.referencia,
                qr_code_id=codigo.id,
            )
            for fila, codigo in zip(leido.productos, codigos)
        ]
        self.db.add_all(productos)
        return productos

    # --- Validaciones que necesitan la base ---

    def _leer_y_validar(self, empresa_id: int, contenido: bytes) -> ArchivoLeido:
        leido = leer_archivo(contenido)
        self._marcar_talleres_repetidos(empresa_id, leido)
        self._marcar_referencias_repetidas(empresa_id, leido)

        if not leido.problemas and not leido.talleres and not leido.productos:
            leido.problemas.append(
                Problema("", None, "El archivo no tiene ninguna fila con datos.")
            )
        return leido

    def _marcar_talleres_repetidos(self, empresa_id: int, leido: ArchivoLeido) -> None:
        """Bloquea los nombres repetidos, dentro del archivo y contra la base.

        Es más estricto que la base (que sí permite dos talleres con el mismo
        nombre) y es a propósito: quien sube dos veces el mismo archivo no
        quiere duplicados, se equivocó. Y como un taller con asignaciones ya
        no se puede borrar, el duplicado se queda para siempre.
        """
        ya_existen = {normalizar(n) for n in self.taller_repo.nombres_existentes(empresa_id)}
        vistos: dict[str, int] = {}

        conservados = []
        for fila in leido.talleres:
            clave = normalizar(fila.nombre)
            if clave in ya_existen:
                leido.problemas.append(
                    Problema(
                        HOJA_TALLERES,
                        fila.fila,
                        f"Ya tienes un taller llamado '{fila.nombre}'. Quita esta fila.",
                    )
                )
            elif clave in vistos:
                leido.problemas.append(
                    Problema(
                        HOJA_TALLERES,
                        fila.fila,
                        f"'{fila.nombre}' está repetido en el archivo "
                        f"(ya aparece en la fila {vistos[clave]}).",
                    )
                )
            else:
                vistos[clave] = fila.fila
                conservados.append(fila)

        leido.talleres = conservados

    def _marcar_referencias_repetidas(self, empresa_id: int, leido: ArchivoLeido) -> None:
        """La referencia sí tiene UNIQUE en la base. Se comprueba antes para
        poder decir en qué fila del Excel está el choque -- el error del
        commit no sabe nada de filas de Excel.

        La comparación ignora mayúsculas: la base dejaría convivir "REF-01" y
        "ref-01", pero para quien las lee son la misma y es un error seguro.
        """
        ya_existen = {r.strip().lower() for r in self.tipo_repo.referencias_existentes(empresa_id)}
        vistas: dict[str, int] = {}

        conservados = []
        for fila in leido.productos:
            clave = fila.referencia.strip().lower()
            if clave in ya_existen:
                leido.problemas.append(
                    Problema(
                        HOJA_PRODUCTOS,
                        fila.fila,
                        f"La referencia '{fila.referencia}' ya existe en tu cuenta. "
                        f"Quita esta fila o cámbiale la referencia.",
                    )
                )
            elif clave in vistas:
                leido.problemas.append(
                    Problema(
                        HOJA_PRODUCTOS,
                        fila.fila,
                        f"La referencia '{fila.referencia}' está repetida en el archivo "
                        f"(ya aparece en la fila {vistas[clave]}).",
                    )
                )
            else:
                vistas[clave] = fila.fila
                conservados.append(fila)

        leido.productos = conservados

    @staticmethod
    def _resumir(leido: ArchivoLeido) -> ResumenImportacion:
        problemas = [
            ProblemaImportacion(hoja=p.hoja, fila=p.fila, mensaje=p.mensaje)
            for p in leido.problemas
        ]
        # Ordenadas como en el Excel, para que el usuario las corrija de
        # arriba hacia abajo sin ir saltando por el archivo.
        problemas.sort(key=lambda p: (p.hoja, p.fila if p.fila is not None else 0))

        return ResumenImportacion(
            talleres_a_crear=len(leido.talleres),
            productos_a_crear=len(leido.productos),
            problemas=problemas,
            se_puede_importar=not problemas,
        )
