"""Load the architecture model from YAML into an in-memory graph."""
from __future__ import annotations

from pathlib import Path

import yaml

from .schema import Agent, ArchitectureModel, Capability, DataEntity, Grant, OrgUnit


def _read(d: Path, name: str, key: str) -> list[dict]:
    p = d / name
    if not p.exists():
        return []
    return yaml.safe_load(p.read_text()).get(key, []) or []


def load_model(model_dir: str | Path) -> ArchitectureModel:
    d = Path(model_dir)
    m = ArchitectureModel()
    m.org_units = {o["id"]: OrgUnit(**o) for o in _read(d, "org.yaml", "org_units")}
    m.capabilities = {c["id"]: Capability(**c)
                      for c in _read(d, "capabilities.yaml", "capabilities")}
    m.data_entities = {e["id"]: DataEntity(**e)
                       for e in _read(d, "data_entities.yaml", "data_entities")}
    m.agents = {a["id"]: Agent(**a) for a in _read(d, "agents.yaml", "agents")}
    m.grants = [Grant(**g) for g in _read(d, "grants.yaml", "grants")]
    _validate(m)
    return m


def _validate(m: ArchitectureModel) -> None:
    """Fail loudly on a malformed model - a silent dangling reference in an
    authorization model is a security bug, not a warning."""
    problems: list[str] = []
    for c in m.capabilities.values():
        if c.owner_org not in m.org_units:
            problems.append(f"capability {c.id}: unknown owner_org {c.owner_org}")
    for e in m.data_entities.values():
        if e.owner_org not in m.org_units:
            problems.append(f"data entity {e.id}: unknown owner_org {e.owner_org}")
    for a in m.agents.values():
        if a.serves not in m.capabilities:
            problems.append(f"agent {a.id}: unknown capability {a.serves}")
        for r in a.reads:
            if r not in m.data_entities:
                problems.append(f"agent {a.id}: unknown data entity {r}")
    for g in m.grants:
        if g.capability not in m.capabilities:
            problems.append(f"grant: unknown capability {g.capability}")
        if g.data_entity not in m.data_entities:
            problems.append(f"grant: unknown data entity {g.data_entity}")
    if problems:
        raise ValueError("Invalid architecture model:\n  - " + "\n  - ".join(problems))
