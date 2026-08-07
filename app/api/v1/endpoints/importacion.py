# app/api/v1/endpoints/importacion.py
from fastapi import APIRouter, Depends, File, Response, UploadFile
from sqlalchemy.orm import Session

from app.api.v1.deps import get_empresa_id
from app.core.deps import require_admin
from app.core.exceptions import ValidationError
from app.core.importacion import MAX_BYTES, plantilla
from app.db.session import get_db
from app.models.usuario import Usuario
from app.schemas.importacion import ResultadoImportacion, ResumenImportacion
from app.services.importacion_service import ImportacionService

router = APIRouter(prefix="/importacion", tags=["importacion"])

_MIME_EXCEL = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _leer_subida(archivo: UploadFile) -> bytes:
    """Valida y lee el archivo subido.

    El tope de tamaño se comprueba acá y no solo dentro del parser porque
    openpyxl descomprime en memoria: conviene rechazar antes de abrir nada.
    """
    nombre = (archivo.filename or "").lower()
    if not nombre.endswith(".xlsx"):
        raise ValidationError(
            "El archivo debe ser un Excel .xlsx. Si lo tienes en .xls o .csv, "
            "ábrelo en Excel y guárdalo como .xlsx."
        )

    contenido = archivo.file.read(MAX_BYTES + 1)
    if len(contenido) > MAX_BYTES:
        raise ValidationError(
            f"El archivo pesa más de {MAX_BYTES // (1024 * 1024)} MB. "
            f"Divide la carga en varios archivos."
        )
    return contenido


@router.get("/plantilla.xlsx", response_class=Response)
def descargar_plantilla(
    _admin: Usuario = Depends(require_admin),
):
    """La plantilla que el cliente llena con sus talleres y productos.

    Va con hojas y títulos fijos a propósito: adivinar la estructura de un
    Excel cualquiera acierta casi siempre, y cuando falla crea datos malos en
    la base en vez de dar un error.
    """
    return Response(
        content=plantilla(),
        media_type=_MIME_EXCEL,
        headers={"Content-Disposition": 'attachment; filename="plantilla-orderscode.xlsx"'},
    )


@router.post("/previsualizar", response_model=ResumenImportacion)
def previsualizar_importacion(
    archivo: UploadFile = File(...),
    empresa_id: int = Depends(get_empresa_id),
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Dice qué se crearía y qué está mal, SIN escribir nada.

    Es el paso que evita el desastre: revisar tres filas malas antes cuesta
    un minuto, deshacer ochenta talleres mal creados no se puede (un taller
    con asignaciones ya no se borra).
    """
    return ImportacionService(db).previsualizar(empresa_id, _leer_subida(archivo))


@router.post("/confirmar", response_model=ResultadoImportacion, status_code=201)
def confirmar_importacion(
    archivo: UploadFile = File(...),
    empresa_id: int = Depends(get_empresa_id),
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Crea los talleres y productos del archivo. Todo o nada.

    Se vuelve a subir el mismo archivo en vez de guardar la previsualización
    en el servidor: así no hay estado a medias que expire ni que se cruce
    entre dos pestañas, y el archivo se valida de nuevo antes de escribir.
    """
    return ImportacionService(db).confirmar(empresa_id, _leer_subida(archivo))
