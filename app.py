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
from datetime import date

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
GRAY_BG = HexColor("#f5f6fa")
GRAY_BOX = HexColor("#dfe6e9")


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


def generate_sacs_pdf(data, output):
    """
    Generate a professional SACS (Simple Automated Cash Flow System) PDF
    using ReportLab canvas API.

    Parameters
    ----------
    data : dict
        Must contain: client_name, report_date, inflow, outflow, excess,
        private_reserve_balance, private_reserve_target,
        insurance_deductibles, monthly_expenses.
    output : str | io.BytesIO
        File path or BytesIO buffer.
    """
    W, H = landscape(A4)  # 841.89 x 595.28
    PW, PH = W, H

    client_name = data.get("client_name", "")
    report_date = data.get("report_date", "")
    inflow = data.get("inflow", 0)
    outflow = data.get("outflow", 0)
    excess = data.get("excess", 0)
    pr_balance = data.get("private_reserve_balance", 0)
    pr_target = data.get("private_reserve_target", 0)

    c = canvas.Canvas(output, pagesize=landscape(A4))

    # ================================================================
    # ELEMENT 1: OUTER PAGE BORDER
    # ================================================================
    c.setStrokeColor(NAVY)
    c.setLineWidth(2)
    c.rect(10, 10, PW - 20, PH - 20, stroke=1, fill=0)

    # ================================================================
    # ELEMENT 2: HEADER BAR (y=PH-46 to y=PH)
    # ================================================================
    c.setFillColor(NAVY)
    c.rect(10, PH - 46, PW - 20, 46, stroke=0, fill=1)
    draw_text(c, "WINDBROOK SOLUTIONS", 30, PH - 33, "Helvetica-Bold", 13, white)
    draw_text(c, "SACS \u2014 Cash Flow Analysis", PW / 2, PH - 33, "Helvetica", 10, white, "center")
    draw_text(c, f"{client_name}  |  {report_date}", PW - 30, PH - 33, "Helvetica", 10, white, "right")

    # ================================================================
    # ELEMENT 3: THREE FLOW BOXES
    # ================================================================
    box_h = 140
    box_y = 270  # bottom of boxes
    gap = 30
    box_w = 215

    # Layout: three boxes evenly spaced
    total_content_w = 3 * box_w + 2 * gap
    start_x = (PW - total_content_w) / 2

    left_x = start_x
    mid_x = start_x + box_w + gap
    right_x = start_x + 2 * (box_w + gap)

    # ── INFLOW BOX (GREEN) ─────────────────────────────────────
    draw_rounded_box(c, left_x, box_y, box_w, box_h, 12, GREEN)
    draw_text(c, "INFLOW", left_x + box_w / 2, box_y + 95,
              "Helvetica-Bold", 18, white, "center")
    draw_text(c, f"{fmt(inflow)}/mo", left_x + box_w / 2, box_y + 65,
              "Helvetica", 14, white, "center")
    draw_text(c, "Monthly Income", left_x + box_w / 2, box_y + 18,
              "Helvetica-Oblique", 9, white, "center")

    # ── OUTFLOW BOX (RED) ──────────────────────────────────────
    draw_rounded_box(c, mid_x, box_y, box_w, box_h, 12, RED)
    draw_text(c, "OUTFLOW", mid_x + box_w / 2, box_y + 95,
              "Helvetica-Bold", 18, white, "center")
    draw_text(c, f"{fmt(outflow)}/mo", mid_x + box_w / 2, box_y + 65,
              "Helvetica", 14, white, "center")
    draw_text(c, "Monthly Expenses", mid_x + box_w / 2, box_y + 18,
              "Helvetica-Oblique", 9, white, "center")

    # ── PRIVATE RESERVE BOX (BLUE) ─────────────────────────────
    draw_rounded_box(c, right_x, box_y, box_w, box_h, 12, BLUE)
    draw_text(c, "PRIVATE RESERVE", right_x + box_w / 2, box_y + 100,
              "Helvetica-Bold", 13, white, "center")
    draw_text(c, f"Balance: {fmt(pr_balance)}", right_x + box_w / 2, box_y + 72,
              "Helvetica", 11, white, "center")
    draw_text(c, f"Target: {fmt(pr_target)}", right_x + box_w / 2, box_y + 52,
              "Helvetica", 11, white, "center")
    draw_text(c, "Emergency Fund", right_x + box_w / 2, box_y + 18,
              "Helvetica-Oblique", 9, white, "center")

    # ── ARROW 1: Inflow -> Outflow (solid) ─────────────────────
    center_y = box_y + box_h / 2
    arrow_size = 8

    c.setStrokeColor(DARK_TEXT)
    c.setLineWidth(1.5)
    c.setDash()
    # Horizontal line
    c.line(left_x + box_w, center_y, mid_x - arrow_size - 5, center_y)
    # Arrowhead
    c.line(mid_x - 5, center_y, mid_x - arrow_size - 5, center_y + 5)
    c.line(mid_x - 5, center_y, mid_x - arrow_size - 5, center_y - 5)

    # Arrow label
    draw_text(c, f"{fmt(outflow)}", (left_x + box_w + mid_x) / 2, center_y + 14,
              "Helvetica-Bold", 9, DARK_TEXT, "center")
    draw_text(c, "\u2192 Expenses", (left_x + box_w + mid_x) / 2, center_y - 14,
              "Helvetica-Bold", 8, RED, "center")

    # ── ARROW 2: Inflow -> Private Reserve (dashed, above) ────
    dashed_y = box_y + box_h + 30
    c.setStrokeColor(BLUE)
    c.setLineWidth(1.5)
    c.setDash(6, 4)
    c.line(left_x + box_w, dashed_y, right_x - arrow_size - 5, dashed_y)
    c.setDash()
    c.line(right_x - 5, dashed_y, right_x - arrow_size - 5, dashed_y + 5)
    c.line(right_x - 5, dashed_y, right_x - arrow_size - 5, dashed_y - 5)
    c.line(left_x + box_w, dashed_y, left_x + box_w + arrow_size + 5, dashed_y + 5)
    c.line(left_x + box_w, dashed_y, left_x + box_w + arrow_size + 5, dashed_y - 5)

    # Arrow labels
    savings_rate = (excess / inflow * 100) if inflow > 0 else 0
    annual_excess = excess * 12
    draw_text(c, f"Excess: {fmt(excess)}/mo", PW / 2, dashed_y + 18,
              "Helvetica-Bold", 12, BLUE, "center")
    draw_text(c, "(Flows to Private Reserve)", PW / 2, dashed_y - 18,
              "Helvetica", 8, GRAY, "center")

    # ================================================================
    # ELEMENT 4: METRICS SUMMARY GRID
    # ================================================================
    strip_y = 130
    strip_h = 80
    on_track = pr_balance >= pr_target

    # Background strip
    c.setFillColor(LIGHT_BG)
    c.rect(30, strip_y, PW - 60, strip_h, fill=True, stroke=False)

    # Top border line
    c.setStrokeColor(DIVIDER)
    c.setLineWidth(0.5)
    c.line(30, strip_y + strip_h, PW - 30, strip_y + strip_h)

    # Four metric columns
    metrics = [
        ("Monthly Savings Rate", f"{savings_rate:.1f}%", GREEN if savings_rate >= 0 else RED),
        ("Annual Excess", fmt(annual_excess), GREEN if annual_excess >= 0 else RED),
        ("Reserve Target", fmt(pr_target), DARK_TEXT),
        ("Reserve Status", "On Track" if on_track else "Below Target", GREEN if on_track else RED),
    ]

    n_metrics = len(metrics)
    col_w = (PW - 100) / n_metrics

    for i, (label, value, color) in enumerate(metrics):
        col_mid = 50 + col_w * i + col_w / 2
        draw_text(c, label, col_mid, strip_y + 58, "Helvetica-Bold", 8, DARK_TEXT, "center")
        draw_text(c, value, col_mid, strip_y + 32, "Helvetica-Bold", 16, color, "center")

    # ================================================================
    # ELEMENT 5: FOOTER (y=10 to y=68)
    # ================================================================
    c.setStrokeColor(GRAY_BOX)
    c.setLineWidth(0.5)
    c.line(30, 65, PW - 30, 65)

    today_str = date.today().strftime("%B %d, %Y")

    draw_text(c, "CONFIDENTIAL \u2014 For Client Use Only", 30, 48, "Helvetica", 8, GRAY)
    draw_text(c, "Windbrook Solutions | AW Client Report Portal", PW / 2, 48, "Helvetica", 8, GRAY, "center")
    draw_text(c, f"Generated: {today_str}", PW - 30, 48, "Helvetica", 8, GRAY, "right")

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

# ── TCC Helper Functions ──────────────────────────────────────────────

def fmt(amount):
    """Format number as $1,234,567.00"""
    return f"${amount:,.2f}"


def fmt_short(amount):
    """Format as $1,234,567 (no decimals for large numbers)"""
    return f"${amount:,.0f}"


def draw_text(c, text, x, y, font="Helvetica", size=10, color=DARK_TEXT, align="left"):
    """Draw text with alignment: 'left', 'center', 'right'"""
    c.setFont(font, size)
    c.setFillColor(color)
    if align == "center":
        c.drawCentredString(x, y, text)
    elif align == "right":
        c.drawRightString(x, y, text)
    else:
        c.drawString(x, y, text)


def draw_section_label(c, text, x, y, width, color=GRAY_BG, text_color=NAVY):
    """Draw a full-width section header bar."""
    c.setFillColor(color)
    c.rect(x, y, width, 16, stroke=0, fill=1)
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(text_color)
    c.drawString(x + 6, y + 4, text)


def draw_rounded_box(c, x, y, w, h, radius=8, fill_color=GRAY_BG, stroke_color=None):
    """Draw a filled (optionally stroked) rounded rectangle."""
    c.setFillColor(fill_color)
    if stroke_color:
        c.setStrokeColor(stroke_color)
        c.roundRect(x, y, w, h, radius, stroke=1, fill=1)
    else:
        c.roundRect(x, y, w, h, radius, stroke=0, fill=1)


def draw_account_row(c, account, row_x, row_y, row_w, row_h, idx):
    """Draw a single account row with type on left, balance on right."""
    bg = GRAY_BG if idx % 2 == 0 else white
    draw_rounded_box(c, row_x, row_y, row_w, row_h, radius=6, fill_color=bg)
    # Left: account type
    draw_text(c, account.get('type', 'Account'), row_x + 10, row_y + row_h / 2 - 4,
              "Helvetica-Bold", 11, DARK_TEXT)
    # Right: balance
    balance = account.get('balance', 0)
    draw_text(c, fmt(balance), row_x + row_w - 10, row_y + row_h / 2 - 4,
              "Helvetica-Bold", 12, BLUE, align="right")


def draw_total_box(c, label, amount, x, y, w, bg_color=NAVY, text_color=white):
    """Draw a colored total box with label on left, amount on right."""
    draw_rounded_box(c, x, y, w, 28, radius=0, fill_color=bg_color)
    draw_text(c, label, x + 10, y + 8, "Helvetica-Bold", 10, text_color)
    draw_text(c, fmt(amount), x + w - 10, y + 8, "Helvetica-Bold", 12, text_color, align="right")


# ── Main Generation Function ──────────────────────────────────────────

def generate_tcc_pdf(data, output):
    """
    Generate a professional TCC (Total Client Chart) net worth PDF
    using ReportLab canvas API for full layout control.

    Parameters
    ----------
    data : dict
        Data dict with keys: client_name, client1_name, client2_name,
        report_date, client1_retirement_accounts, client2_retirement_accounts,
        non_retirement_accounts, trust_value, trust_address, liabilities,
        client1_retirement_total, client2_retirement_total,
        non_retirement_total, liabilities_total, grand_total_net_worth.
    output : str | io.BytesIO
        File path or BytesIO buffer.
    """
    WHITE = white
    W, H = A4  # 595.28 x 841.89

    c = canvas.Canvas(output, pagesize=A4)

    # Unpack data
    client_name = data.get("client_name", "")
    client1_name = data.get("client1_name", "Client 1")
    client2_name = data.get("client2_name", "")
    report_date = data.get("report_date", "")
    c1_accounts = data.get("client1_retirement_accounts", [])
    c2_accounts = data.get("client2_retirement_accounts", [])
    nr_accounts = data.get("non_retirement_accounts", [])
    liabilities = data.get("liabilities", [])
    trust_value = data.get("trust_value", 0)
    trust_address = data.get("trust_address", "")
    c1_total = data.get("client1_retirement_total", 0)
    c2_total = data.get("client2_retirement_total", 0)
    nr_total = data.get("non_retirement_total", 0)
    liab_total = data.get("liabilities_total", 0)
    grand_total = data.get("grand_total_net_worth", 0)

    if not client2_name:
        client2_name = "Individual Client"

    PW = 595.27  # page width points

    # ================================================================
    # ELEMENT 1: OUTER PAGE BORDER
    # ================================================================
    c.setStrokeColor(NAVY)
    c.setLineWidth(2)
    c.rect(10, 10, 575.27, 821.89, stroke=1, fill=0)

    # ================================================================
    # ELEMENT 2: HEADER BAR (y=795 to y=841.89)
    # ================================================================
    c.setFillColor(NAVY)
    c.rect(10, 795, 575.27, 46.89, stroke=0, fill=1)
    draw_text(c, "WINDBROOK SOLUTIONS", 30, 812, "Helvetica-Bold", 13, WHITE)
    draw_text(c, "Total Client Chart \u2014 TCC", W / 2, 812, "Helvetica", 10, WHITE, "center")
    draw_text(c, f"{client_name}  |  {report_date}", 565.27, 812, "Helvetica", 10, WHITE, "right")

    # ================================================================
    # ELEMENT 3: CLIENT NAME BOXES (y=747 to y=787)
    # ================================================================
    draw_rounded_box(c, 30, 747, 255, 38, 8, NAVY)
    draw_text(c, client1_name, 30 + 255 / 2, 747 + 12, "Helvetica-Bold", 13, WHITE, "center")

    draw_rounded_box(c, 310, 747, 255, 38, 8, NAVY)
    draw_text(c, client2_name, 310 + 255 / 2, 747 + 12, "Helvetica-Bold", 13, WHITE, "center")

    # ================================================================
    # ELEMENT 4: RETIREMENT SECTION LABEL (y=730 to y=745)
    # ================================================================
    draw_section_label(c, "RETIREMENT ACCOUNTS", 30, 730, 535)

    # ================================================================
    # ELEMENT 5: TWO-COLUMN RETIREMENT ACCOUNTS (y=530+ to y=728)
    # ================================================================
    col_header_h = 22
    row_h = 44
    row_gap = 6
    total_h = 28
    col_padding = 10

    # Calculate needed column height
    n1 = max(len(c1_accounts), 1)
    n2 = max(len(c2_accounts), 1)
    content_h = col_header_h + row_gap + max(n1, n2) * (row_h + row_gap) + col_padding + total_h
    content_h = max(content_h, 195)
    col_bottom = max(728 - content_h, 530)

    # Column divider line
    c.setStrokeColor(GRAY_BOX)
    c.setLineWidth(0.5)
    c.line(295, col_bottom, 295, 728)

    # --- LEFT COLUMN: Client 1 Retirement (x=30, width=255) ---
    col_x1, col_w1 = 30, 255

    draw_rounded_box(c, col_x1, 728 - col_header_h, col_w1, col_header_h, 0, GRAY_BOX)
    # Client 1 column header — use first name only to avoid overflow
    c1_display = client1_name.split()[0] if client1_name else "Client 1"
    draw_text(c, f"{c1_display} \u2014 Retirement Accounts", col_x1 + 8, 728 - col_header_h + 4,
              "Helvetica-Bold", 9, NAVY)

    y = 728 - col_header_h - row_gap
    if not c1_accounts:
        draw_text(c, "No Accounts Recorded", col_x1 + 10, y + 14,
                  "Helvetica-Oblique", 10, GRAY)
        y -= (row_h + row_gap)
    else:
        for idx, acct in enumerate(c1_accounts):
            draw_account_row(c, acct, col_x1, y - row_h, col_w1, row_h, idx)
            y -= (row_h + row_gap)

    y -= col_padding
    draw_total_box(c, "TOTAL", c1_total, col_x1, y - total_h, col_w1)
    c1_bottom = y - total_h

    # --- RIGHT COLUMN: Client 2 Retirement (x=307, width=255) ---
    col_x2, col_w2 = 307, 255

    draw_rounded_box(c, col_x2, 728 - col_header_h, col_w2, col_header_h, 0, GRAY_BOX)
    # Client 2 column header
    c2_display = client2_name.split()[0] if client2_name else "Client 2"
    draw_text(c, f"{c2_display} \u2014 Retirement Accounts", col_x2 + 8, 728 - col_header_h + 4,
              "Helvetica-Bold", 9, NAVY)

    y = 728 - col_header_h - row_gap
    if not c2_accounts:
        draw_text(c, "No Accounts Recorded", col_x2 + 10, y + 14,
                  "Helvetica-Oblique", 10, GRAY)
        y -= (row_h + row_gap)
    else:
        for idx, acct in enumerate(c2_accounts):
            draw_account_row(c, acct, col_x2, y - row_h, col_w2, row_h, idx)
            y -= (row_h + row_gap)

    y -= col_padding
    draw_total_box(c, "TOTAL", c2_total, col_x2, y - total_h, col_w2)
    c2_bottom = y - total_h

    # ================================================================
    # ELEMENT 6: NON-RETIREMENT SECTION (y=390 to y=528)
    # ================================================================
    nr_section_top = 528
    nr_section_bottom = 390

    draw_section_label(c, "NON-RETIREMENT / JOINT ACCOUNTS", 30, nr_section_top - 15, 535)

    nr_row_h = 40
    nr_gap = 6
    y = nr_section_top - 15 - nr_gap

    if not nr_accounts:
        draw_text(c, "No Accounts Recorded", 40, y + 14,
                  "Helvetica-Oblique", 10, GRAY)
        y -= (nr_row_h + nr_gap)
    else:
        for idx, acct in enumerate(nr_accounts):
            draw_account_row(c, acct, 30, y - nr_row_h, 535, nr_row_h, idx)
            y -= (nr_row_h + nr_gap)

    y -= nr_gap
    draw_total_box(c, "NON-RETIREMENT TOTAL", nr_total, 30, y - 28, 535)
    nr_bottom = y - 28

    # ================================================================
    # ELEMENT 7: TRUST SECTION (y=295 to y=388)
    # ================================================================
    draw_section_label(c, "TRUST / PROPERTY", 30, 388 - 15, 535)

    trust_box_y = 295
    trust_box_h = 70
    trust_box_w = 535
    draw_rounded_box(c, 30, trust_box_y, trust_box_w, trust_box_h, 8, GRAY_BG)

    # Trust content
    draw_text(c, "TRUST PROPERTY", 30 + trust_box_w / 2, trust_box_y + 50,
              "Helvetica-Bold", 11, NAVY, "center")
    if trust_address:
        draw_text(c, trust_address, 30 + trust_box_w / 2, trust_box_y + 35,
                  "Helvetica", 10, DARK_TEXT, "center")
    draw_text(c, f"Zillow Zestimate: {fmt(trust_value)}", 30 + trust_box_w / 2, trust_box_y + 18,
              "Helvetica-Bold", 14, BLUE, "center")
    draw_text(c, "Value updated quarterly", 30 + trust_box_w / 2, trust_box_y + 5,
              "Helvetica-Oblique", 8, GRAY, "center")

    # ================================================================
    # ELEMENT 8: LIABILITIES SECTION (y=165 to y=293)
    # ================================================================
    draw_section_label(c, "LIABILITIES", 30, 293 - 15, 535, RED, WHITE)

    liab_row_h = 32
    y = 293 - 15 - 2  # 2pt gap

    if not liabilities:
        draw_rounded_box(c, 30, y - liab_row_h, 535, liab_row_h, 6, GRAY_BG)
        draw_text(c, "No Liabilities Recorded", 40, y - liab_row_h + 10,
                  "Helvetica-Oblique", 10, GRAY)
        y -= (liab_row_h + 2)
    else:
        for idx, liab in enumerate(liabilities):
            liab_name = liab.get('name', '')
            liab_balance = liab.get('balance', 0)
            liab_rate = liab.get('rate', 0)
            bg = GRAY_BG if idx % 2 == 0 else WHITE
            draw_rounded_box(c, 30, y - liab_row_h, 535, liab_row_h, 0, bg)
            draw_text(c, liab_name, 40, y - liab_row_h + 10,
                      "Helvetica-Bold", 11, DARK_TEXT)
            draw_text(c, f"Rate: {liab_rate}%", 300, y - liab_row_h + 10,
                      "Helvetica", 9, GRAY)
            draw_text(c, fmt(liab_balance), 555, y - liab_row_h + 10,
                      "Helvetica-Bold", 12, RED, align="right")
            y -= (liab_row_h + 2)

    y -= 2
    draw_total_box(c, "TOTAL LIABILITIES", liab_total, 30, y - 28, 535, RED, WHITE)

    liab_bottom = y - 28
    draw_text(c, "Liabilities shown separately \u2014 not subtracted from net worth per client preference",
              W / 2, liab_bottom - 12, "Helvetica-Oblique", 8, GRAY, "center")

    # ================================================================
    # ELEMENT 9: GRAND TOTAL SUMMARY BAR (y=70 to y=140)
    # ================================================================
    # Top section (y=105 to y=140): NAVY fill with four columns
    c.setFillColor(NAVY)
    c.rect(10, 105, 575.27, 35, stroke=0, fill=1)

    # Use actual individual names in summary bar (truncate if too long)
    c1_label = client1_name.split()[0] + " Ret."   # e.g. "John Ret."
    c2_label = client2_name.split()[0] + " Ret."   # e.g. "Jane Ret."
    col_labels = [c1_label, c2_label, "Non-Retirement", "Trust"]
    col_values = [fmt_short(c1_total), fmt_short(c2_total), fmt_short(nr_total), fmt_short(trust_value)]
    col_w_summary = 575.27 / 4

    for i in range(4):
        col_center_x = 10 + col_w_summary * i + col_w_summary / 2
        draw_text(c, col_labels[i], col_center_x, 128, "Helvetica", 8, WHITE, "center")
        draw_text(c, col_values[i], col_center_x, 113, "Helvetica-Bold", 10, WHITE, "center")

    # Bottom section (y=70 to y=105): darker navy, big hero number
    c.setFillColor(HexColor("#0d1b38"))
    c.rect(10, 70, 575.27, 35, stroke=0, fill=1)

    draw_text(c, "GRAND TOTAL NET WORTH", W / 2, 95, "Helvetica", 10, WHITE, "center")
    draw_text(c, fmt(grand_total), W / 2, 73, "Helvetica-Bold", 18, WHITE, "center")

    # ================================================================
    # ELEMENT 10: FOOTER (y=10 to y=68)
    # ================================================================
    c.setStrokeColor(GRAY_BOX)
    c.setLineWidth(0.5)
    c.line(30, 65, 565, 65)

    today_str = date.today().strftime("%B %d, %Y")

    draw_text(c, "CONFIDENTIAL \u2014 For Client Use Only", 30, 48, "Helvetica", 8, GRAY)
    draw_text(c, "Windbrook Solutions | AW Client Report Portal", W / 2, 48, "Helvetica", 8, GRAY, "center")
    draw_text(c, f"Generated: {today_str}", 565, 48, "Helvetica", 8, GRAY, "right")

    c.showPage()
    c.save()


# ======================================================================
# TCC Self-Test Block (only runs when executed directly)
# ======================================================================

if __name__ == "__main__":
    # Test data matching the exact input format
    test_data = {
        "client_name": "John & Jane Doe",
        "client1_name": "John Doe",
        "client2_name": "Jane Doe",
        "report_date": "Q2 2026",
        "client1_retirement_accounts": [
            {"type": "IRA", "balance": 125000},
            {"type": "401K", "balance": 280000},
        ],
        "client2_retirement_accounts": [
            {"type": "Roth IRA", "balance": 95000},
        ],
        "non_retirement_accounts": [
            {"type": "Schwab Brokerage", "balance": 340000},
        ],
        "trust_value": 850000,
        "trust_address": "123 Main St, Atlanta GA",
        "liabilities": [
            {"name": "Mortgage", "balance": 420000, "rate": 3.25},
            {"name": "Auto Loan", "balance": 18000, "rate": 4.9},
        ],
        "client1_retirement_total": 405000,
        "client2_retirement_total": 95000,
        "non_retirement_total": 340000,
        "grand_total_net_worth": 1690000,
        "liabilities_total": 438000,
    }

    generate_tcc_pdf(test_data, "test_tcc_v2.pdf")
    print("Generated test_tcc_v2.pdf \u2014 open to verify layout")


# ======================================================================
# Data Mapping Helpers
# ======================================================================

def _split_couple_name(full_name: str):
    """
    Split a couple name into two individual names.

    Examples:
      "John & Jane Doe"   → ("John Doe",  "Jane Doe")
      "John & Jane"       → ("John",      "Jane")
      "John Doe"          → ("John Doe",  "")
      "John"              → ("John",      "")
    """
    if " & " in full_name:
        parts = full_name.split(" & ", 1)
        left  = parts[0].strip()   # e.g. "John"
        right = parts[1].strip()   # e.g. "Jane Doe"

        right_words = right.split()
        if len(right_words) > 1:
            # right already has a last name → take it for left too if left has none
            last_name = right_words[-1]
            left_words = left.split()
            if len(left_words) == 1:
                left = f"{left} {last_name}"   # "John" → "John Doe"
            return left, right
        else:
            # right is just a first name, no shared last name
            return left, right
    else:
        # no " & " → treat as single name
        return full_name.strip(), ""


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
    nr_accts  = raw_data.get("non_retirement_accounts")    or []
    liabilities = raw_data.get("liabilities")              or []

    def _to_accts(numbers, prefix="Account"):
        return [
            {"type": f"{prefix} {i + 1}", "balance": float(val)}
            for i, val in enumerate(numbers)
        ]

    # ── Resolve individual client names ──────────────────────────────
    full_couple_name = calculated.get("client_name", "")

    # If the form sends explicit individual names → use them.
    # Otherwise → auto-split the couple name (e.g. "John & Jane Doe").
    raw_c1 = (raw_data.get("client1_name") or "").strip()
    raw_c2 = (raw_data.get("client2_name") or "").strip()

    if raw_c1 and raw_c2:
        client1_name = raw_c1
        client2_name = raw_c2
    elif raw_c1:
        _, client2_name = _split_couple_name(full_couple_name)
        client1_name = raw_c1
    else:
        client1_name, client2_name = _split_couple_name(full_couple_name)
        # Final fallbacks if split produces empty strings
        if not client1_name:
            client1_name = "Client 1"
        if not client2_name:
            client2_name = "Client 2"

    # ── Pull totals from calculated dict ─────────────────────────────
    c1_total    = calculated.get("tcc_client1_retirement_total", 0)
    c2_total    = calculated.get("tcc_client2_retirement_total", 0)
    nr_total    = calculated.get("tcc_non_retirement_total",     0)
    liab_total  = calculated.get("tcc_liabilities_total",        0)
    trust_val   = calculated.get("trust_value",                  0)
    grand_total = calculated.get("tcc_grand_total_net_worth",    0)

    return {
        "client_name":  full_couple_name,
        "client1_name": client1_name,
        "client2_name": client2_name,
        "report_date":  calculated.get("report_date", ""),

        "client1_retirement_accounts": _to_accts(c1_accts),
        "client2_retirement_accounts": _to_accts(c2_accts),
        "non_retirement_accounts":     _to_accts(nr_accts),

        "trust_value":   trust_val,
        "trust_address": raw_data.get("trust_address", ""),
        "liabilities":   liabilities,

        "client1_retirement_total": c1_total,
        "client2_retirement_total": c2_total,
        "non_retirement_total":     nr_total,
        "liabilities_total":        liab_total,
        "grand_total_net_worth":    grand_total,
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
