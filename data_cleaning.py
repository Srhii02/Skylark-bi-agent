"""
Normalizes raw monday.com rows into analysis-ready records, and tracks data
quality issues so the agent can surface caveats instead of silently guessing.

Handles, specifically (found by inspecting the real sample data):
  - Corrupted/garbage rows where a header row got re-entered as data
    (e.g. a "deal" whose Deal Status literally equals "Deal Status").
  - Numbers with embedded units in the same field ("5360 HA", "4 mines",
    "45days", "NA", "2 location") — extracted to a clean float + unit.
  - Spreadsheet error strings ("#VALUE!") in numeric fields.
  - Inconsistent date formats — parsed defensively, invalid values dropped
    rather than crashing.
  - Missing values everywhere — never assumed to be zero; tracked explicitly.
  - Sector spelled/cased inconsistently across the two boards.
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from dateutil import parser as dateparser

NUMERIC_UNIT_RE = re.compile(r"^\s*([\d,]+\.?\d*)\s*([A-Za-z][A-Za-z /]*)?\s*$")
ERROR_STRINGS = {"#VALUE!", "#N/A", "#REF!", "#DIV/0!", "N/A", "NA", "-", ""}

SECTOR_SYNONYMS = {
    "dsp": "DSP",
    "mining": "Mining",
    "powerline": "Powerline",
    "renewables": "Renewables",
    "railways": "Railways",
    "construction": "Construction",
    "tender": "Tender",
    "security and surveillance": "Security & Surveillance",
    "others": "Others",
    "other": "Others",
}


@dataclass
class CleaningReport:
    board_name: str
    total_rows: int = 0
    dropped_garbage_rows: int = 0
    rows_with_missing_value: dict[str, int] = field(default_factory=dict)
    parse_errors: dict[str, int] = field(default_factory=dict)

    def note_missing(self, field_name: str):
        self.rows_with_missing_value[field_name] = self.rows_with_missing_value.get(field_name, 0) + 1

    def note_parse_error(self, field_name: str):
        self.parse_errors[field_name] = self.parse_errors.get(field_name, 0) + 1

    def summary(self) -> str:
        lines = [f"Data quality — {self.board_name}: {self.total_rows} rows loaded"]
        if self.dropped_garbage_rows:
            lines.append(f"  - {self.dropped_garbage_rows} corrupted row(s) dropped (looked like re-entered headers)")
        for f_, n in sorted(self.rows_with_missing_value.items(), key=lambda x: -x[1])[:6]:
            pct = round(100 * n / max(self.total_rows, 1))
            lines.append(f"  - '{f_}' missing in {n} rows ({pct}%)")
        for f_, n in self.parse_errors.items():
            lines.append(f"  - '{f_}' had {n} unparseable value(s)")
        return "\n".join(lines)


def is_garbage_row(row: dict, known_headers: set[str]) -> bool:
    """A row is treated as a corrupted/re-entered header if any of its
    values literally equal the title of the column it's sitting in
    (this pattern was found in the Deals sample data)."""
    for key, val in row.items():
        if key.startswith("_"):
            continue
        if val and val.strip() in known_headers and val.strip() == key.strip():
            return True
    return False


def parse_number(raw: str | None) -> tuple[float | None, str | None]:
    """Returns (value, unit). Handles '5360 HA', '4', 'NA', '#VALUE!', '1,310.850'."""
    if raw is None:
        return None, None
    text = raw.strip()
    if text in ERROR_STRINGS:
        return None, None
    m = NUMERIC_UNIT_RE.match(text)
    if not m:
        return None, None
    num_str, unit = m.group(1), (m.group(2) or "").strip() or None
    try:
        return float(num_str.replace(",", "")), unit
    except ValueError:
        return None, None


def parse_date(raw: str | None):
    if not raw or raw.strip() in ERROR_STRINGS:
        return None
    try:
        return dateparser.parse(raw.strip(), dayfirst=False, fuzzy=True).date().isoformat()
    except (ValueError, OverflowError, TypeError):
        return None


def normalize_sector(raw: str | None) -> str | None:
    if not raw or raw.strip() in ERROR_STRINGS:
        return None
    key = raw.strip().lower()
    return SECTOR_SYNONYMS.get(key, raw.strip().title())


def clean_deals(raw_rows: list[dict]) -> tuple[list[dict], CleaningReport]:
    report = CleaningReport(board_name="Deals")
    known_headers = {
        "Deal Name", "Owner code", "Client Code", "Deal Status", "Close Date (A)",
        "Closure Probability", "Masked Deal value", "Tentative Close Date",
        "Deal Stage", "Product deal", "Sector/service", "Created Date",
    }
    clean: list[dict] = []
    for row in raw_rows:
        report.total_rows += 1
        if is_garbage_row(row, known_headers):
            report.dropped_garbage_rows += 1
            continue

        value, _ = parse_number(row.get("Masked Deal value"))
        if row.get("Masked Deal value") in (None, "") :
            report.note_missing("Masked Deal value")

        stage = (row.get("Deal Stage") or "").strip() or None
        if not stage:
            report.note_missing("Deal Stage")

        status = (row.get("Deal Status") or "").strip() or None
        if not status:
            report.note_missing("Deal Status")

        sector = normalize_sector(row.get("Sector/service"))
        if not sector:
            report.note_missing("Sector/service")

        tentative_close = parse_date(row.get("Tentative Close Date"))
        created = parse_date(row.get("Created Date"))

        clean.append({
            "item_id": row.get("_item_id"),
            "deal_label": row.get("Deal Name") or row.get("_item_name"),
            "owner_code": (row.get("Owner code") or "").strip() or None,
            "client_code": (row.get("Client Code") or "").strip() or None,
            "status": status,
            "closure_probability": (row.get("Closure Probability") or "").strip() or None,
            "deal_value": value,
            "tentative_close_date": tentative_close,
            "deal_stage": stage,
            "product": (row.get("Product deal") or "").strip() or None,
            "sector": sector,
            "created_date": created,
            "is_open": status not in ("Dead", None) and (stage or "").upper().find("PROJECT LOST") == -1,
        })
    return clean, report


def clean_work_orders(raw_rows: list[dict]) -> tuple[list[dict], CleaningReport]:
    report = CleaningReport(board_name="Work Orders")
    clean: list[dict] = []
    for row in raw_rows:
        report.total_rows += 1

        sector = normalize_sector(row.get("Sector"))
        if not sector:
            report.note_missing("Sector")

        exec_status = (row.get("Execution Status") or "").strip() or None
        if not exec_status:
            report.note_missing("Execution Status")

        billed_excl, _ = parse_number(row.get("Amount in Rupees (Excl of GST) (Masked)"))
        billed_incl, _ = parse_number(row.get("Amount in Rupees (Incl of GST) (Masked)"))
        if row.get("Amount in Rupees (Incl of GST) (Masked)") in (None, "", "#VALUE!"):
            report.note_missing("Amount in Rupees (Incl of GST) (Masked)")
            if row.get("Amount in Rupees (Incl of GST) (Masked)") == "#VALUE!":
                report.note_parse_error("Amount in Rupees (Incl of GST) (Masked)")

        collected, _ = parse_number(row.get("Collected Amount in Rupees (Incl of GST.) (Masked)"))
        receivable, _ = parse_number(row.get("Amount Receivable (Masked)"))

        qty_po, qty_unit = parse_number(row.get("Quantities as per PO"))
        qty_billed, _ = parse_number(row.get("Quantity billed (till date)"))
        qty_balance, _ = parse_number(row.get("Balance in quantity"))

        po_date = parse_date(row.get("Date of PO/LOI"))
        billing_status = (row.get("Billing Status") or "").strip() or None
        wo_status = (row.get("WO Status (billed)") or "").strip() or None

        clean.append({
            "item_id": row.get("_item_id"),
            "deal_label": row.get("Deal name masked") or row.get("_item_name"),
            "customer_code": (row.get("Customer Name Code") or "").strip() or None,
            "serial": (row.get("Serial #") or "").strip() or None,
            "nature_of_work": (row.get("Nature of Work") or "").strip() or None,
            "execution_status": exec_status,
            "po_date": po_date,
            "owner_code": (row.get("BD/KAM Personnel code") or "").strip() or None,
            "sector": sector,
            "type_of_work": (row.get("Type of Work") or "").strip() or None,
            "billed_value_incl_gst": billed_incl,
            "billed_value_excl_gst": billed_excl,
            "collected_incl_gst": collected,
            "amount_receivable": receivable,
            "quantity_po": qty_po,
            "quantity_unit": qty_unit,
            "quantity_billed": qty_billed,
            "quantity_balance": qty_balance,
            "invoice_status": (row.get("Invoice Status") or "").strip() or None,
            "billing_status": billing_status,
            "wo_status": wo_status,
            "is_closed": wo_status == "Closed",
        })
    return clean, report


NOTE_ON_JOINING = (
    "Deals are keyed by 'Client Code' (e.g. COMPANY089) and owned by 'Owner code' "
    "(OWNER_00N). Work Orders are keyed by 'Customer Name Code' (e.g. WOCOMPANY_002) "
    "and owned by 'BD/KAM Personnel code' — which uses the SAME OWNER_00N scheme as "
    "Deals. There is no shared client identifier between the two boards in the sample "
    "data, so deal-to-work-order matching at the individual-record level is not "
    "reliable. Cross-board analysis in this agent is done by shared dimensions instead "
    "(owner code, sector, time period), not by joining individual deal/work-order rows. "
    "See DECISION_LOG.md."
)
