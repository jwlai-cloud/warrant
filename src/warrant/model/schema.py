"""A deliberately small subset of the TOGAF content metamodel.

Only the entities an authorization decision actually needs:

    Organization Unit  --owns-->  Business Capability
    Organization Unit  --stewards-->  Data Entity
    Application Component (Agent)  --serves-->  Business Capability
    Application Component (Agent)  --reads-->  Data Entity
    Grant: Business Capability  --may-read-->  Data Entity

TOGAF is the rigour behind these names, not a feature. We model the join that
makes a runtime decision possible and nothing else.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class OrgUnit(BaseModel):
    id: str
    name: str
    owner: str


class Capability(BaseModel):
    id: str
    name: str
    owner_org: str


class DataEntity(BaseModel):
    id: str
    name: str
    owner_org: str
    classification: str = "internal"


class Agent(BaseModel):
    id: str
    name: str
    org: str
    serves: str
    reads: list[str] = Field(default_factory=list)
    external: bool = False


class Grant(BaseModel):
    capability: str
    data_entity: str
    granted_by: str
    note: str | None = None


class ArchitectureModel(BaseModel):
    org_units: dict[str, OrgUnit] = Field(default_factory=dict)
    capabilities: dict[str, Capability] = Field(default_factory=dict)
    data_entities: dict[str, DataEntity] = Field(default_factory=dict)
    agents: dict[str, Agent] = Field(default_factory=dict)
    grants: list[Grant] = Field(default_factory=list)

    def has_grant(self, capability: str, data_entity: str) -> Grant | None:
        for g in self.grants:
            if g.capability == capability and g.data_entity == data_entity:
                return g
        return None

    def steward_of(self, data_entity: str) -> OrgUnit | None:
        de = self.data_entities.get(data_entity)
        return self.org_units.get(de.owner_org) if de else None
