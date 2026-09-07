"""Schema validation. Requires `jsonschema` (see requirements.txt).

Every invocation result and every manifest/locator artifact goes through here before
anything downstream trusts it. A schema-invalid result is a failed invocation, not a thing
to interpret leniently (docs/control-flow-guardrails.md F4 / §2 downside on envelopes).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator

from util import SCHEMA_DIR, load_json


class SchemaValidationError(Exception):
    def __init__(self, schema_name: str, errors: list[str]):
        self.schema_name = schema_name
        self.errors = errors
        super().__init__(f"{schema_name}: {'; '.join(errors)}")


def validate(payload: Any, schema_name: str) -> None:
    """Raise SchemaValidationError if payload does not conform to schemas/<schema_name>."""
    schema_path = SCHEMA_DIR / schema_name
    if not schema_path.is_file():
        raise FileNotFoundError(f"unknown schema: {schema_name}")
    schema = load_json(schema_path)
    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
    if errors:
        raise SchemaValidationError(
            schema_name, [f"{list(e.path)}: {e.message}" for e in errors]
        )


def is_valid(payload: Any, schema_name: str) -> bool:
    try:
        validate(payload, schema_name)
        return True
    except SchemaValidationError:
        return False
