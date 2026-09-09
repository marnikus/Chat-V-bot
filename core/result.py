"""Result[T] — typed success / failure container for layer boundaries.

Services return Result; bridges translate it to Qt signals. No exceptions
cross the bridge/services boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar, Callable, Optional

T = TypeVar("T")
E = TypeVar("E")


@dataclass(frozen=True)
class Result(Generic[T]):
    """Immutable result. One of ok(value) or err(message)."""

    _ok: bool
    _value: Optional[T] = None
    _error: Optional[str] = None

    @staticmethod
    def ok(value: T) -> "Result[T]":
        return Result(True, value, None)

    @staticmethod
    def err(error: str, value: Optional[T] = None) -> "Result[T]":
        return Result(False, value, str(error))

    @property
    def is_ok(self) -> bool:
        return self._ok

    @property
    def is_err(self) -> bool:
        return not self._ok

    @property
    def value(self) -> Optional[T]:
        return self._value

    @property
    def error(self) -> Optional[str]:
        return self._error

    def unwrap(self) -> T:
        if not self._ok:
            raise ValueError(f"Result is err: {self._error}")
        return self._value  # type: ignore[return-value]

    def unwrap_or(self, default: T) -> T:
        return self._value if self._ok and self._value is not None else default  # type: ignore[return-value]

    def map(self, fn: Callable[[T], E]) -> "Result[E]":
        if self._ok:
            try:
                return Result.ok(fn(self._value))  # type: ignore[arg-type]
            except Exception as exc:  # noqa: BLE001
                return Result.err(str(exc))
        return Result.err(self._error or "unknown", None)  # type: ignore[return-value]

    def to_dict(self) -> dict:
        if self._ok:
            return {"ok": True, "value": self._value}
        return {"ok": False, "error": self._error}

    def __repr__(self) -> str:
        if self._ok:
            return f"Result.ok({self._value!r})"
        return f"Result.err({self._error!r})"
