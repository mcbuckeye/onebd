"""
Add publicly traded Cortellis companies that are missing from Edgar.

This script:
1. Finds Cortellis companies with CIKs not in Edgar
2. Adds them to the Edgar companies table
3. Fetches their SEC filings metadata
4. Queues filings for ingestion
"""
import asyncio
from datetime import datetime, timezone
from sqlalchemy import text
import structlog

logger = structlog.get_logger(__name__)


# Companies found to be missing (Cortellis CIKs not in Edgar)
MISSING_COMPANIES = [
    {
        "cik": "0001114448",
        "ticker": "NVS",
        "name": "Novartis AG",
        "country": "Switzerland",
        "sector": "Pharmaceuticals",
        "cortellis_id": 23137,
    },
    {
        # Official SEC submissions identify Roche Holding Ltd as CIK 0000889131.
        # CIK 0001140536 belongs to Willis Towers Watson plc.
        "cik": "0000889131",
        "ticker": "RHHBY",
        "name": "Roche Holding Ltd",
        "country": "Switzerland",
        "sector": "Pharmaceuticals",
        "cortellis_id": 19446,
    },
]


async def add_missing_companies():
    """Add missing companies and fetch their filings."""
    from unified_api.services.database import get_edgar_session
    from unified_api.services.edgar import get_edgar_client

    client = get_edgar_client()

    for company in MISSING_COMPANIES:
        cik = company["cik"]
        logger.info(f"Processing {company['name']} ({cik})")

        with get_edgar_session() as session:
            # Check if already exists
            existing = session.execute(
                text("SELECT id FROM companies WHERE cik = :cik"),
                {"cik": cik}
            ).fetchone()

            if existing:
                logger.info(f"Company {company['name']} already exists in Edgar")
                continue

            # Add to companies table
            result = session.execute(
                text("""
                    INSERT INTO companies (cik, ticker, name, country, sector, aliases)
                    VALUES (:cik, :ticker, :name, :country, :sector, '[]'::jsonb)
                    RETURNING id
                """),
                {
                    "cik": cik,
                    "ticker": company["ticker"],
                    "name": company["name"],
                    "country": company["country"],
                    "sector": company["sector"],
                }
            )
            company_id = result.fetchone().id
            session.commit()

            logger.info(f"Added {company['name']} to Edgar companies (id={company_id})")

        # Fetch filings metadata
        # For foreign filers, we want 20-F (annual) and 6-K (current reports)
        try:
            filings = await client.get_company_filings(
                cik=cik,
                forms=["8-K", "20-F", "6-K", "425", "SC 13D", "SC 13G"],
                date_from=datetime(2020, 1, 1, tzinfo=timezone.utc),  # Last 5 years
            )

            logger.info(f"Found {len(filings)} filings for {company['name']}")

            # Insert filing metadata into raw_documents table
            import json

            with get_edgar_session() as session:
                inserted = 0
                for filing in filings:
                    # Check if filing exists by URL
                    exists = session.execute(
                        text("SELECT id FROM raw_documents WHERE url = :url"),
                        {"url": filing["url"]}
                    ).fetchone()

                    if exists:
                        continue

                    session.execute(
                        text("""
                            INSERT INTO raw_documents (
                                company_id, source_type, url,
                                fetched_at, filing_date, filing_metadata
                            )
                            VALUES (
                                :company_id, :source_type, :url,
                                NOW(), :filing_date, :metadata
                            )
                        """),
                        {
                            "company_id": company_id,
                            "source_type": f"sec_{filing['form'].lower().replace('-', '_')}",
                            "url": filing["url"],
                            "filing_date": filing["filing_date"],
                            "metadata": json.dumps({
                                "accession_number": filing["accession_number"],
                                "form": filing["form"],
                                "cik": cik,
                                "primary_document": filing.get("primary_document"),
                                "status": "pending",
                            }),
                        }
                    )
                    inserted += 1

                session.commit()
                logger.info(f"Inserted {inserted} new filing records for {company['name']}")

        except Exception as e:
            logger.error(f"Failed to fetch filings for {company['name']}: {e}")
            continue

    logger.info("Completed adding missing companies")


def run():
    """Entry point for script."""
    asyncio.run(add_missing_companies())


if __name__ == "__main__":
    run()
