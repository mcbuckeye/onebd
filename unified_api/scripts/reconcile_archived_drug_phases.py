"""Repair per-asset Cortellis phases from lossless expanded-response archives."""

from __future__ import annotations

import argparse
import json

from unified_api.services.cortellis_deal_api_sync import (
    reconcile_archived_drug_phases_batch,
)
from unified_api.services.database import get_cortellis_session


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument("--after-deal-id", type=int, default=0)
    parser.add_argument(
        "--all",
        action="store_true",
        help="Continue until every archived deal has been reconciled.",
    )
    args = parser.parse_args()

    cursor = args.after_deal_id
    totals = {"deals_processed": 0, "drugs_updated": 0, "parse_errors": 0}
    while True:
        with get_cortellis_session() as session:
            result = reconcile_archived_drug_phases_batch(
                session,
                after_deal_id=cursor,
                batch_size=args.batch_size,
            )
        for key in totals:
            totals[key] += int(result[key])
        cursor = int(result["next_deal_id"])
        print(json.dumps({**result, "totals": totals}, sort_keys=True), flush=True)
        if result["complete"] or not args.all:
            break


if __name__ == "__main__":
    main()
