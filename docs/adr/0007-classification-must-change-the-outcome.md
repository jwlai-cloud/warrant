# 0007. Classification is load-bearing, or it is removed

Date: 2026-09-17
Status: Accepted

## Context

ADR-0004 keeps the model out of the decision. Correct, and not in question. But
the scaffold implemented it in a way that made Nemotron *inert*, which is a
different failure and a worse one:

- `classify.py` narrows the callee's declared entities, then falls back to the
  full declared set on any error.
- The demo callee's declared set contained `Inventory.StockLevel`, to which the
  caller's capability held no grant. So **every** purpose denied. Narrowing could
  not change any outcome.
- The offline `mock` provider echoed the declared set back verbatim, so its
  success path and `classify.py`'s failure path returned the identical value.

Net effect: a working fast tier and a stopped one produced byte-identical
output. Running the demo confirmed it - all three declared entities came
through, the justification was the mock's canned string. The honest description
of what shipped was "a YAML lookup with two inert model calls attached."

Worse, the advertised refusal reason was backwards. The demo was documented as
refused *because Expense Management holds no grant to Employee.Compensation* -
but a competent classifier, given "reconcile Q3 claims", should narrow salary
data **out**. The headline refusal was produced more reliably by the classifier
failing than by it working.

## Decision

The architecture model is arranged so that **classification changes the
outcome**, and a test enforces it.

One grant is added: `expense-management -> Inventory.StockLevel`. Within the
Inventory Reconciler's declared set, `Employee.Compensation` becomes the only
entity Expense Management cannot reach. The decision therefore turns on a single
classification question - *does this purpose need salary data?* - which is both a
genuine language task and a reliable one.

The demo is now an A/B on the same two agents and the same grant table:

| Purpose | Narrows to | Outcome |
|---|---|---|
| "verify claim 4471 against supplier contract terms and stock movements" | `Inventory.StockLevel`, `Supplier.Contract` | **GRANTED** |
| "reconcile Q3 claims against employee compensation bands" | `Employee.Compensation` | **DENIED** |

`tests/test_ab_demo.py` asserts the two outcomes differ. If that test can pass
with classification disabled, the model has stopped being load-bearing.

The `mock` provider now narrows by literal token overlap. It is a stub, not a
small model, and is documented as such: an indirectly-phrased purpose
("headcount cost" for `Employee.Compensation`) will miss offline and hit on a
real fast tier. That divergence is deliberate - if offline and online agree on
every input, Nemotron is decorative.

## Alternatives considered

- **Drop classification, keep only justification** - rejected for now, but it
  remains the honest fallback if time collapses. It reduces Nemotron to a text
  formatter and weakens Technological Implementation.
- **Let the model widen the entity set when the purpose implies more** -
  rejected outright. Widening is the one thing ADR-0004 forbids; a prompt
  injection in the payload would then escalate rather than deny.
- **Make the demo refusal depend on the classifier including an entity** -
  rejected. That is the backwards dependency described above: the demo would
  succeed most reliably when inference failed.

## Consequences

- Removing Nemotron now visibly breaks the product: every call denies, because
  fail-closed widens to the declared set. That is the correct failure mode and
  it is demonstrable on camera.
- The 3-minute video has a cause-and-effect structure - change one sentence of
  intent, watch the authorization flip - rather than one static refusal.
- Fail-closed is unchanged and still tested: an unclassifiable purpose widens to
  the declared set and denies. It never narrows to empty, which would grant.
- ADR-0004 is untouched. The grant table still decides; classification only
  selects which grants are checked.
