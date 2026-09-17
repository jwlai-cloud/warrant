# 0003. Model only a subset of the TOGAF content metamodel

Date: 2026-09-17
Status: Accepted

## Context

WARRANT needs a vocabulary for "who owns this capability" and "who stewards this
data". TOGAF's content metamodel already has it. But The Open Group has
published nothing on agentic architecture, and both SAP LeanIX and Ardoq built
working agent metamodels *without* TOGAF — so the standard is unclaimed here,
which may mean unwanted rather than undiscovered.

A full TOGAF implementation is also weeks of work that produces no decision.

## Decision

We will model exactly five entity types and one relationship that matters:

    Organization Unit --owns--> Business Capability
    Organization Unit --stewards--> Data Entity
    Application Component (Agent) --serves--> Business Capability
    Application Component (Agent) --reads--> Data Entity
    Grant: Business Capability --may-read--> Data Entity

**TOGAF is the rigour behind the naming, never the pitch.** The README and the
demo lead with the refusal, not the framework.

## Alternatives considered

- **Full TOGAF content metamodel / ArchiMate import** — rejected. Enormous
  surface area, none of which changes a decision, in a six-weekend window.
- **An ad-hoc ownership schema with invented names** — rejected. The TOGAF names
  are the vocabulary the target audience (enterprise architects) already uses,
  and adopting them costs nothing.
- **Leading the pitch with TOGAF** — rejected. Judges reward a working product;
  a standards-compliance claim is not a product.

## Consequences

- The model loads from five small YAML files and validates on load; a dangling
  reference is a hard error, because a silent one in an authorization model is a
  security bug.
- Grants are coarse (capability × data entity). Row-level, purpose-limited and
  time-boxed grants are deliberately deferred.
- Anyone from an EA background reads the model file and understands it instantly,
  which is most of the Potential Impact argument.
