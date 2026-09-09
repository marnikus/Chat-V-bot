"""Result[T] — the only shape domain errors cross a layer boundary in.

Services return ``Result`` instead of raising: a domain failure (a preset
name that does not exist, a person already deleted, a database that cannot
be opened) is an EXPECTED, typed outcome, not an exception. Bridges
translate a Result into the JS wire format; stores keep raising only for
programmer errors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Generic, TypeVar, Union

T = TypeVar("T")


class _ErrKind:
    """Sentinel so `is_err` checks never depend on truthiness."""

    __slots__ = ()


ERR = _ErrKind()


@dataclass(frozen=True, slots=True)
class Ok(Generic[T]):
    value: T

    @property
    def is_ok(self) -> bool:
        return True

    @property
    def is_err(self) -> bool:
        return False

    def unwrap(self) -> T:
        return self.value

    def unwrap_or(self, default: Any) -> T:
        return self.value

    def map(self, fn: Callable[[T], Any]) -> "Ok":
        return Ok(fn(self.value))

    def err(self) -> None:
        return None


@dataclass(frozen=True, slots=True)
class Err(Generic[T]):
    code: str                 # machine-readable, stable — e.g. "preset_not_found"
    detail: str = ""          # human-readable context for logs / the UI

    @property
    def is_ok(self) -> bool:
        return False

    @property
    def is_err(self) -> bool:
        return True

    def unwrap(self) -> Any:
        raise RuntimeError(f"unwrap() on Err({self.code!r}): {self.detail}")

    def unwrap_or(self, default: Any) -> Any:
        return default

    def map(self, fn: Callable[[Any], Any]) -> "Err":
        return self

    def err(self) -> "Err":
        return self


#: Result[T] = Ok(value: T) | Err(code: str, detail: str)
Result = Union[Ok[T], Err[T]]


def ok(value: T = None) -> Ok[T]:
    return Ok(value)


def err(code: str, detail: str = "") -> Err[T]:
    return Err(code, detail)


def of(fn: Callable[[], T], code: str = "unexpected_error") -> Result[T]:
    """Run `fn`, catching any Exception into an Err — the bridge seam rule
    ("no bare exception crosses a layer boundary") in one helper."""
    try:
        return Ok(fn())
    except Exception as exc:                      # noqa: BLE001
        return Err(code, f"{type(exc).__name__}: {exc}")


async def aof(coro_fn: Callable[[], T],
              code: str = "unexpected_error") -> Result[T]:
    """Async `of`: awaits a zero-arg coroutine factory."""
    try:
        return Ok(await coro_fn())
    except Exception as exc:                      # noqa: BLE001
        return Err(code, f"{type(exc).__name__}: {exc}")
