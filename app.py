"""
AW Client Report Portal — Consolidated Flask Application

A web portal for financial advisors at Windbrook Solutions to generate
professional, in-browser PDF reports for millionaire clients.

Provides:
  - SACS (Simple Automated Cash Flow System) → cashflow diagram PDF
  - TCC (Total Client Chart)                  → net worth overview PDF
  - Combined ZIP download when both reports are available

Modules consolidated into this single file:
  1. Calculation engine       (calculate_report_data)
  2. SACS PDF generator       (generate_sacs_pdf)
  3. TCC PDF generator        (generate_tcc_pdf)
  4. Flask routes             (/, /calculate, /generate-pdf)
"""

# ======================================================================
# Imports
# ======================================================================

# ── Standard Library ─────────────────────────────────────────────
import io
import os
import time
import zipfile
from typing import Any, Dict, Union

# ── Third-Party ──────────────────────────────────────────────────
from flask import Flask, jsonify, render_template, request, send_file
from flask_cors import CORS
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.colors import HexColor, white, black


# ======================================================================
# Color Palette
# ======================================================================

NAVY = HexColor("#1a2744")
GREEN = HexColor("#27ae60")
RED = HexColor("#e74c3c")
BLUE = HexColor("#2980b9")
PURPLE = HexColor("#8e44ad")
GRAY = HexColor("#95a5a6")
DARK_TEXT = HexColor("#2c3e50")
LIGHT_BG = HexColor("#f0f4f8")
DIVIDER = HexColor("#d1d8e0")


# ======================================================================
# Utility Helpers
# ======================================================================

def _fmt(n: float) -> str:
    """Format a number as US currency: $X,XXX.XX"""
    return "${:,.2f}".format(n)


def _safe_sum(values: Any) -> float:
    """Sum a list of numbers, gracefully handling None / non-list values."""
    if not isinstance(values, (list, tuple)):
        return 0.0
    return sum(v for v in values if isinstance(v, (int, float)))


def _safe_liability_sum(liabilities: Any) -> float:
    """Sum the 'balance' field of each liability in a list of dicts."""
    if not isinstance(liabilities, (list, tuple)):
        return 0.0
    total = 0.0
    for item in liabilities:
        if isinstance(item, dict):
            balance = item.get("balance", 0)
            if isinstance(balance, (int, float)):
                total += balance
    return total


# ======================================================================
# Calculation Engine  (SACS & TCC)
# ======================================================================

def calculate_report_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Primary calculation engine.

    Accepts raw financial inputs and returns a **new** dictionary
    containing all original inputs plus computed SACS and TCC metrics.

    Parameters
    ----------
    data : dict
        Raw client financial data with keys: client_name, report_date,
        inflow, outflow, monthly_expenses, insurance_deductibles,
        client1_retirement_accounts, client2_retirement_accounts,
        non_retirement_accounts, trust_value, liabilities.

    Returns
    -------
    dict
        New dictionary with original inputs plus all calculated fields.
        Original input data is never mutated.
    """
    # Defensive copies of list inputs
    client1_retirement = list(data.get("client1_retirement_accounts") or [])
    client2_retirement = list(data.get("client2_retirement_accounts") or [])
    non_retirement = list(data.get("non_retirement_accounts") or [])
    liabilities = list(data.get("liabilities") or [])

    inflow = data.get("inflow", 0) or 0
    outflow = data.get("outflow", 0) or 0
    monthly_expenses = data.get("monthly_expenses", 0) or 0
    insurance_deductibles = data.get("insurance_deductibles", 0) or 0
    trust_value = data.get("trust_value", 0) or 0

    # ── SACS — Cash Flow ──────────────────────────────────────────
    excess = round(inflow - outflow, 2)
    private_reserve_target = round(
        (6 * monthly_expenses) + insurance_deductibles, 2
    )

    # ── TCC — Net Worth ───────────────────────────────────────────
    client1_retirement_total = round(_safe_sum(client1_retirement), 2)
    client2_retirement_total = round(_safe_sum(client2_retirement), 2)
    non_retirement_total = round(_safe_sum(non_retirement), 2)
    liabilities_total = round(_safe_liability_sum(liabilities), 2)

    grand_total_net_worth = round(
        client1_retirement_total
        + client2_retirement_total
        + non_retirement_total
        + trust_value,
        2,
    )

    return {
        # Original inputs
        "client_name": data.get("client_name", ""),
        "report_date": data.get("report_date", ""),
        "inflow": inflow,
        "outflow": outflow,
        "monthly_expenses": monthly_expenses,
        "insurance_deductibles": insurance_deductibles,
        "client1_retirement_accounts": client1_retirement,
        "client2_retirement_accounts": client2_retirement,
        "non_retirement_accounts": non_retirement,
        "trust_value": trust_value,
        "liabilities": liabilities,
        # SACS results
        "sacs_excess": excess,
        "sacs_private_reserve_target": private_reserve_target,
        # TCC results
        "tcc_client1_retirement_total": client1_retirement_total,
        "tcc_client2_retirement_total": client2_retirement_total,
        "tcc_non_retirement_total": non_retirement_total,
        "tcc_liabilities_total": liabilities_total,
        "tcc_grand_total_net_worth": grand_total_net_worth,
        # Metadata
        "calculation_status": "ok",
    }


# ======================================================================
# SACS PDF Generator
# ======================================================================
#
# Coordinate system (ReportLab default):
#   y=0 at page bottom, y=595.28 at page top (A4 landscape)
#   x=0 at page left,  x=841.89 at page right (A4 landscape)
#
# A4 landscape dimensions: 841.89 x 595.28 pt
# ======================================================================

def _sacs_draw_page_border(c: canvas.Canvas) -> None:
    """2pt navy border inset 5pt from page edges (A4 landscape)."""
    pw, ph = landscape(A4)  # 841.89 x 595.28
    c.setStrokeColor(NAVY)
    c.setLineWidth(2)
    c.rect(5, 5, pw - 10, ph - 10)


def _sacs_draw_header(c: canvas.Canvas, data: dict) -> None:
    """Full-width navy header bar at the top of the page (55pt tall)."""
    pw, ph = landscape(A4)

    c.setFillColor(NAVY)
    c.rect(0, ph - 55, pw, 55, fill=True, stroke=False)

    # Header text (y = ph - 38, centered 17pt above bar bottom)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, ph - 38, "Windbrook Solutions")

    c.setFont("Helvetica", 11)
    c.drawString(190, ph - 38, "|")

    c.setFont("Helvetica-Bold", 11)
    c.drawString(205, ph - 38, "SACS Report")

    c.setFont("Helvetica", 11)
    c.drawString(310, ph - 38, "|")

    c.setFont("Helvetica", 11)
    c.drawString(325, ph - 38, data.get("client_name", "N/A"))

    c.setFont("Helvetica", 10)
    c.drawRightString(pw - 40, ph - 38, data.get("report_date", "N/A"))


def _sacs_draw_flow_boxes(c: canvas.Canvas, data: dict) -> dict:
    """
    Draw three colored flow boxes and return edge coordinates for arrows.

    All boxes vertically centered at y=320, each 140pt tall.
    """
    inflow = data.get("inflow", 0)
    outflow = data.get("outflow", 0)
    private_balance = data.get("private_reserve_balance", 0)
    private_target = data.get("private_reserve_target", 0)

    box_height = 140
    box_y = 250  # bottom of all boxes

    # ── LEFT BOX (Green — Inflow) ──────────────────────────────
    left_x, left_width = 60, 200

    c.setFillColor(GREEN)
    c.roundRect(left_x, box_y, left_width, box_height, 12, fill=True, stroke=False)

    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(left_x + left_width / 2, box_y + 80, "INFLOW")
    c.setFont("Helvetica", 13)
    c.drawCentredString(left_x + left_width / 2, box_y + 50, f"{_fmt(inflow)}/mo")

    # ── MIDDLE BOX (Red — Outflow) ─────────────────────────────
    mid_x, mid_width = 320, 200

    c.setFillColor(RED)
    c.roundRect(mid_x, box_y, mid_width, box_height, 12, fill=True, stroke=False)

    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(mid_x + mid_width / 2, box_y + 80, "OUTFLOW")
    c.setFont("Helvetica", 13)
    c.drawCentredString(mid_x + mid_width / 2, box_y + 50, f"{_fmt(outflow)}/mo")

    # ── RIGHT BOX (Blue — Private Reserve) ─────────────────────
    right_x, right_width = 580, 220

    c.setFillColor(BLUE)
    c.roundRect(right_x, box_y, right_width, box_height, 12, fill=True, stroke=False)

    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(right_x + right_width / 2, box_y + 85, "PRIVATE RESERVE")
    c.setFont("Helvetica", 11)
    c.drawCentredString(right_x + right_width / 2, box_y + 60, f"Balance: {_fmt(private_balance)}")
    c.drawCentredString(right_x + right_width / 2, box_y + 38, f"Target: {_fmt(private_target)}")

    center_y = box_y + box_height / 2  # y=320
    return {
        "left": {
            "left_x": left_x, "right_x": left_x + left_width,
            "center_y": center_y, "top_y": box_y + box_height, "bottom_y": box_y,
        },
        "middle": {
            "left_x": mid_x, "right_x": mid_x + mid_width,
            "center_y": center_y, "top_y": box_y + box_height, "bottom_y": box_y,
        },
        "right": {
            "left_x": right_x, "right_x": right_x + right_width,
            "center_y": center_y, "top_y": box_y + box_height, "bottom_y": box_y,
        },
    }


def _sacs_draw_arrows(c: canvas.Canvas, data: dict, boxes: dict) -> None:
    """
    Draw arrows between flow boxes.

    Arrow 1 (solid black): LEFT box -> MIDDLE box (expenses flow)
    Arrow 2 (dashed blue): LEFT box -> RIGHT box (excess, arcs above middle)
    """
    outflow = data.get("outflow", 0)
    excess = data.get("excess", 0)
    arrow_size = 10

    left_right = boxes["left"]["right_x"]    # x=260
    mid_left = boxes["middle"]["left_x"]     # x=320
    center_y = boxes["left"]["center_y"]     # y=320

    # Arrow 1: Solid black line LEFT -> MIDDLE
    c.setStrokeColor(black)
    c.setLineWidth(1.5)
    c.setDash()
    line_end_x = mid_left - arrow_size
    c.line(left_right, center_y, line_end_x, center_y)
    c.line(mid_left, center_y, mid_left - arrow_size, center_y + 6)
    c.line(mid_left, center_y, mid_left - arrow_size, center_y - 6)

    # Label: outflow amount
    label_x = (left_right + mid_left) / 2  # ~290
    c.setFillColor(DARK_TEXT)
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(label_x, center_y + 18, f"{_fmt(outflow)}")
    c.setFillColor(RED)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(label_x, center_y - 14, "\u2716  \u2192 Expenses")

    # Arrow 2: Dashed blue line LEFT -> RIGHT (above middle box)
    right_left = boxes["right"]["left_x"]    # x=580
    dashed_y = boxes["left"]["top_y"] + 50   # y=440 (increased gap from boxes)

    c.setStrokeColor(BLUE)
    c.setLineWidth(1.5)
    c.setDash(5, 3)
    c.line(left_right + 5, dashed_y, right_left - 5, dashed_y)
    c.setDash()
    c.line(right_left - 5, dashed_y, right_left - 5 - arrow_size, dashed_y + 6)
    c.line(right_left - 5, dashed_y, right_left - 5 - arrow_size, dashed_y - 6)
    c.line(left_right + 5, dashed_y, left_right + 5 + arrow_size, dashed_y + 6)
    c.line(left_right + 5, dashed_y, left_right + 5 + arrow_size, dashed_y - 6)

    # Excess label
    excess_label_x = (left_right + right_left) / 2  # ~420
    c.setFillColor(BLUE)
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(excess_label_x, dashed_y + 16, f"Excess: {_fmt(excess)}/mo")
    c.setFont("Helvetica", 8)
    c.drawCentredString(excess_label_x, dashed_y - 30, "(Flows to Private Reserve)")


def _sacs_draw_summary_row(c: canvas.Canvas, data: dict) -> None:
    """
    Summary row below the boxes showing savings rate and reserve status.
    """
    inflow = data.get("inflow", 0)
    outflow = data.get("outflow", 0)
    excess = data.get("excess", 0)
    balance = data.get("private_reserve_balance", 0)
    target = data.get("private_reserve_target", 0)
    pw, _ph = landscape(A4)

    savings_rate = (excess / inflow * 100) if inflow > 0 else 0
    annual_excess = excess * 12
    on_track = balance >= target

    # Background strip
    strip_y = 175
    strip_height = 55
    c.setFillColor(LIGHT_BG)
    c.rect(40, strip_y, pw - 80, strip_height, fill=True, stroke=False)

    c.setStrokeColor(DIVIDER)
    c.setLineWidth(0.5)
    c.line(40, strip_y + strip_height, pw - 40, strip_y + strip_height)

    label_y = strip_y + 36
    value_y = strip_y + 18

    # Savings Rate
    c.setFillColor(DARK_TEXT)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(60, label_y, "Monthly Savings Rate")
    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(GREEN if savings_rate >= 0 else RED)
    c.drawString(60, value_y, f"{savings_rate:.1f}%")

    # Annual Excess
    c.setFillColor(DARK_TEXT)
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(pw / 2 - 40, label_y, "Annual Excess")
    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(GREEN if annual_excess >= 0 else RED)
    c.drawCentredString(pw / 2 - 40, value_y, f"{_fmt(annual_excess)}")

    # Reserve Status
    c.setFillColor(DARK_TEXT)
    c.setFont("Helvetica-Bold", 9)
    c.drawRightString(pw - 60, label_y, "Private Reserve Status")
    c.setFont("Helvetica-Bold", 13)
    if on_track:
        c.setFillColor(GREEN)
        c.drawRightString(pw - 60, value_y, "\u2705 On Track")
    else:
        c.setFillColor(RED)
        c.drawRightString(pw - 60, value_y, "\u26A0\uFE0F Below Target")


def _sacs_draw_footer(c: canvas.Canvas, data: dict) -> None:
    """Navy footer bar at the bottom of the page (y=0 to y=35)."""
    pw, _ph = landscape(A4)

    c.setFillColor(NAVY)
    c.rect(0, 0, pw, 35, fill=True, stroke=False)

    c.setFillColor(white)
    c.setFont("Helvetica", 9)
    c.drawString(40, 12, "Confidential")
    c.drawCentredString(pw / 2, 12, "Windbrook Solutions")
    c.drawRightString(pw - 40, 12, data.get("report_date", "N/A"))


def generate_sacs_pdf(data: dict, output: Union[str, io.BytesIO]) -> None:
    """
    Generate a one-page A4 landscape SACS cashflow diagram PDF.

    Parameters
    ----------
    data : dict
        Must contain: client_name, report_date, inflow, outflow, excess,
        private_reserve_balance, private_reserve_target.
    output : str | io.BytesIO
        File path or BytesIO buffer. ReportLab Canvas accepts both.
    """
    c = canvas.Canvas(output, pagesize=landscape(A4))

    _sacs_draw_page_border(c)
    _sacs_draw_header(c, data)
    boxes = _sacs_draw_flow_boxes(c, data)
    _sacs_draw_arrows(c, data, boxes)
    _sacs_draw_summary_row(c, data)
    _sacs_draw_footer(c, data)

    c.showPage()
    c.save()


# ======================================================================
# TCC PDF Generator
# ======================================================================
#
# Coordinate system (ReportLab default):
#   y=0 at page bottom, y=841.89 at page top (A4 portrait)
#   x=0 at page left,  x=595.28 at page right (A4 portrait)
#
# A4 portrait dimensions: 595.28 x 841.89 pt
# ======================================================================

def _tcc_draw_page_border(c: canvas.Canvas) -> None:
    """2pt navy border inset 5pt from page edges (A4 portrait)."""
    pw, ph = A4  # 595.28 x 841.89
    c.setStrokeColor(NAVY)
    c.setLineWidth(2)
    c.rect(5, 5, pw - 10, ph - 10)


def _tcc_draw_header(c: canvas.Canvas, data: dict) -> None:
    """
    Full-width navy header bar at the top of the page.

    Header bar: y=PH-55 to y=PH (55pt tall).
    """
    pw, ph = A4  # 595.28 x 841.89

    c.setFillColor(NAVY)
    c.rect(0, ph - 55, pw, 55, fill=True, stroke=False)

    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, ph - 38, "Windbrook Solutions")

    c.setFont("Helvetica", 11)
    c.drawString(190, ph - 38, "|")

    c.setFont("Helvetica-Bold", 11)
    c.drawString(205, ph - 38, "TCC Report")

    c.setFont("Helvetica", 11)
    c.drawString(310, ph - 38, "|")

    c.setFont("Helvetica", 11)
    c.drawString(325, ph - 38, data.get("client_name", "N/A"))

    c.setFont("Helvetica", 10)
    c.drawRightString(pw - 40, ph - 38, data.get("report_date", "N/A"))


def _tcc_draw_section_header(
    c: canvas.Canvas, x: float, y: float,
    width: float, height: float,
    color: HexColor, title: str,
) -> None:
    """Draw a colored section header bar with white text."""
    c.setFillColor(color)
    c.rect(x, y, width, height, fill=True, stroke=False)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(x + 8, y + (height - 13) / 2, title)


def _tcc_draw_item_row(
    c: canvas.Canvas, x: float, y: float,
    width: float, label: str, value: str,
    secondary: str = "",
) -> None:
    """Draw a single account row: label on left, value on right."""
    c.setFillColor(DARK_TEXT)
    c.setFont("Helvetica", 9)
    c.drawString(x + 4, y, label)

    if secondary:
        c.setFillColor(GRAY)
        c.setFont("Helvetica", 8)
        c.drawString(x + 4, y - 11, secondary)

    c.setFillColor(DARK_TEXT)
    c.setFont("Helvetica-Bold", 9)
    c.drawRightString(x + width - 4, y, value)


def _tcc_draw_section_total(
    c: canvas.Canvas, x: float, y: float,
    width: float, value: str,
) -> None:
    """Draw a bold total row with a thin top line."""
    c.setStrokeColor(DIVIDER)
    c.setLineWidth(0.5)
    c.line(x, y + 16, x + width, y + 16)

    c.setFillColor(DARK_TEXT)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x + 4, y, "Total")
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(x + width - 4, y, value)


def _tcc_draw_account_section(
    c: canvas.Canvas, x: float, top_y: float,
    width: float, color: HexColor, title: str,
    accounts: list, total: float,
    show_rate: bool = False,
) -> float:
    """
    Draw a complete accounts section flowing DOWNWARD from top_y.

    Layout (top to bottom):
      top_y  ─────── header top edge
        [header: 20pt tall]
        [6pt gap]
        [items: 22pt each]
        [6pt gap]
        [total: 18pt tall with divider above]
        [16pt gap to next section]

    Returns the top_y for the next section.
    """
    header_h = 20
    item_h = 22
    total_h = 18
    gap = 16

    # 1. Header bar (extends upward from header_bottom)
    header_bottom = top_y - header_h
    _tcc_draw_section_header(c, x, header_bottom, width, header_h, color, title)

    # 2. Gap after header
    y = header_bottom - 6

    # 3. Items
    actual_item_h = item_h + (6 if show_rate else 0)  # extra space for rate text
    if not accounts:
        c.setFillColor(GRAY)
        c.setFont("Helvetica-Oblique", 9)
        c.drawString(x + 8, y, "\u2014")
        y -= actual_item_h
    else:
        for acct in accounts:
            acct_type = acct.get("type") or acct.get("name", "")
            balance = acct.get("balance", 0)
            secondary = ""
            if show_rate and "rate" in acct:
                secondary = f"Rate: {acct['rate']:.2f}%"
            _tcc_draw_item_row(c, x, y, width, acct_type, _fmt(balance), secondary)
            y -= actual_item_h

    # 4. Gap before total
    y -= 6

    # 5. Total row
    _tcc_draw_section_total(c, x, y, width, _fmt(total))
    y -= total_h

    # 6. Return next section's top_y (with gap)
    return y - gap


def _tcc_generate_content(c: canvas.Canvas, data: dict) -> None:
    """Generate all content sections of the TCC report."""
    client1_name = data.get("client1_name", "Client 1")
    client2_name = data.get("client2_name", "Client 2")

    client1_accounts = data.get("client1_retirement") or []
    client2_accounts = data.get("client2_retirement") or []
    non_retirement_accounts = data.get("non_retirement") or []
    liabilities = data.get("liabilities") or []
    trust_value = data.get("trust_value", 0)
    trust_address = data.get("trust_address", "")

    totals = data.get("totals", {})
    c1_total = totals.get("client1_retirement", sum(a.get("balance", 0) for a in client1_accounts))
    c2_total = totals.get("client2_retirement", sum(a.get("balance", 0) for a in client2_accounts))
    nr_total = totals.get("non_retirement", sum(a.get("balance", 0) for a in non_retirement_accounts))
    grand_total = totals.get("grand_total", 0)
    liab_total = totals.get("liabilities", sum(a.get("balance", 0) for a in liabilities))

    col1_x, col1_w = 40, 240   # LEFT column
    col2_x, col2_w = 305, 250  # RIGHT column
    col_top = A4[1] - 62       # ~779.89 — top_y for first row sections

    # LEFT — Client 1 Retirement
    c1_bottom = _tcc_draw_account_section(
        c, col1_x, col_top, col1_w,
        GREEN, f"{client1_name} \u2014 Retirement",
        client1_accounts, c1_total,
    )

    # RIGHT — Client 2 Retirement
    c2_bottom = _tcc_draw_account_section(
        c, col2_x, col_top, col2_w,
        BLUE, f"{client2_name} \u2014 Retirement",
        client2_accounts, c2_total,
    )

    # LEFT — Non-Retirement / Joint
    nr_bottom = _tcc_draw_account_section(
        c, col1_x, c1_bottom, col1_w,
        PURPLE, "Non-Retirement / Joint",
        non_retirement_accounts, nr_total,
    )

    # LEFT — Trust section
    trust_header_h = 20
    trust_content_h = 60
    trust_top = nr_bottom  # top_y for Trust header

    _tcc_draw_section_header(c, col1_x, trust_top - trust_header_h, col1_w, trust_header_h, GRAY, "Trust")

    # Content background (below the header)
    c.setFillColor(HexColor("#fafafa"))
    c.rect(col1_x, trust_top - trust_header_h - trust_content_h, col1_w, trust_content_h, fill=True, stroke=False)

    # Text inside content area: 6pt gap below header, then value + label
    content_y = trust_top - trust_header_h - 6 - 14  # inside bg rect
    c.setFillColor(DARK_TEXT)
    c.setFont("Helvetica", 9)
    c.drawString(col1_x + 8, content_y, trust_address if trust_address else "\u2014")
    c.setFont("Helvetica", 8)
    c.setFillColor(GRAY)
    c.drawString(col1_x + 8, content_y - 10, "Estimated value")
    c.setFillColor(DARK_TEXT)
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(col1_x + col1_w - 8, content_y, _fmt(trust_value))

    trust_bottom = trust_top - trust_header_h - trust_content_h  # bottom of bg rect

    # RIGHT — Liabilities
    liab_bottom = _tcc_draw_account_section(
        c, col2_x, c2_bottom, col2_w,
        RED, "Liabilities",
        liabilities, liab_total,
        show_rate=True,
    )

    # Summary totals bar — aligned to lowest section bottom
    content_bottom = min(trust_bottom, liab_bottom)
    summary_y = content_bottom - 15
    bar_h = 48
    c.setFillColor(LIGHT_BG)
    c.rect(40, summary_y - bar_h, A4[0] - 80, bar_h, fill=True, stroke=False)
    c.setStrokeColor(DIVIDER)
    c.setLineWidth(0.5)
    c.line(40, summary_y, A4[0] - 40, summary_y)

    metrics = [
        ("Client 1 Retirement", _fmt(c1_total)),
        ("Client 2 Retirement", _fmt(c2_total)),
        ("Non-Retirement", _fmt(nr_total)),
        ("Grand Total", _fmt(grand_total)),
    ]
    bar_content_w = A4[0] - 100
    col_w = bar_content_w / len(metrics)

    for i, (label, value) in enumerate(metrics):
        col_mid = 55 + (col_w * i) + col_w / 2
        c.setFillColor(DARK_TEXT)
        c.setFont("Helvetica-Bold", 7)
        c.drawCentredString(col_mid, summary_y - 8, label)
        c.setFillColor(GREEN if i == len(metrics) - 1 else DARK_TEXT)
        c.setFont("Helvetica-Bold", 12 if i == len(metrics) - 1 else 10)
        c.drawCentredString(col_mid, summary_y - 26, value)

    # Disclaimer
    c.setFillColor(GRAY)
    c.setFont("Helvetica-Oblique", 7)
    c.drawCentredString(
        A4[0] / 2, summary_y - bar_h - 14,
        "Liabilities shown separately \u2014 not subtracted from net worth per client preference",
    )


def _tcc_draw_footer(c: canvas.Canvas, data: dict) -> None:
    """Navy footer bar at the bottom of the page (y=0 to y=35)."""
    pw, _ph = A4

    c.setFillColor(NAVY)
    c.rect(0, 0, pw, 35, fill=True, stroke=False)

    c.setFillColor(white)
    c.setFont("Helvetica", 9)
    c.drawString(40, 12, "Confidential")
    c.drawCentredString(pw / 2, 12, "Windbrook Solutions")
    c.drawRightString(pw - 40, 12, data.get("report_date", "N/A"))


def generate_tcc_pdf(data: dict, output: Union[str, io.BytesIO]) -> None:
    """
    Generate a one-page A4 portrait TCC net worth overview PDF.

    Parameters
    ----------
    data : dict
        Must contain: client_name, report_date, client1_name, client2_name,
        client1_retirement (list of dicts with type/balance),
        client2_retirement (list), non_retirement (list),
        trust_value, trust_address, liabilities (list with name/balance/rate),
        totals (dict with all total values).
    output : str | io.BytesIO
        File path or BytesIO buffer for in-memory generation.
    """
    c = canvas.Canvas(output, pagesize=A4)

    _tcc_draw_page_border(c)
    _tcc_draw_header(c, data)
    _tcc_generate_content(c, data)
    _tcc_draw_footer(c, data)

    c.showPage()
    c.save()


# ======================================================================
# Data Mapping Helpers
# ======================================================================

def _build_sacs_data(raw_data: dict, calculated: dict) -> dict:
    """Map raw + calculated data into generate_sacs_pdf input format."""
    return {
        "client_name": calculated.get("client_name", ""),
        "report_date": calculated.get("report_date", ""),
        "inflow": calculated.get("inflow", 0),
        "outflow": calculated.get("outflow", 0),
        "excess": calculated.get("sacs_excess", 0),
        "private_reserve_balance": raw_data.get("private_reserve_balance", 0),
        "private_reserve_target": calculated.get("sacs_private_reserve_target", 0),
        "insurance_deductibles": calculated.get("insurance_deductibles", 0),
        "monthly_expenses": calculated.get("monthly_expenses", 0),
    }


def _build_tcc_data(raw_data: dict, calculated: dict) -> dict:
    """Map raw + calculated data into generate_tcc_pdf input format."""
    c1_accts = raw_data.get("client1_retirement_accounts") or []
    c2_accts = raw_data.get("client2_retirement_accounts") or []
    nr_accts = raw_data.get("non_retirement_accounts") or []
    liabilities = raw_data.get("liabilities") or []

    def _to_accts(numbers, prefix="Account"):
        return [
            {"type": f"{prefix} {i + 1}", "balance": float(val)}
            for i, val in enumerate(numbers)
        ]

    client1_name = raw_data.get("client1_name", calculated.get("client_name", "Client 1"))
    client2_name = raw_data.get("client2_name", "Client 2")

    c1_total = calculated.get("tcc_client1_retirement_total", 0)
    c2_total = calculated.get("tcc_client2_retirement_total", 0)
    nr_total = calculated.get("tcc_non_retirement_total", 0)
    liab_total = calculated.get("tcc_liabilities_total", 0)
    trust_val = calculated.get("trust_value", 0)
    grand_total = calculated.get("tcc_grand_total_net_worth", 0)

    return {
        "client_name": calculated.get("client_name", ""),
        "client1_name": client1_name,
        "client2_name": client2_name,
        "report_date": calculated.get("report_date", ""),
        "client1_retirement": _to_accts(c1_accts),
        "client2_retirement": _to_accts(c2_accts),
        "non_retirement": _to_accts(nr_accts),
        "trust_value": trust_val,
        "trust_address": "",  # not available from simplified form
        "liabilities": liabilities,
        "totals": {
            "client1_retirement": c1_total,
            "client2_retirement": c2_total,
            "non_retirement": nr_total,
            "grand_total": grand_total,
            "liabilities": liab_total,
        },
    }


# ======================================================================
# Flask App Initialization
# ======================================================================

app = Flask(__name__)
CORS(app)


# ======================================================================
# Routes
# ======================================================================

@app.route("/")
def index():
    """Serve the main single-page application."""
    return render_template("index.html")


@app.route("/calculate", methods=["POST"])
def calculate():
    """Accept JSON financial data, return calculated SACS + TCC results."""
    data = request.get_json(force=True)
    return jsonify(calculate_report_data(data))


@app.route("/generate-pdf", methods=["POST"])
def generate_pdf():
    """
    Accept JSON financial data, return downloadable PDF(s).

    Generates a SACS cashflow diagram PDF and a TCC net worth overview PDF.
    Both are bundled into a ZIP file for download.

    Returns 400 if required fields are missing, 500 on server error.
    """
    try:
        data = request.get_json(force=True)

        # ── Validate required fields ──────────────────────────────
        client_name = (data.get("client_name") or "").strip()
        if not client_name:
            return jsonify({"error": "Client name is required"}), 400

        inflow = data.get("inflow")
        outflow = data.get("outflow")
        if inflow is None or not str(inflow).strip():
            return jsonify({"error": "Monthly inflow is required"}), 400
        if outflow is None or not str(outflow).strip():
            return jsonify({"error": "Monthly outflow is required"}), 400

        # ── Run calculations ──────────────────────────────────────
        calculated = calculate_report_data(data)
        report_date = calculated.get("report_date", "") or "report"
        safe_name = client_name.replace(" ", "_").replace("&", "and")

        timestamp = int(time.time() * 1000)

        # ── Generate SACS PDF ─────────────────────────────────────
        sacs_path = f"/tmp/sacs_{timestamp}.pdf"
        sacs_data = _build_sacs_data(data, calculated)
        generate_sacs_pdf(sacs_data, sacs_path)
        temp_files = [sacs_path]

        # ── Generate TCC PDF ──────────────────────────────────────
        tcc_path = f"/tmp/tcc_{timestamp}.pdf"
        tcc_data = _build_tcc_data(data, calculated)
        generate_tcc_pdf(tcc_data, tcc_path)
        temp_files.append(tcc_path)

        # ── Bundle both PDFs into a ZIP ───────────────────────────
        try:
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(sacs_path, f"{safe_name}_SACS_{report_date}.pdf")
                zf.write(tcc_path, f"{safe_name}_TCC_{report_date}.pdf")
            zip_buffer.seek(0)

            return send_file(
                zip_buffer,
                mimetype="application/zip",
                as_attachment=True,
                download_name=f"{safe_name}_Reports_{report_date}.zip",
            )
        finally:
            for f in temp_files:
                try:
                    if os.path.exists(f):
                        os.remove(f)
                except OSError:
                    pass  # best-effort cleanup

    except Exception as e:
        return jsonify({"error": f"Server error: {str(e)}"}), 500


# ======================================================================
# Entry Point
# ======================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
