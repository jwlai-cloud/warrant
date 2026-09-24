# 0010. Expose the authorization plane over MCP, with identity fixed by configuration

Date: 2026-09-24
Status: Accepted — complements ADR-0008's deferred A2A transport; does not replace it

## Context

ADR-0008 deferred A2A as the inter-agent transport. Separately, WARRANT's
reach is limited by how an agent asks for a warrant: today that means writing
an HTTP client against `POST /v1/warrant`. Most agents in 2026 already speak
MCP, so an MCP server makes WARRANT usable by any of them with a config entry
and no integration code.

There is also a fit on the merits. MCP's own Authorization Interest Group lists
as active and unsolved: *"authorization granularity beyond scope strings —
Rich Authorization Requests, structured denials, remediation hints."* A
WARRANT refusal is a structured denial with a remediation hint. Exposing it
over MCP puts the answer in the protocol the question was asked in.

A comparable project reviewed on 2026-09-24 (a card-dispute MCP server) ships
as MCP too — but as a single-agent vertical app whose authorization is account
scoping, not cross-organisation agent authorization.

## Decision

`warrant.mcp_server` exposes three tools, proxying to the HTTP plane:

- `request_warrant(callee, purpose, payload)` — returns a warrant, or a refusal
  **as a result, not an error**, carrying each refused entity's classification
  and steward and a remediation hint naming the next tool to call.
- `list_my_access()` — every entity other agents hold and whether this agent may
  reach it, so an agent can plan around boundaries before hitting them.
- `raise_grant_request(data_entity, reason, blocking)` — only accepted after a
  recorded refusal, as enforced by the plane.

Two properties are deliberate and tested:

1. **Identity is configuration, not a tool argument.** Each server instance is
   one agent (`WARRANT_AGENT_ID`, authenticated with `WARRANT_AGENT_TOKEN`). No
   tool accepts a caller, agent or capability parameter. If one did, the model
   driving the MCP client would choose who it is — the self-asserted
   `caller_agent` hole the September review closed on the HTTP API, reopened one
   layer up. `tests/test_mcp_server.py` asserts this against the live tool
   schemas and is mutation-tested: adding a `caller` parameter fails it.
2. **It proxies to the plane rather than embedding a service.** One source of
   truth for grants and the audit log, and the plane's `agent_auth` applies to
   MCP callers exactly as to HTTP ones.

## Alternatives considered

- **A2A instead** — not instead; A2A remains the right inter-agent transport
  (ADR-0008). MCP is agent-to-*tool*: it lets an agent ask WARRANT, not let
  agents call each other. The two are complementary.
- **Embed a `WarrantService` in the MCP process** — rejected. A second process
  with its own in-memory model would diverge from the plane as soon as a steward
  approved something.
- **Return refusals as MCP tool errors** — rejected. Errors are for failures;
  a refusal is a normal authorization outcome the agent is expected to plan
  around (ADR-0008), and tool-error text is not structured.

## Consequences

- Any MCP client — Claude Code, Claude Desktop, an agent framework's MCP adapter
  — can use WARRANT with a config entry.
- The core stays framework-free: the MCP SDK is an optional `[mcp]` extra,
  imported only by this adapter.
- mcp 2.x renamed `FastMCP` to `MCPServer`. Pinned to `>=2.2,<3` so code written
  from v1 examples fails at import rather than subtly.
