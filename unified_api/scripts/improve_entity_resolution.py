"""Seed cross-source aliases and promote normalized-exact company matches."""

import json

from unified_api.services.entity_resolution import get_entity_resolution_service


def main() -> int:
    stats = get_entity_resolution_service().improve_identity_records()
    print(json.dumps(stats, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
