"""The data each agent actually holds - and the problems hidden in it.

Q3 expense audit at Northwind Group. 47 claims: 41 paid to suppliers, 6 travel
allowances paid to staff. Most are fine. Four are not, and each problem can only
be seen with data owned by ANOTHER department:

  CLM-3141  duplicate of CLM-3101 - same supplier, amount and date, submitted
            twice. Visible from Finance's own claims.
  CLM-3132  Meridian Travel billed 1,890.00 against a contracted day rate of
            310.00 (+10% tolerance, max 4 days = 1,364.00). Needs
            Supplier.Contract, held by Operations.
  CLM-3128  Meridian Travel booking for E-1201 on a date the roster shows no
            trip. Needs Employee.Roster, held by People & Culture.
  CLM-3606  travel allowance of 290.00 for E-1290, whose band (Band 2) caps a
            3-day trip at 255.00. Needs Employee.Compensation - restricted, held
            by People & Culture, and Finance has NO grant to it. This one stays
            hidden until a steward approves access.

So a refused call doesn't just leave work undone; it leaves a real overpayment
undetected. That is what makes the refusal matter, and what makes the approval
worth something.

Generated deterministically: same data every run, no fixture file to drift.
"""
from __future__ import annotations

_SUPPLIERS = [
    ("SUP-014", "Northwind Logistics", 128.50, "freight"),
    ("SUP-027", "Harbour Freight Co", 96.00, "freight"),
    ("SUP-033", "Calder Office Supply", 41.25, "supplies"),
    ("SUP-041", "Meridian Travel", 310.00, "travel"),
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

_DESCRIPTIONS = {
    "freight": ["Pallet freight to Leeds DC", "Return haulage, damaged stock",
                "Same-day courier, Bristol", "Container drayage, Felixstowe"],
    "supplies": ["Printer toner and paper", "Warehouse safety signage",
                 "Packing tape, bulk order", "Label stock for dispatch"],
    "travel": ["Client visit, Berlin - flights and hotel",
               "Supplier audit, Rotterdam - rail and hotel",
               "Trade show, Birmingham - hotel 2 nights",
               "Site survey, Glasgow - flights"],
}

# Claim numbers with planted problems. Kept as constants so tests and docs can
# point at them rather than rediscovering them.
DUPLICATE_OF = {"CLM-3141": "CLM-3101"}
OVER_CONTRACT = "CLM-3132"
PHANTOM_TRIP = "CLM-3128"
OVER_BAND = "CLM-3606"


def _date(i: int) -> str:
    return f"2026-0{7 + (i % 3)}-{(i % 27) + 1:02d}"


def _claims() -> list[dict]:
    rows: list[dict] = []
    for i in range(41):
        sup_id, sup_name, rate, kind = _SUPPLIERS[i % len(_SUPPLIERS)]
        emp_id, _, _ = _STAFF[i % len(_STAFF)]
        rows.append({
            "id": f"CLM-3{i + 101:03d}",
            "employee_id": emp_id,
            "date": _date(i),
            "type": "supplier",
            "supplier_id": sup_id,
            "supplier": sup_name,
            "category": kind,
            "description": _DESCRIPTIONS[kind][i % 4],
            "amount": round(rate * (1 + (i % 4) * 0.25), 2),
            "status": "open",
        })
    by_id = {r["id"]: r for r in rows}

    # duplicate: resubmitted copy of an earlier claim
    dup, orig = next(iter(DUPLICATE_OF.items()))
    by_id[dup].update({k: by_id[orig][k] for k in
                       ("employee_id", "date", "supplier_id", "supplier",
                        "category", "description", "amount")})
    # over contract: a travel invoice well above the contracted rate
    by_id[OVER_CONTRACT]["amount"] = 1890.00
    by_id[OVER_CONTRACT]["description"] = "Client visit, Berlin - flights, hotel, 'upgrade'"

    for j, (emp_id, _, _) in enumerate(_STAFF):
        rows.append({
            "id": f"CLM-3{j + 601:03d}",
            "employee_id": emp_id,
            "date": f"2026-0{7 + (j % 3)}-{(j * 4) + 2:02d}",
            "type": "allowance",
            "supplier_id": None,
            "supplier": None,
            "category": "allowance",
            "description": "Daily travel allowance",
            "amount": round(140.0 + j * 18.5, 2),
            "status": "open",
        })
    next(r for r in rows if r["id"] == OVER_BAND)["amount"] = 290.00
    return rows


CLAIMS: list[dict] = _claims()

SUPPLIER_CONTRACTS: list[dict] = [
    {"supplier_id": sid, "supplier": name, "agreed_day_rate": rate,
     "term": "2026-01-01/2026-12-31", "tolerance_pct": 10}
    for sid, name, rate, _ in _SUPPLIERS
]

STOCK_LEVELS: list[dict] = [
    {"sku": f"SKU-{200 + i}", "on_hand": 40 + i * 7, "location": "WH-1"}
    for i in range(6)
]


def _roster() -> list[dict]:
    """Every travel booking falls inside a rostered trip - except the phantom."""
    trips: dict[str, list[str]] = {e: [] for e, _, _ in _STAFF}
    for c in CLAIMS:
        if c["category"] == "travel" and c["id"] != PHANTOM_TRIP:
            trips[c["employee_id"]].append(c["date"])
        if c["type"] == "allowance":
            trips[c["employee_id"]].append(c["date"])
    return [{"employee_id": eid, "name": name, "trip_dates": sorted(set(trips[eid]))}
            for eid, name, _ in _STAFF]


EMPLOYEE_ROSTER: list[dict] = _roster()

# The withheld entity. Present here, never handed over without a grant.
EMPLOYEE_COMPENSATION: list[dict] = [
    {"employee_id": eid, "band": band, "max_daily_allowance": _BAND_ALLOWANCE[band]}
    for eid, _, band in _STAFF
]

DATASETS: dict[str, dict[str, list[dict]]] = {
    "expense-auditor":      {"Expense.Claim": CLAIMS},
    "inventory-reconciler": {"Inventory.StockLevel": STOCK_LEVELS,
                             "Supplier.Contract": SUPPLIER_CONTRACTS},
    "roster-planner":       {"Employee.Roster": EMPLOYEE_ROSTER,
                             "Employee.Compensation": EMPLOYEE_COMPENSATION},
}


def _self_check() -> None:
    assert len(CLAIMS) == 47
    assert sum(c["type"] == "supplier" for c in CLAIMS) == 41
    assert sum(c["type"] == "allowance" for c in CLAIMS) == 6
    ids = {c["id"] for c in CLAIMS}
    for cid in (*DUPLICATE_OF, *DUPLICATE_OF.values(), OVER_CONTRACT,
                PHANTOM_TRIP, OVER_BAND):
        assert cid in ids, cid
    phantom = next(c for c in CLAIMS if c["id"] == PHANTOM_TRIP)
    assert phantom["category"] == "travel", "the phantom trip must be a travel booking"
    rostered = next(r for r in EMPLOYEE_ROSTER if r["employee_id"] == phantom["employee_id"])
    assert phantom["date"] not in rostered["trip_dates"]


_self_check()
