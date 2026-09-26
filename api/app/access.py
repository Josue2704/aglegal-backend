"""Shared authorization for minimal lookups and files attached to domain entities."""
from fastapi import Depends, HTTPException
from .deps import CurrentUser


def check(user, *permissions):
    if not user['is_admin'] and not any(p in user['permissions'] for p in permissions):
        raise HTTPException(403, 'Sin permiso: ' + ' / '.join(permissions))


def require_any(*permissions):
    def dependency(user: CurrentUser):
        check(user, *permissions)
    return Depends(dependency)


def check_attachment(user, entity_type, entity_id, action, conn):
    mapping = {'case_task':('tareas','case_tasks'), 'client':('clientes','clients'), 'case':('expedientes','cases'),
        'session':('agenda','sessions'), 'income':('flujo_caja','incomes'),
        'expense':('flujo_caja','expenses'), 'cost':('flujo_caja','costs'), 'user':('usuarios','users')}
    if entity_type not in mapping:
        raise HTTPException(400, 'Tipo de entidad inválido')
    module, table = mapping[entity_type]
    if not (entity_type == 'user' and int(entity_id) == user['id']):
        check(user, f'{module}.{action}')
    if not conn.execute(f'SELECT 1 FROM {table} WHERE id=%s',(entity_id,)).fetchone():
        raise HTTPException(404, 'Entidad no encontrada')
