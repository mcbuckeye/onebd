"""Main entry point for the Cortellis sync application."""

import logging
import sys
import signal
import time

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import Progress, SpinnerColumn, TextColumn

from .config import load_config
from .sync import SyncService
from .scheduler import SyncScheduler

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[RichHandler(rich_tracebacks=True)],
)
logger = logging.getLogger(__name__)
console = Console()


@click.group()
def cli():
    """Cortellis Deals Database Sync Tool."""
    pass


@cli.command()
def init():
    """Initialize the database schema."""
    console.print("[bold blue]Initializing database...[/bold blue]")
    try:
        config = load_config()
        sync_service = SyncService(config)
        sync_service.init_database()
        console.print("[bold green]Database initialized successfully![/bold green]")
    except Exception as e:
        console.print(f"[bold red]Error: {e}[/bold red]")
        sys.exit(1)


@cli.command()
@click.option("--batch-size", default=30, help="Number of deals per API batch (max 30)")
@click.option("--use-cache/--no-cache", default=True, help="Use cached deal IDs if available")
@click.option("--refresh-ids", is_flag=True, help="Force refresh of deal IDs from API")
def full_sync(batch_size: int, use_cache: bool, refresh_ids: bool):
    """Perform a full sync of all deals."""
    console.print("[bold blue]Starting full sync...[/bold blue]")

    if refresh_ids:
        use_cache = False
        console.print("[yellow]Forcing refresh of deal IDs from API[/yellow]")
    elif use_cache:
        console.print("[green]Will use cached deal IDs if available (use --refresh-ids to force refresh)[/green]")

    try:
        config = load_config()
        sync_service = SyncService(config)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Syncing deals...", total=None)
            sync_log = sync_service.full_sync(batch_size=batch_size, use_cached_ids=use_cache)
            progress.update(task, completed=True)

        console.print(f"\n[bold green]Full sync completed![/bold green]")
        console.print(f"  Records processed: {sync_log.records_processed}")
        console.print(f"  Records created: {sync_log.records_created}")
        console.print(f"  Records updated: {sync_log.records_updated}")
        console.print(f"  Contracts downloaded: {sync_log.contracts_downloaded}")

    except Exception as e:
        console.print(f"[bold red]Error: {e}[/bold red]")
        logger.exception("Full sync failed")
        sys.exit(1)


@cli.command()
@click.option("--batch-size", default=30, help="Number of deals per API batch (max 30)")
def incremental_sync(batch_size: int):
    """Perform an incremental sync of updated deals."""
    console.print("[bold blue]Starting incremental sync...[/bold blue]")

    try:
        config = load_config()
        sync_service = SyncService(config)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Syncing updated deals...", total=None)
            sync_log = sync_service.incremental_sync(batch_size=batch_size)
            progress.update(task, completed=True)

        console.print(f"\n[bold green]Incremental sync completed![/bold green]")
        console.print(f"  Records processed: {sync_log.records_processed}")
        console.print(f"  Records updated: {sync_log.records_updated}")
        console.print(f"  Contracts downloaded: {sync_log.contracts_downloaded}")

    except Exception as e:
        console.print(f"[bold red]Error: {e}[/bold red]")
        logger.exception("Incremental sync failed")
        sys.exit(1)


@cli.command()
@click.option("--workers", default=5, help="Number of parallel workers (default 5)")
@click.option("--resume/--no-resume", default=True, help="Resume from previous progress")
def sync_contracts(workers: int, resume: bool):
    """Sync contract metadata and download contract documents."""
    console.print("[bold blue]Starting contract sync...[/bold blue]")

    try:
        config = load_config()
        sync_service = SyncService(config)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Syncing contracts...", total=None)
            result = sync_service.sync_contracts(workers=workers, resume=resume)
            progress.update(task, completed=True)

        console.print(f"\n[bold green]Contract sync completed![/bold green]")
        console.print(f"  Deals checked: {result['deals_checked']}")
        console.print(f"  Deals with contracts: {result['deals_with_contracts']}")
        console.print(f"  Contracts downloaded: {result['contracts_downloaded']}")

    except Exception as e:
        console.print(f"[bold red]Error: {e}[/bold red]")
        logger.exception("Contract sync failed")
        sys.exit(1)


@cli.command()
def daemon():
    """Run as a daemon with scheduled syncs."""
    console.print("[bold blue]Starting Cortellis sync daemon...[/bold blue]")

    try:
        config = load_config()

        # Initialize database
        sync_service = SyncService(config)
        sync_service.init_database()

        # Start scheduler
        scheduler = SyncScheduler(config)
        scheduler.start()

        console.print(f"[green]Scheduler started with schedule: {config.sync_schedule}[/green]")
        console.print("Press Ctrl+C to stop...")

        # Handle shutdown signals
        def signal_handler(signum, frame):
            console.print("\n[yellow]Shutting down...[/yellow]")
            scheduler.stop()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Keep the main thread alive
        while True:
            time.sleep(60)

    except Exception as e:
        console.print(f"[bold red]Error: {e}[/bold red]")
        logger.exception("Daemon failed")
        sys.exit(1)


@cli.command()
def query():
    """Start the AI query agent (interactive mode)."""
    console.print("[bold blue]Starting AI Query Agent...[/bold blue]")

    try:
        config = load_config()

        if not config.openai.api_key:
            console.print("[bold red]Error: OPENAI_API_KEY not set[/bold red]")
            sys.exit(1)

        # Import here to avoid loading OpenAI if not needed
        from agent.query_agent import QueryAgent

        agent = QueryAgent(config)
        agent.interactive_session()

    except ImportError:
        console.print("[bold red]Error: Could not import query agent[/bold red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[bold red]Error: {e}[/bold red]")
        logger.exception("Query agent failed")
        sys.exit(1)


@cli.command()
@click.argument("question")
def ask(question: str):
    """Ask a single question to the AI agent."""
    try:
        config = load_config()

        if not config.openai.api_key:
            console.print("[bold red]Error: OPENAI_API_KEY not set[/bold red]")
            sys.exit(1)

        from agent.query_agent import QueryAgent

        agent = QueryAgent(config)
        response = agent.ask(question)
        console.print(response)

    except Exception as e:
        console.print(f"[bold red]Error: {e}[/bold red]")
        sys.exit(1)


@cli.command()
@click.option("--batch-size", default=100, help="Number of contracts per batch")
@click.option("--force", is_flag=True, help="Reindex already indexed contracts")
def index_contracts(batch_size: int, force: bool):
    """Index contract text files for full-text search."""
    console.print("[bold blue]Indexing contracts for full-text search...[/bold blue]")

    try:
        config = load_config()
        from .contract_indexer import ContractIndexer

        indexer = ContractIndexer(config)

        # Show current stats
        stats = indexer.get_stats()
        console.print(f"  Text contracts available: {stats['total_text_contracts']:,}")
        console.print(f"  Already indexed: {stats['indexed_for_fulltext']:,}")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Indexing contracts...", total=None)
            result = indexer.index_contracts_fulltext(
                batch_size=batch_size,
                force_reindex=force,
            )
            progress.update(task, completed=True)

        console.print(f"\n[bold green]Indexing complete![/bold green]")
        console.print(f"  Contracts to index: {result['total_contracts']:,}")
        console.print(f"  Indexed: {result['indexed']:,}")
        console.print(f"  Skipped: {result['skipped']:,}")
        console.print(f"  Errors: {result['errors']:,}")

    except Exception as e:
        console.print(f"[bold red]Error: {e}[/bold red]")
        logger.exception("Contract indexing failed")
        sys.exit(1)


@cli.command()
@click.option("--batch-size", default=50, help="Contracts per batch")
@click.option("--api-batch", default=100, help="Chunks per OpenAI API call")
@click.option("--force", is_flag=True, help="Regenerate existing embeddings")
def embed_contracts(batch_size: int, api_batch: int, force: bool):
    """Generate embeddings for contract chunks (for RAG)."""
    console.print("[bold blue]Generating contract embeddings for RAG...[/bold blue]")

    try:
        config = load_config()

        if not config.openai.api_key:
            console.print("[bold red]Error: OPENAI_API_KEY not set[/bold red]")
            sys.exit(1)

        from .contract_indexer import ContractIndexer

        indexer = ContractIndexer(config)

        # Show current stats
        stats = indexer.get_stats()
        console.print(f"  Indexed contracts: {stats['indexed_for_fulltext']:,}")
        console.print(f"  Existing chunks: {stats['total_chunks']:,}")
        console.print(f"  Embedded chunks: {stats['embedded_chunks']:,}")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Generating embeddings...", total=None)
            result = indexer.embed_contracts(
                batch_size=batch_size,
                api_batch_size=api_batch,
                force_reembed=force,
            )
            progress.update(task, completed=True)

        console.print(f"\n[bold green]Embedding complete![/bold green]")
        console.print(f"  Contracts processed: {result['contracts_processed']:,}")
        console.print(f"  Chunks created: {result['chunks_created']:,}")
        console.print(f"  Chunks embedded: {result['chunks_embedded']:,}")
        console.print(f"  Errors: {result['errors']:,}")

    except Exception as e:
        console.print(f"[bold red]Error: {e}[/bold red]")
        logger.exception("Contract embedding failed")
        sys.exit(1)


@cli.command()
@click.argument("query")
@click.option("--limit", default=10, help="Maximum results")
def search_contracts(query: str, limit: int):
    """Search contracts using full-text search."""
    try:
        config = load_config()
        from .contract_indexer import ContractIndexer

        indexer = ContractIndexer(config)

        results = indexer.search_fulltext(query, limit=limit)

        if not results:
            console.print("[yellow]No matching contracts found.[/yellow]")
            return

        console.print(f"[bold green]Found {len(results)} matching contracts:[/bold green]\n")

        for i, r in enumerate(results, 1):
            console.print(f"[bold]{i}. Deal {r['deal_id']}: {r['deal_title'][:60]}...[/bold]")
            console.print(f"   Contract ID: {r['contract_id']} | Types: {r['contract_types']}")
            console.print(f"   Relevance: {r['rank']:.4f} | Words: {r['word_count']:,}")
            console.print(f"   [dim]{r['snippet']}[/dim]\n")

    except Exception as e:
        console.print(f"[bold red]Error: {e}[/bold red]")
        sys.exit(1)


@cli.command()
@click.argument("query")
@click.option("--limit", default=5, help="Maximum results")
def search_similar(query: str, limit: int):
    """Search contracts using semantic similarity (RAG)."""
    try:
        config = load_config()

        if not config.openai.api_key:
            console.print("[bold red]Error: OPENAI_API_KEY not set[/bold red]")
            sys.exit(1)

        from .contract_indexer import ContractIndexer

        indexer = ContractIndexer(config)

        with console.status("[bold blue]Searching...[/bold blue]"):
            results = indexer.search_similar(query, limit=limit)

        if not results:
            console.print("[yellow]No similar contracts found.[/yellow]")
            return

        console.print(f"[bold green]Found {len(results)} similar contract sections:[/bold green]\n")

        for i, r in enumerate(results, 1):
            console.print(f"[bold]{i}. Deal {r['deal_id']}: {r['deal_title'][:60]}...[/bold]")
            console.print(f"   Contract ID: {r['contract_id']} | Chunk: {r['chunk_index']}")
            console.print(f"   Similarity: {r['similarity']:.4f} | Tokens: {r['token_count']}")
            console.print(f"   [dim]{r['content'][:300]}...[/dim]\n")

    except Exception as e:
        console.print(f"[bold red]Error: {e}[/bold red]")
        sys.exit(1)


@cli.command()
@click.option("--api-batch", default=2000, help="Chunks per OpenAI API call (max 2048)")
def resume_embedding(api_batch: int):
    """Resume embedding generation from where it left off (optimized)."""
    console.print("[bold blue]Resuming contract embedding (optimized)...[/bold blue]")

    try:
        config = load_config()

        if not config.openai.api_key:
            console.print("[bold red]Error: OPENAI_API_KEY not set[/bold red]")
            sys.exit(1)

        from .contract_indexer import ContractIndexer

        indexer = ContractIndexer(config)

        # Show current stats
        stats = indexer.get_stats()
        remaining = stats['total_chunks'] - stats['embedded_chunks']
        console.print(f"  Total chunks: {stats['total_chunks']:,}")
        console.print(f"  Already embedded: {stats['embedded_chunks']:,}")
        console.print(f"  Remaining: {remaining:,}")

        if remaining == 0:
            console.print("[green]All chunks already embedded![/green]")
            return

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Generating embeddings...", total=None)
            result = indexer.resume_embedding(api_batch_size=api_batch)
            progress.update(task, completed=True)

        console.print(f"\n[bold green]Embedding complete![/bold green]")
        console.print(f"  Chunks embedded: {result['chunks_embedded']:,}")
        console.print(f"  Errors: {result['errors']:,}")

    except Exception as e:
        console.print(f"[bold red]Error: {e}[/bold red]")
        logger.exception("Resume embedding failed")
        sys.exit(1)


@cli.command()
def index_status():
    """Show contract indexing status."""
    try:
        config = load_config()
        from .contract_indexer import ContractIndexer

        indexer = ContractIndexer(config)
        stats = indexer.get_stats()

        console.print("[bold blue]Contract Indexing Status[/bold blue]\n")
        console.print(f"  Text contracts available: {stats['total_text_contracts']:,}")
        console.print(f"  Indexed for full-text search: {stats['indexed_for_fulltext']:,}")
        console.print(f"  Total chunks created: {stats['total_chunks']:,}")
        console.print(f"  Chunks with embeddings: {stats['embedded_chunks']:,}")

        if stats['total_text_contracts'] > 0:
            pct_indexed = (stats['indexed_for_fulltext'] / stats['total_text_contracts']) * 100
            console.print(f"\n  Full-text indexing: {pct_indexed:.1f}% complete")

        if stats['total_chunks'] > 0:
            pct_embedded = (stats['embedded_chunks'] / stats['total_chunks']) * 100
            console.print(f"  Embedding generation: {pct_embedded:.1f}% complete")

    except Exception as e:
        console.print(f"[bold red]Error: {e}[/bold red]")
        sys.exit(1)


def main():
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
