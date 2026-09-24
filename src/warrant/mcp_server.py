"""WARRANT as an MCP server: any MCP-speaking agent can ask for a warrant.

This is an adapter, like `warrant.agents`: it depends on the MCP SDK so that
`warrant.engine` and `warrant.providers` never do (ADR-0005, kept by ADR-0008).
It holds no authorization logic of its own - every tool proxies to the HTTP
plane, so there is one source of truth for grants and the audit log, and the
plane's `agent_auth` still applies.

Two design choices worth stating, because the obvious version gets both wrong:

**Identity is configuration, not a tool argument.** Each server instance IS one
agent, fixed by WARRANT_AGENT_ID and authenticated to the plane with
WARRANT_AGENT_TOKEN. No tool accepts a `caller` parameter. If one did, the model
driving the MCP client would choose who it is - which is exactly the
self-asserted `caller_agent` hole the September review closed on the HTTP API.

**A refusal is a result, not an error.** `request_warrant` returns structured
reasons, the steward of each refused entity, and a remediation hint naming the
tool to call next. The calling agent can replan around a refusal only if it can
read one (ADR-0008). This is also precisely what MCP's own authorization interest
group lists as unsolved: "structured denials, remediation hints".

Run:
    WARRANT_AGENT_ID=expense-auditor WARRANT_PLANE_URL=http://127.0.0.1:8000 \\
        python -m warrant.mcp_server
"""
from __future__ import annotations

import os

import httpx
from mcp.server import MCPServer
from pydantic import BaseModel, Field


class RefusedEntity(BaseModel):
    data_entity: str
    classification: str
    steward: str = Field(description="org unit that can approve a grant")


class WarrantResult(BaseModel):
    granted: bool
    warrant_id: str
    entities: list[str] = Field(description="data entities this call was judged to touch")
    refused: list[RefusedEntity] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    remediation: str = Field("", description="what to do next if refused")
    expires_at: str = ""
    decisive_exclusions: list[str] = Field(
        default_factory=list,
        description="entities the classifier dropped that you hold no grant "
                    "for - the one place a model output affected this outcome")


class AccessEntry(BaseModel):
    callee: str
    data_entity: str
    classification: str
    granted: bool
    steward: str


class AccessMap(BaseModel):
    agent: str
    capability: str
    entries: list[AccessEntry]


class GrantRequestResult(BaseModel):
    accepted: bool
    request_id: str = ""
    routed_to: str = ""
    error: str = ""


def make_server(agent_id: str, plane_url: str, token: str | None = None,
                http: httpx.AsyncClient | None = None) -> MCPServer:
    """`http` is injectable so tests can drive the real FastAPI plane through
    an ASGI transport instead of a network socket."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    client = http or httpx.AsyncClient(base_url=plane_url, timeout=30.0)
    server = MCPServer(
        "warrant",
        instructions=(
            f"You are acting as the agent '{agent_id}'. Before reaching data "
            f"owned by another organisation unit, call request_warrant. If it is "
            f"refused, do not retry the same purpose: finish what you can with "
            f"what was granted, and call raise_grant_request for what you "
            f"genuinely need. Call list_my_access to plan before you start."
        ),
    )
    _model: dict = {}

    async def model() -> dict:
        if not _model:
            r = await client.get("/v1/model")
            r.raise_for_status()
            _model.update(r.json())
        return _model

    async def steward_of(entity_id: str) -> tuple[str, str]:
        m = await model()
        orgs = {o["id"]: o["name"] for o in m["org_units"]}
        for e in m["data_entities"]:
            if e["id"] == entity_id:
                return orgs.get(e["owner_org"], e["owner_org"]), e["classification"]
        return "unknown", "unknown"

    @server.tool()
    async def request_warrant(callee: str, purpose: str, payload: str = "") -> WarrantResult:
        """Ask for permission to call another agent. State the purpose honestly
        and narrowly: it decides which data entities the call is judged to touch.
        Returns a warrant id to present to the callee, or structured reasons."""
        r = await client.post("/v1/warrant", headers=headers, json={
            "caller_agent": agent_id, "callee_agent": callee,
            "purpose": purpose, "payload": payload})
        if r.status_code in (401, 403) and "granted" not in r.text:
            raise PermissionError(r.json().get("error", r.text))
        body = r.json()
        refused = []
        for m in body.get("missing_grants", []):
            steward, cls = await steward_of(m["data_entity"])
            refused.append(RefusedEntity(data_entity=m["data_entity"],
                                         classification=cls, steward=steward))
        remediation = ""
        if refused:
            names = ", ".join(f"{x.data_entity} (steward: {x.steward})" for x in refused)
            remediation = (
                f"Refused on {names}. Do not retry this purpose. Complete what "
                f"you can with data you are granted, then call "
                f"raise_grant_request(data_entity=...) for each entity you "
                f"genuinely need; it is routed to the steward named.")
        return WarrantResult(
            granted=bool(body.get("granted")),
            warrant_id=body.get("id", ""),
            entities=body.get("entities_touched", []),
            refused=refused,
            reasons=[x["detail"] for x in body.get("reasons", [])],
            remediation=remediation,
            expires_at=body.get("expires_at", ""),
            decisive_exclusions=body.get("decisive_exclusions", []),
        )

    @server.tool()
    async def list_my_access() -> AccessMap:
        """Every data entity each other agent holds, and whether you may reach
        it. Plan with this before calling anything."""
        m = await model()
        me = next((a for a in m["agents"] if a["id"] == agent_id), None)
        if me is None:
            raise ValueError(f"'{agent_id}' is not an agent in the model")
        held = {(g["capability"], g["data_entity"]) for g in m["grants"]}
        entries = []
        for a in m["agents"]:
            if a["id"] == agent_id:
                continue
            for e in a["reads"]:
                steward, cls = await steward_of(e)
                entries.append(AccessEntry(
                    callee=a["id"], data_entity=e, classification=cls,
                    granted=(me["serves"], e) in held, steward=steward))
        return AccessMap(agent=agent_id, capability=me["serves"], entries=entries)

    @server.tool()
    async def raise_grant_request(data_entity: str, reason: str,
                                  blocking: int = 0) -> GrantRequestResult:
        """Ask the steward of a refused entity for a grant. Only valid after a
        refusal: the plane rejects a request with no recorded denial behind it.
        The capability is yours; you cannot request on another's behalf."""
        m = await model()
        me = next((a for a in m["agents"] if a["id"] == agent_id), None)
        if me is None:
            return GrantRequestResult(accepted=False, error=f"unknown agent {agent_id}")
        r = await client.post("/v1/grant-requests", headers=headers, json={
            "capability": me["serves"], "data_entity": data_entity,
            "requested_by": agent_id, "reason": reason, "blocking": blocking})
        if r.status_code != 201:
            return GrantRequestResult(accepted=False,
                                      error=r.json().get("error", r.text))
        steward, _ = await steward_of(data_entity)
        return GrantRequestResult(accepted=True, request_id=r.json()["id"],
                                  routed_to=steward)

    return server


def main() -> None:
    agent = os.environ.get("WARRANT_AGENT_ID")
    if not agent:
        raise SystemExit("WARRANT_AGENT_ID is required: this server acts as one agent")
    make_server(agent,
                os.environ.get("WARRANT_PLANE_URL", "http://127.0.0.1:8000"),
                os.environ.get("WARRANT_AGENT_TOKEN")).run("stdio")


if __name__ == "__main__":
    main()
