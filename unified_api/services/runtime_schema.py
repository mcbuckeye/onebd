"""Shared deployment-migration boundary for live application processes."""

import os


def runtime_schema_is_pre_migrated() -> bool:
    """Return whether Compose guaranteed the one-shot migration completed."""
    return os.environ.get("ONEBD_RUNTIME_SCHEMA_MIGRATED", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
