"""Finance's own data: the expense claims an audit runs on.

Finance can bring its own claims (a prepared scenario, or a CSV in the fixed
format below). The other departments' data - supplier contracts, the roster,
salary bands - stays theirs, reachable only through WARRANT. That split is the
product's point, so the upload is claims only, by design.

Uploaded text is untrusted. Only counts and the category (a fixed vocabulary)
reach a model prompt; supplier names and descriptions appear in findings, so
they are held to a plain character set and a length limit. A claim naming an
employee or supplier the other departments don't hold is flagged for query by
`audit_claims`, not passed.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date

from .fixtures import DATASETS

FIELDS = ("id", "employee_id", "date", "type", "supplier_id", "supplier",
          "category", "description", "amount")
TYPES = {"supplier", "allowance"}
CATEGORIES = {"freight", "supplies", "travel", "allowance"}
MAX_ROWS = 300
MAX_BYTES = 100_000
_ID = re.compile(r"^[A-Za-z0-9-]{1,20}$")
_TEXT = re.compile(r"^[A-Za-z0-9 .,'&/()-]{0,80}$")


def parse_claims_csv(text: str) -> list[dict]:
    """Rows in the fixed format, validated. Raises ValueError listing what is
    wrong (first 10 problems), so the console can show it."""
    if len(text.encode()) > MAX_BYTES:
        raise ValueError(f"file is larger than {MAX_BYTES // 1000} KB")
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    header = [h.strip() for h in (reader.fieldnames or [])]
    missing = [f for f in FIELDS if f not in header]
    if missing:
        raise ValueError("missing columns: " + ", ".join(missing))
    out, errors, seen = [], [], set()
    for n, raw in enumerate(reader, start=2):              # row 1 is the header
        if len(out) >= MAX_ROWS:
            errors.append(f"more than {MAX_ROWS} claims; only the first {MAX_ROWS} are allowed")
            break
        r = {k.strip(): (v or "").strip() for k, v in raw.items() if k}
        if not any(r.values()):
            continue
        problems = []
        if not _ID.match(r["id"]) or r["id"] in seen:
            problems.append("id must be unique, letters/digits/dashes")
        if not _ID.match(r["employee_id"]):
            problems.append("employee_id must be letters/digits/dashes")
        try:
            date.fromisoformat(r["date"])
        except ValueError:
            problems.append("date must be YYYY-MM-DD")
        if r["type"] not in TYPES:
            problems.append("type must be supplier or allowance")
        if r["category"] not in CATEGORIES:
            problems.append("category must be freight, supplies, travel or allowance")
        if r["type"] == "supplier" and not (_ID.match(r["supplier_id"]) and r["supplier"]):
            problems.append("a supplier claim needs supplier_id and supplier")
        if not (_TEXT.match(r["supplier"]) and _TEXT.match(r["description"])):
            problems.append("supplier and description: up to 80 plain characters")
        try:
            amount = round(float(r["amount"]), 2)
            if not 0 < amount <= 100_000:
                raise ValueError
        except ValueError:
            problems.append("amount must be a number between 0 and 100,000")
            amount = 0.0
        if problems:
            errors.append(f"row {n}: " + "; ".join(problems))
            if len(errors) >= 10:
                break
            continue
        seen.add(r["id"])
        allowance = r["type"] == "allowance"
        out.append({"id": r["id"], "employee_id": r["employee_id"], "date": r["date"],
                    "type": r["type"],
                    "supplier_id": None if allowance else r["supplier_id"],
                    "supplier": None if allowance else r["supplier"],
                    "category": "allowance" if allowance else r["category"],
                    "description": r["description"], "amount": amount, "status": "open"})
    if errors:
        raise ValueError("; ".join(errors))
    if not out:
        raise ValueError("no claims in the file")
    return out


def _c(cid, emp, d, typ, amount, cat, desc, sid=None, sup=None):
    return {"id": cid, "employee_id": emp, "date": d, "type": typ, "supplier_id": sid,
            "supplier": sup, "category": cat, "description": desc, "amount": amount,
            "status": "open"}


# Prepared scenarios. Each uses employees and suppliers the other departments
# hold (see fixtures.py), plus one they don't, so every path shows up somewhere.
SCENARIOS = {
    "northwind-q3": {
        "title": "Northwind Q3 audit",
        "summary": "47 claims across freight, supplies, travel and allowances. The guided demo's data: one refusal, a grant request, and an overpayment found after approval.",
        "demo": True,
        "claims": DATASETS["expense-auditor"]["Expense.Claim"],
    },
    "supplier-review": {
        "title": "Supplier spend review",
        "summary": "12 supplier invoices checked against Operations' contracts. Two over contract, one duplicate, one supplier with no contract on file. No restricted data needed.",
        "demo": False,
        "claims": [
            _c("INV-501", "E-1042", "2026-07-03", "supplier", 128.50, "freight", "Pallet freight to Leeds DC", "SUP-014", "Northwind Logistics"),
            _c("INV-502", "E-1088", "2026-07-09", "supplier", 384.00, "freight", "Three-day haulage, Bristol", "SUP-027", "Harbour Freight Co"),
            _c("INV-503", "E-1088", "2026-07-21", "supplier", 610.00, "freight", "Return haulage, Bristol", "SUP-027", "Harbour Freight Co"),
            _c("INV-504", "E-1153", "2026-08-04", "supplier", 41.25, "supplies", "Printer toner", "SUP-033", "Calder Office Supply"),
            _c("INV-505", "E-1153", "2026-08-04", "supplier", 41.25, "supplies", "Printer toner", "SUP-033", "Calder Office Supply"),
            _c("INV-506", "E-1247", "2026-08-12", "supplier", 165.00, "supplies", "Desk chairs, two", "SUP-033", "Calder Office Supply"),
            _c("INV-507", "E-1247", "2026-08-19", "supplier", 240.00, "supplies", "Shelving units", "SUP-033", "Calder Office Supply"),
            _c("INV-508", "E-1290", "2026-08-25", "supplier", 257.00, "freight", "Two-day freight, Leeds", "SUP-014", "Northwind Logistics"),
            _c("INV-509", "E-1201", "2026-09-02", "supplier", 96.00, "freight", "Courier, samples", "SUP-027", "Harbour Freight Co"),
            _c("INV-510", "E-1042", "2026-09-08", "supplier", 420.00, "freight", "Event logistics", "SUP-088", "Blue Fern Events"),
            _c("INV-511", "E-1290", "2026-09-15", "supplier", 128.50, "freight", "Pallet freight to York", "SUP-014", "Northwind Logistics"),
            _c("INV-512", "E-1153", "2026-09-29", "supplier", 82.50, "supplies", "Stationery", "SUP-033", "Calder Office Supply"),
        ],
    },
    "travel-allowances": {
        "title": "Travel and allowances",
        "summary": "10 travel bookings and allowances. Checking them needs People & Culture's roster and its restricted salary bands, so expect a refusal and a request to the owner.",
        "demo": False,
        "claims": [
            _c("TRV-701", "E-1201", "2026-07-13", "supplier", 620.00, "travel", "Client visit, Edinburgh - rail", "SUP-041", "Meridian Travel"),
            _c("TRV-702", "E-1201", "2026-07-28", "supplier", 455.00, "travel", "Workshop, Cardiff - flights", "SUP-041", "Meridian Travel"),
            _c("TRV-703", "E-1290", "2026-09-12", "supplier", 310.00, "travel", "Supplier audit, Hull - rail", "SUP-041", "Meridian Travel"),
            _c("TRV-704", "E-1088", "2026-08-06", "supplier", 980.00, "travel", "Trade fair, Birmingham", "SUP-041", "Meridian Travel"),
            _c("TRV-705", "E-1153", "2026-09-10", "supplier", 1480.00, "travel", "Board offsite, Dublin", "SUP-041", "Meridian Travel"),
            _c("ALW-801", "E-1042", "2026-07-02", "allowance", 410.00, "allowance", "Daily travel allowance"),
            _c("ALW-802", "E-1153", "2026-09-10", "allowance", 520.00, "allowance", "Daily travel allowance"),
            _c("ALW-803", "E-1290", "2026-09-22", "allowance", 300.00, "allowance", "Daily travel allowance"),
            _c("ALW-804", "E-1247", "2026-08-18", "allowance", 330.00, "allowance", "Daily travel allowance"),
            _c("ALW-805", "E-1999", "2026-09-30", "allowance", 150.00, "allowance", "Daily travel allowance"),
        ],
    },
}
DEFAULT = "northwind-q3"
