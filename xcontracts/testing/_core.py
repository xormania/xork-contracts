"""Check objects and the assertion helpers the kit uses instead of ``assert``.

Checks raise ``ContractViolation`` (an ``AssertionError``) with a stable code,
so they still fail under ``python -O`` and report the same way with or without
pytest.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any


class ContractViolation(AssertionError):
    """A subject did not behave as its port requires. ``code`` names the requirement."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def expect(condition: object, code: str, detail: str = "") -> None:
    """Raise ``ContractViolation(code, detail)`` unless ``condition`` is true."""
    if not condition:
        raise ContractViolation(code, detail)


def expect_equal(observed: object, expected: object, code: str) -> None:
    if observed != expected:
        raise ContractViolation(code, f"observed {observed!r}, expected {expected!r}")


def raises[E: BaseException](expected: type[E] | tuple[type[E], ...], call: Callable[[], object], code: str,
                             detail: str = "") -> E:
    """Run ``call`` and return the exception it raises, which must be ``expected``.

    Any other ``Exception`` is reported as ``ContractViolation(code)``; other
    ``BaseException``s (such as ``KeyboardInterrupt``) propagate unless expected.
    """
    prefix = f"{detail}: " if detail else ""
    try:
        result = call()
    except expected as error:
        return error
    except ContractViolation:
        raise
    except Exception as error:  # noqa: BLE001 - reported as a violation with its type
        raise ContractViolation(code, f"{prefix}raised {type(error).__name__}: {error}") from error
    raise ContractViolation(code, f"{prefix}returned {result!r} instead of raising")


@dataclass(frozen=True)
class Check:
    """One named requirement. Calling it runs it against a subject; ``str`` is its name (for test ids)."""

    name: str
    function: Callable[..., None]
    description: str = ""

    def __call__(self, *arguments: Any, **keywords: Any) -> None:
        """Run the check. An unexpected ``Exception`` from the subject is reported as a violation.

        Its code is ``UNEXPECTED_EXCEPTION`` and its detail names this check.
        """
        try:
            self.function(*arguments, **keywords)
        except ContractViolation:
            raise
        except Exception as error:  # noqa: BLE001 - any adapter failure is a verdict on that adapter
            raise ContractViolation("UNEXPECTED_EXCEPTION",
                                    f"{self.name}: {type(error).__name__}: {error}") from error

    def __str__(self) -> str:
        return self.name


def check(description: str = "") -> Callable[[Callable[..., None]], Check]:
    """Decorator turning a function into a ``Check`` named after it."""
    def wrap(function: Callable[..., None]) -> Check:
        return Check(function.__name__, function, description or (function.__doc__ or "").strip().split("\n")[0])
    return wrap


@dataclass(frozen=True)
class Result:
    name: str
    passed: bool
    code: str | None = None
    detail: str = ""


def run(checks: Iterable[Check], *arguments: Any, **keywords: Any) -> list[Result]:
    """Run every check with the same arguments and collect results, without pytest.

    A check fails with a ``ContractViolation``, including ``UNEXPECTED_EXCEPTION``
    when the subject raised something else; nothing else escapes except
    ``BaseException``s such as ``KeyboardInterrupt``.
    """
    results = []
    for item in checks:
        try:
            item(*arguments, **keywords)
        except ContractViolation as violation:
            results.append(Result(item.name, False, violation.code, violation.detail))
        else:
            results.append(Result(item.name, True))
    return results
