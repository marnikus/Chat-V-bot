"""DB command delegators — part of UndoService facade, H-C2."""

from __future__ import annotations


class UndoDbDelegates:
    async def _db_delete_op(self, value: dict, forward: bool) -> dict | None:
        return await self._db_commands._db_delete_op(value, forward)

    async def _db_op_forward(self, op: str, path: str) -> dict | None:
        return await self._db_commands._db_op_forward(op, path)

    async def _db_switch_op(self, value: dict, forward: bool) -> dict | None:
        return await self._db_commands._db_switch_op(value, forward)

    def _apply_db_command(self, value: dict, forward: bool) -> bool:
        return self._db_commands._apply_db_command(value, forward)
