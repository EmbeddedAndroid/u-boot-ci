"""The fwci-run/1 results schema: one JSON document per CI run."""
import datetime
import json
import os

import jsonschema

SCHEMA = json.load(open(os.path.join(os.path.dirname(__file__), "schema", "run.schema.json")))
_VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)


def errors(run):
    """Every schema violation of a run document, as 'path: message'."""
    return ["%s: %s" % ("/".join(str(p) for p in e.absolute_path) or "(root)", e.message)
            for e in sorted(_VALIDATOR.iter_errors(run), key=lambda e: list(e.absolute_path))]


def check(run):
    errs = errors(run)
    if errs:
        raise ValueError("invalid run document:\n  " + "\n  ".join(errs))
    return run


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
