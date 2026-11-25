"""Currency precision shared with the frontend (FR-1.4)."""

import json
from importlib.resources import files
from types import MappingProxyType

CURRENCY_EXPONENTS = MappingProxyType(
    json.loads(files("app").joinpath("currency_exponents.json").read_text(encoding="utf-8"))
)
