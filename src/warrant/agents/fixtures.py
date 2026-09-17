"""The data each agent actually holds.

A refusal has to withhold real rows or the demo is abstract: "you may not see
Employee.Compensation" lands very differently when six specific claims stay open
because of it.

Generated deterministically rather than checked in as ~400 lines of JSON - same
data every run, no randomness, no fixture file to drift out of sync with the
numbers quoted in the README.

The split is the whole scenario: of 47 Q3 claims, 41 are supplier-rate claims
that Finance can verify against `Supplier.Contract`, and 6 are travel allowances
that can only be verified against a salary band in `Employee.Compensation` -
which Expense Management holds no grant to.
"""
from __future__ import annotations

_SUPPLIERS = [
    ("SUP-014", "Northwind Logistics", 128.50),
    ("SUP-027", "Harbour Freight Co", 96.00),
    ("SUP-033", "Calder Office Supply", 41.25),
    ("SUP-041", "Meridian Travel", 310.00),
]

_STAFF = [
    ("E-1042", "A. Okonkwo", "Band 4"),
    ("E-1088", "R. Basile", "Band 3"),
    ("E-1153", "M. Tanaka", "Band 5"),
    ("E-1201", "S. Delacroix", "Band 3"),
    ("E-1247", "J. Whitfield", "Band 4"),
    ("E-1290", "P. Ramasamy", "Band 2"),
]

_BAND_ALLOWANCE = {"Band 2": 85.0, "Band 3": 120.0, "Band 4": 165.0, "Band 5": 220.0}


def _claims() -> list[dict]:
    """47 Q3 claims: 41 supplier-rate, 6 travel allowance."""
    rows: list[dict] = []
    for i in range(41):
        sup_id, sup_name, rate = _SUPPLIERS[i % len(_SUPPLIERS)]
        emp_id, _, _ = _STAFF[i % len(_STAFF)]
        rows.append({
            "id": f"CLM-3{i + 101:03d}",
            "employee_id": emp_id,
            "date": f"2026-0{7 + (i % 3)}-{(i % 27) + 1:02d}",
            "type": "supplier",
            "supplier_id": sup_id,
            "supplier": sup_name,
            "amount": round(rate * (1 + (i % 4) * 0.25), 2),
            "status": "open",
        })
    for j, (emp_id, _, _) in enumerate(_STAFF):
        rows.append({
            "id": f"CLM-3{j + 601:03d}",
            "employee_id": emp_id,
            "date": f"2026-0{7 + (j % 3)}-{(j * 4) + 2:02d}",
            "type": "allowance",
            "supplier_id": None,
            "supplier": None,
            "amount": round(140.0 + j * 18.5, 2),
            "status": "open",
        })
    return rows


CLAIMS: list[dict] = _claims()

SUPPLIER_CONTRACTS: list[dict] = [
    {"supplier_id": sid, "supplier": name, "agreed_day_rate": rate,
     "term": "2026-01-01/2026-12-31", "tolerance_pct": 10}
    for sid, name, rate in _SUPPLIERS
]

STOCK_LEVELS: list[dict] = [
    {"sku": f"SKU-{200 + i}", "on_hand": 40 + i * 7, "location": "WH-1"}
    for i in range(6)
]

EMPLOYEE_ROSTER: list[dict] = [
    {"employee_id": eid, "name": name, "travelled_q3": True,
     "trips": 1 + (i % 3)}
    for i, (eid, name, _) in enumerate(_STAFF)
]

# The withheld entity. Present here, and never handed over - Expense Management
# holds no grant to Employee.Compensation.
EMPLOYEE_COMPENSATION: list[dict] = [
    {"employee_id": eid, "band": band,
     "max_daily_allowance": _BAND_ALLOWANCE[band]}
    for eid, _, band in _STAFF
]

# Which agent holds which data entity. Mirrors `reads` in config/model/.
DATASETS: dict[str, dict[str, list[dict]]] = {
    "expense-auditor":       {"Expense.Claim": CLAIMS},
    "inventory-reconciler":  {"Inventory.StockLevel": STOCK_LEVELS,
                              "Supplier.Contract": SUPPLIER_CONTRACTS},
    "roster-planner":        {"Employee.Roster": EMPLOYEE_ROSTER,
                              "Employee.Compensation": EMPLOYEE_COMPENSATION},
}


def _self_check() -> None:
    assert len(CLAIMS) == 47, len(CLAIMS)
    assert sum(c["type"] == "supplier" for c in CLAIMS) == 41
    assert sum(c["type"] == "allowance" for c in CLAIMS) == 6
    # Every allowance claim must need a band that lives in the withheld entity,
    # or "6 stay open because of the refusal" stops being true.
    banded = {r["employee_id"] for r in EMPLOYEE_COMPENSATION}
    assert all(c["employee_id"] in banded
               for c in CLAIMS if c["type"] == "allowance")


_self_check()
