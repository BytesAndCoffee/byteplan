# byteplan-runtime

[![PyPI - Version](https://img.shields.io/pypi/v/byteplan-runtime.svg)](https://pypi.org/project/byteplan-runtime)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/byteplan-runtime.svg)](https://pypi.org/project/byteplan-runtime)

Inert `@todo` and `@verifies` decorators for [BytePlan](https://github.com/BytesAndCoffee/byteplan),
a source-first task tracker for Python projects. *Plan in code. Track in one place.*

```python
from byteplan_runtime import todo, verifies

class Router:
    @todo("Implement route poisoning", id="a83f",
          tests=("tests/test_routing.py::test_route_poisoning",))
    def advertise_routes(self):
        raise NotImplementedError

@verifies("a83f")
def test_route_poisoning():
    ...
```

## Guarantees

- **Inert.** Both decorators return the decorated object itself (`todo(...)(f) is f`). They
  don't wrap, register, validate, log, read files or use the network. Decorator order and the
  behaviour of methods, classes, `staticmethod`, `classmethod` and `property` are unchanged.
- **No dependencies, nothing at import time.** It supports Python 3.8+ and is a single module.
- **Never breaks an import.** Arguments aren't checked at runtime. The `byteplan` CLI reads these
  decorators statically (with `ast`, never by importing your code) and reports problems there.
- **Stable API.** `todo(title, /, *, id=None, kind="TODO", description="", test=None, tests=())`
  and `verifies(*ids)`. Keyword arguments may be added later, but existing ones won't change
  meaning.

## Status

This package is complete for its purpose. The `byteplan` CLI's support for these decorators is
in development: it will discover them, allocate `id=` values, link tests, and strip the decorators
from release builds. Until then the decorators are harmless markers. See the
[implementation plan](https://github.com/BytesAndCoffee/byteplan/blob/main/byteplan/docs/IMPLEMENTATION_PLAN.md).

## Installation

```console
pip install byteplan-runtime
```

If you use BytePlan's release stripping, production code won't import this package, and you can
declare it as a development dependency only.

## License

`byteplan-runtime` is distributed under the terms of the [MIT](https://spdx.org/licenses/MIT.html) license.
