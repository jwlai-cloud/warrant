"""CLI. `warrant ask` is the 20-second demo; `warrant serve` runs the API."""
from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .engine import WarrantRequest, audit
from .service import WarrantService

app = typer.Typer(add_completion=False, help="WARRANT - agent-to-agent authorization.")
console = Console()


@app.command()
def ask(
    caller: str = typer.Argument(..., help="Calling agent id"),
    callee: str = typer.Argument(..., help="Called agent id"),
    purpose: str = typer.Option("", "--purpose", "-p"),
):
    """Request a warrant for one agent-to-agent call."""
    async def run():
        svc = WarrantService()
        d = await svc.evaluate(WarrantRequest(caller, callee, purpose))
        await svc.aclose()
        return d

    d = asyncio.run(run())
    style = "green" if d.granted else "red"
    console.print(Panel(d.justification or d.headline(),
                        title=f"[{style}]{d.headline()}[/{style}]",
                        subtitle=f"warrant {d.id} - served by "
                                 f"{d.tier_used or 'n/a'}/{d.provider_kind or 'n/a'}",
                        border_style=style))
    t = Table(show_header=True, header_style="bold")
    t.add_column("code"); t.add_column("detail", overflow="fold")
    for r in d.reasons:
        t.add_row(r.code, r.detail)
    console.print(t)
    raise typer.Exit(0 if d.granted else 3)


@app.command()
def log(limit: int = 20):
    """Show recent decisions."""
    svc = WarrantService()
    t = Table(show_header=True, header_style="bold")
    for c in ("id", "outcome", "caller", "callee", "tier"):
        t.add_column(c)
    for e in audit.read_all(svc.config.audit_path, limit):
        t.add_row(e["id"], "GRANT" if e["granted"] else "DENY",
                  e["caller"], e["callee"], e.get("tier_used") or "-")
    console.print(t)


@app.command()
def validate():
    """Load and validate the architecture model."""
    svc = WarrantService()
    m = svc.model
    console.print(f"[green]Model OK[/green] - {len(m.org_units)} org units, "
                  f"{len(m.capabilities)} capabilities, {len(m.data_entities)} data "
                  f"entities, {len(m.agents)} agents, {len(m.grants)} grants.")


@app.command()
def serve(host: str = "0.0.0.0", port: int = 8000):
    """Run the authorization plane and the console."""
    import uvicorn
    uvicorn.run("warrant.api.app:app", host=host, port=port)


# The ports ARCHITECTURE.md names. Keeping them in one place so the doc and the
# code cannot drift apart again.
AGENT_PORTS = {"inventory-reconciler": 8102, "roster-planner": 8103}


@app.command("serve-agent")
def serve_agent(
    agent_id: str = typer.Argument(..., help="inventory-reconciler | roster-planner"),
    port: int = typer.Option(0, help="defaults to this agent's documented port"),
    plane: str = typer.Option("http://127.0.0.1:8000", help="authorization plane"),
    host: str = "0.0.0.0",
):
    """Run one serving agent as its own service.

    ARCHITECTURE.md described these as separate services on their own ports and
    there was no way to start them - the console ran the graph in-process
    instead. This is the missing entrypoint, so the described topology is the
    one you can actually run.
    """
    import uvicorn

    from .agents.serving import make_serving_agent

    if agent_id not in AGENT_PORTS:
        console.print(f"[red]unknown serving agent '{agent_id}'[/red] - "
                      f"expected one of {', '.join(sorted(AGENT_PORTS))}")
        raise typer.Exit(2)
    uvicorn.run(make_serving_agent(agent_id, plane),
                host=host, port=port or AGENT_PORTS[agent_id])


if __name__ == "__main__":
    app()
