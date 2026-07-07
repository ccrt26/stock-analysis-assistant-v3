from datetime import date

import typer

app = typer.Typer(no_args_is_help=True)


@app.command("health-check")
def health_check() -> None:
    typer.echo("credential: unchecked")
    typer.echo("network: unchecked")
    typer.echo("api_response: unchecked")
    typer.echo("field_consumability: unchecked")


@app.command("run-daily")
def run_daily(
    dry_run: bool = typer.Option(False, "--dry-run"),
    trade_date: str = typer.Option(..., "--trade-date"),
) -> None:
    parsed_trade_date = date.fromisoformat(trade_date)
    if dry_run:
        typer.echo(
            f"daily run dry-run completed for {parsed_trade_date.isoformat()}"
        )
        return
    typer.echo(f"daily run completed for {parsed_trade_date.isoformat()}")
