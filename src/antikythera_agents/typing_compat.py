"""`TypedDict` support that behaves identically on every supported interpreter (3.9 - 3.14).

`NotRequired` only reached the stdlib in Python 3.11. Before that it lives in
`typing_extensions`, where it works *only* in combination with `typing_extensions.TypedDict`
and `typing_extensions.get_type_hints`: a `typing.TypedDict` marked with a backported
`NotRequired[...]` reports every key as required, and `typing.get_type_hints` leaves the
`NotRequired[...]` wrapper in the resolved annotation instead of stripping it.

Agents declaring a `TypedDict` return type should import both names from here, so the same
tool describes itself the same way wherever it runs — including Rhino/Grasshopper's embedded
CPython 3.9. See `reference_agent.py` for the worked example.
"""

from __future__ import annotations

import sys

if sys.version_info >= (3, 11):
    from typing import NotRequired
    from typing import Required
    from typing import TypedDict
    from typing import get_type_hints
else:
    from typing_extensions import NotRequired
    from typing_extensions import Required
    from typing_extensions import TypedDict
    from typing_extensions import get_type_hints

__all__ = ["NotRequired", "Required", "TypedDict", "get_type_hints"]
