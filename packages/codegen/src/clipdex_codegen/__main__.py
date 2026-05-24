"""`task codegen` — emit ``web/src/generated/schema.ts`` from shared Pydantic.

Pipeline:

1. Collect every model we expose to the API (the ones imported in
   ``clipdex_schema.api``).
2. ``model_json_schema()`` each into a single root JSON Schema with
   ``definitions`` for every other model — so cross-references resolve.
3. Write the JSON schema to ``web/src/generated/schema.json``.
4. Shell out to ``json2ts`` (from the ``json-schema-to-typescript`` npm
   package, devDep'd in ``web/``) to render the .ts.

About eighty lines, no extra deps on the Python side. The TS emitter is a
normal ``pnpm`` devDep in the ``web/`` workspace.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path

from pydantic import BaseModel

from clipdex_schema.api import (
    Appearance,
    ClipHit,
    GuestDetail,
    GuestQuote,
    GuestSummary,
    Question,
    QuestionSet,
    QuoteRef,
    SearchResponse,
    TopicMention,
)

log = logging.getLogger("clipdex.codegen")

MODELS: list[type[BaseModel]] = [
    GuestSummary,
    Appearance,
    TopicMention,
    GuestQuote,
    GuestDetail,
    QuoteRef,
    Question,
    QuestionSet,
    ClipHit,
    SearchResponse,
]


def _repo_root() -> Path:
    # __file__ -> packages/codegen/src/clipdex_codegen/__main__.py
    return Path(__file__).resolve().parents[4]


def build_combined_schema() -> dict:
    """One root schema with each model under ``definitions``.

    Each model also gets a top-level ``properties`` entry so that
    ``json-schema-to-typescript`` emits a named interface for it.
    """
    definitions: dict[str, dict] = {}
    properties: dict[str, dict] = {}
    for cls in MODELS:
        schema = cls.model_json_schema(ref_template="#/definitions/{model}")
        for name, defn in (schema.pop("$defs", {}) or {}).items():
            definitions.setdefault(name, defn)
        definitions[cls.__name__] = schema
        properties[cls.__name__] = {"$ref": f"#/definitions/{cls.__name__}"}

    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "ClipdexApi",
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
        "definitions": definitions,
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    root = _repo_root()
    out_dir = root / "web" / "src" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    schema_path = out_dir / "schema.json"
    ts_path = out_dir / "schema.ts"

    schema = build_combined_schema()
    schema_path.write_text(json.dumps(schema, indent=2) + "\n")
    log.info(
        "wrote %s (%d definitions)",
        schema_path.relative_to(root),
        len(schema["definitions"]),
    )

    pnpm = shutil.which("pnpm")
    if pnpm is None:
        log.error("pnpm not found on PATH; install pnpm or use npx manually")
        sys.exit(1)
    cmd = [
        pnpm,
        "--dir",
        str(root / "web"),
        "exec",
        "json2ts",
        "-i",
        str(schema_path),
        "-o",
        str(ts_path),
        "--no-additionalProperties",
    ]
    log.info("running: %s", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=root)
    log.info("wrote %s", ts_path.relative_to(root))


if __name__ == "__main__":
    main()
