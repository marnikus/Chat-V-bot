"""Pure database-result policy. Deletion never becomes an undo command."""
import os


def world_switched(result: dict) -> bool:
    return bool(result.get("ok") and not result.get("unchanged")
                and not result.get("offline"))


def rebuild_needed(op: str) -> bool:
    return op in ("create", "load", "delete")


def undo_entry(op: str, result: dict) -> dict | None:
    if op == "delete":
        return None
    return {"op": result.get("op", op), "path": result.get("path", ""),
            "before_path": result.get("before_path", ""),
            "backup": result.get("backup", "")}


def success_text(template: str, result: dict) -> str:
    path = result.get("path", "")
    return template.format(path=path, name=os.path.basename(path))
