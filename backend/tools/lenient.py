"""Forgiving tool arguments for local models.

The SDK checks a tool's arguments against its JSON schema before the tool runs, and refuses the
whole call on a small slip. Claude rarely slips; local models often do (the benchmark in
scripts/bench_ollama_tools.py showed "Mon" instead of "mon", and "" for fields they don't use).
For the Ollama brain each tool's enums are loosened (the allowed values move into the description)
and its handler first tidies the arguments: unused empty fields dropped, enum words put in the
canonical case. Claude's tools are left exactly as they are.
"""

import dataclasses
from typing import Any


def _canon(value: Any, allowed: list) -> Any:
    if isinstance(value, str):
        return next((a for a in allowed if isinstance(a, str) and a.lower() == value.strip().lower()), value)
    return value


def clean(args: dict, schema: dict) -> dict:
    """Arguments without empty optional fields, enum words in the schema's own case."""
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    out = {}
    for key, value in args.items():
        if key not in required and (value is None or value == ""):
            continue
        spec = props.get(key, {})
        if "enum" in spec:
            value = _canon(value, spec["enum"])
        elif isinstance(value, list) and "enum" in spec.get("items", {}):
            value = [_canon(v, spec["items"]["enum"]) for v in value]
        out[key] = value
    return out


def _loosen(spec: dict) -> dict:
    spec = dict(spec)
    for holder in (spec, spec.get("items")):
        if isinstance(holder, dict) and "enum" in holder:
            holder_allowed = ", ".join(map(str, holder["enum"]))
            holder.pop("enum")
            spec["description"] = f"{spec.get('description', '')} One of: {holder_allowed}.".strip()
    return spec


def relax(tool):
    """A copy of an SdkMcpTool that accepts the slips `clean` can fix."""
    schema = tool.input_schema
    if not isinstance(schema, dict) or "properties" not in schema:
        return tool
    loose = {**schema, "properties": {k: _loosen({**v, **({"items": dict(v["items"])} if "items" in v else {})})
                                       for k, v in schema["properties"].items()}}

    async def handler(args):
        return await tool.handler(clean(args, schema))

    return dataclasses.replace(tool, input_schema=loose, handler=handler)
