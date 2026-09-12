# app/services/recepcion/__init__.py
"""
La recepción de lo que vuelve del taller, partida por quién hace qué.

Un archivo por puesto, y el nombre de la carpeta es el PROCESO y no la
persona. Eso es deliberado: el proceso "recibir lo que vuelve" va a seguir
existiendo aunque mañana cambien los cargos, se parta bodega en dos turnos o
el dueño cubra el puesto un sábado. El dueño de cada parte se lee en el nombre
del archivo.

- `bodega.py`  -- quien cuenta. No ve ni una cantidad enviada.
- `corte.py`   -- quien compara y confirma. Es el único que ve las dos cifras.

Lo compartido (recalcular estados, la asignación) NO se copia aquí: sigue en
app/services/asignacion_taller_service.py, que es de donde ya lo usan otros
servicios que no son ni bodega ni corte.
"""
