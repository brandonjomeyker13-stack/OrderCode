# app/api/v1/deps.py
from dataclasses import dataclass

from fastapi import Depends

from app.core.deps import get_current_usuario
from app.models.enums import RolUsuario
from app.models.usuario import Usuario
from app.schemas.common import PaginationParams


@dataclass(frozen=True)
class Contexto:
    """Quién está haciendo la request.

    Existe porque `get_empresa_id` devuelve un entero y solo un entero: con
    eso, ni el endpoint ni el servicio saben qué rol está preguntando, y por
    lo tanto no pueden decidir qué campos incluir en la respuesta. Eso es
    justo lo que exige el conteo a ciegas de bodega, donde el mismo endpoint
    tiene que devolver menos información a un rol que a otro.

    Ojo: declarar `Contexto` y `get_empresa_id` en el mismo endpoint no cuesta
    dos consultas. FastAPI memoiza las dependencias por request, así que
    `get_current_usuario` se resuelve una sola vez.
    """

    usuario: Usuario
    empresa_id: int
    rol: RolUsuario

    @property
    def es_admin(self) -> bool:
        return self.rol == RolUsuario.ADMIN

    def tiene_rol(self, *roles: RolUsuario) -> bool:
        return self.rol in roles


def get_contexto(usuario: Usuario = Depends(get_current_usuario)) -> Contexto:
    return Contexto(
        usuario=usuario, empresa_id=usuario.empresa_id, rol=usuario.rol
    )


def get_empresa_id(contexto: Contexto = Depends(get_contexto)) -> int:
    """
    Punto único de extracción del tenant actual. Todo endpoint que toque
    datos de negocio depende de esto -- nunca del empresa_id que venga
    en el body/query de la request (eso permitiría a un usuario pedir
    datos de otra empresa con solo cambiar un número).

    Se deriva del contexto para que el tenant salga de un solo sitio, aunque
    el endpoint pida las dos cosas.
    """
    return contexto.empresa_id


def get_pagination(page: int = 1, page_size: int = 50) -> PaginationParams:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 200)  # tope duro para evitar abuso
    return PaginationParams(page=page, page_size=page_size)