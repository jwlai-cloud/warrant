# 0005. No agent SDK in WARRANT's core; LangGraph for the demo agents only

Date: 2026-09-17
Status: Accepted

## Context

The hackathon mandates no agent framework — only a runtime call to Token Factory
or deployment on Nebius AI Cloud compute, plus an NVIDIA open model. The Nebius
cookbook ships examples for CrewAI, LangChain, Agno, Camel, Google ADK,
LlamaIndex, Pydantic AI and AWS Strands, which shows the ecosystem is plural and
that no one framework is expected.

WARRANT is not an agent. It is a decision service that sits *between* agents.

## Decision

WARRANT's core takes **no agent-framework dependency**. The demo agents that
exercise it will be built with **LangGraph**, on familiarity grounds alone.

## Alternatives considered

- **Build WARRANT itself on LangGraph / Strands / ADK** — rejected. It would tie a
  framework-agnostic authorization plane to one framework, undermining the
  central claim that it works with anything.
- **AWS Strands or Google ADK for the demo agents** — rejected only on speed. No
  technical objection; LangGraph is the fastest path for this author.
- **No framework at all for the demo agents** — considered and still viable
  (two agents are ~30 lines of `httpx` each). Revisit if LangGraph setup costs
  more than half a day.

## Consequences

- Any framework can call `POST /v1/warrant`; that portability is a selling point
  and should be stated in the README.
- An A2A-compatible adapter becomes a natural, cheap stretch goal — A2A
  explicitly delegates authorization to the implementing organisation, which is
  precisely the gap WARRANT fills.
- The demo must show at least one *real* framework integration, or the
  "works with anything" claim is unevidenced.
