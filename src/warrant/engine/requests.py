"""Grant requests: the loop back from a refusal to a human who can act.

A refused agent raises one of these naming the capability, the data entity and
the work that is blocked. The steward of that entity approves or declines it.
An approval writes a grant into the model, so the next run of the same task
resolves without a refusal.

This is the only part of WARRANT that *creates* authority, so it is the part
with the most checking: the entity and capability must exist, an already-decided
request cannot be re-decided, and the approver must belong to the org unit that
actually stewards the entity.

SCOPE NOTE, stated plainly because it matters: there is no authentication here.
The steward check is a *modelled* check - it verifies the claimed approver org
stewards the entity - not proof of who is calling. A production deployment needs
real authn in front of this endpoint. It is demo-scoped on purpose, not by
oversight.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..model import ArchitectureModel
from ..model.schema import Grant


@dataclass(slots=True)
class GrantRequest:
    id: str
    capability: str
    data_entity: str
    requested_by: str
    reason: str = ""
    blocking: int = 0
    state: str = "pending"          # pending | approved | declined
    decided_by: str = ""
    decided_at: str = ""
    note: str = ""
    raised_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class RequestStore:
    """Append-only, like the audit log. The file is the log of every state
    change; the current state of a request is its last entry."""

    def __init__(self, path: str | Path, audit_path: str | Path | None = None):
        self.path = Path(path)
        # Used to check that a request corresponds to a refusal that actually
        # happened. Without it, `requested_by`, `reason` and `blocking` are
        # attacker-chosen strings that the console then renders to the steward
        # as the factual basis for approving.
        self.audit_path = Path(audit_path) if audit_path else None
        # Records that could not be parsed. Surfaced rather than swallowed - a
        # corrupt approvals log is an operational problem someone must see.
        self.corrupt: list[str] = []

    def _was_refused(self, capability: str, data_entity: str) -> bool:
        if self.audit_path is None or not self.audit_path.exists():
            return False
        for line in self.audit_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("granted"):
                continue
            for m in e.get("missing_grants", []):
                if (m.get("capability") == capability
                        and m.get("data_entity") == data_entity):
                    return True
        return False

    def _append(self, r: GrantRequest) -> GrantRequest:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(r)) + "\n")
        return r

    def all(self) -> list[GrantRequest]:
        if not self.path.exists():
            return []
        # Reset: all() re-reads the file each time and approved_grants() calls
        # it again, so accumulating would double-count every corrupt record.
        self.corrupt = []
        latest: dict[str, GrantRequest] = {}
        for line in self.path.read_text(encoding="utf-8").strip().splitlines():
            if not line:
                continue
            # A single corrupt line used to raise out of here, and because
            # approved_grants() is called during startup that meant one bad
            # record stopped the whole plane rather than losing one request.
            # Skipping is the fail-closed choice: an unreadable record grants
            # nothing.
            try:
                r = GrantRequest(**json.loads(line))
            except (json.JSONDecodeError, TypeError) as exc:
                self.corrupt.append(f"{line[:80]}... ({exc})")
                continue
            latest[r.id] = r
        return sorted(latest.values(), key=lambda r: r.raised_at, reverse=True)

    def get(self, request_id: str) -> GrantRequest | None:
        for r in self.all():
            if r.id == request_id:
                return r
        return None

    def approved_grants(self) -> list[Grant]:
        """Replayed into the model on start so an approval survives a restart."""
        return [
            Grant(capability=r.capability, data_entity=r.data_entity,
                  granted_by=r.decided_by or "approvals",
                  note=f"Approved from grant request {r.id}. {r.note}".strip())
            for r in self.all() if r.state == "approved"
        ]

    # ------------------------------------------------------------------
    def raise_request(self, model: ArchitectureModel, *, capability: str,
                      data_entity: str, requested_by: str, reason: str = "",
                      blocking: int = 0) -> GrantRequest:
        if capability not in model.capabilities:
            raise ValueError(f"unknown capability '{capability}'")
        if data_entity not in model.data_entities:
            raise ValueError(f"unknown data entity '{data_entity}'")
        if model.has_grant(capability, data_entity):
            raise ValueError("that grant already exists")

        # The requester must be a modelled agent that actually serves the
        # capability it is asking for. Otherwise any caller can raise a request
        # in a legitimate agent's name, for a capability it has nothing to do
        # with, and the steward approves on that forged provenance.
        agent = model.agents.get(requested_by)
        if agent is None:
            raise ValueError(f"'{requested_by}' is not an agent in the model")
        if agent.serves != capability:
            raise ValueError(
                f"'{requested_by}' serves '{agent.serves}', not '{capability}'")

        # And the refusal must have actually happened. A grant request is a
        # response to a recorded denial, not a way to ask for arbitrary access.
        if not self._was_refused(capability, data_entity):
            raise ValueError(
                f"no recorded refusal of {capability} -> {data_entity}; a grant "
                f"request must follow a denial that is in the audit log")
        for r in self.all():
            if (r.state == "pending" and r.capability == capability
                    and r.data_entity == data_entity):
                return r          # idempotent: one open request per pair
        return self._append(GrantRequest(
            id=uuid.uuid4().hex[:6].upper(), capability=capability,
            data_entity=data_entity, requested_by=requested_by,
            reason=reason, blocking=blocking,
        ))

    def decide(self, model: ArchitectureModel, request_id: str, *,
               approve: bool, decided_by: str, note: str = "") -> GrantRequest:
        r = self.get(request_id)
        if r is None:
            raise ValueError(f"unknown request '{request_id}'")
        if r.state != "pending":
            raise ValueError(f"request {request_id} is already {r.state}")

        steward = model.steward_of(r.data_entity)
        if steward is None:
            raise ValueError(f"no steward for '{r.data_entity}'")
        if decided_by != steward.id:
            # Modelled, not authenticated - see the scope note above.
            raise PermissionError(
                f"'{r.data_entity}' is stewarded by {steward.name} "
                f"({steward.id}); '{decided_by}' cannot decide this request"
            )

        r.state = "approved" if approve else "declined"
        r.decided_by = decided_by
        r.decided_at = datetime.now(timezone.utc).isoformat()
        r.note = note
        self._append(r)

        if approve:
            model.grants.append(Grant(
                capability=r.capability, data_entity=r.data_entity,
                granted_by=decided_by,
                note=f"Approved from grant request {r.id}. {note}".strip(),
            ))
        return r
