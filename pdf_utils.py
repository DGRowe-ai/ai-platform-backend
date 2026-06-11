from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def build_monthly_report_pdf(data: dict) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=48,
        leftMargin=48,
        topMargin=48,
        bottomMargin=48,
        title=f"Rowe AI Monthly Financial Summary - {data.get('month_label', '')}",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Heading1"],
        fontSize=18,
        spaceAfter=12,
        textColor=colors.HexColor("#0f172a"),
    )
    section_style = ParagraphStyle(
        "SectionHeading",
        parent=styles["Heading2"],
        fontSize=13,
        spaceBefore=14,
        spaceAfter=8,
        textColor=colors.HexColor("#115e59"),
    )
    body_style = ParagraphStyle(
        "ReportBody",
        parent=styles["BodyText"],
        fontSize=10,
        leading=14,
    )

    story = []
    story.append(Paragraph("Rowe AI Monthly Financial Summary Report", title_style))
    story.append(Paragraph(f"Period: {data.get('month_label', 'No data provided.')}", body_style))
    story.append(Spacer(1, 0.2 * inch))

    overview = data.get("month_overview", {})
    story.append(Paragraph("Month Overview", section_style))
    overview_lines = [
        f"Total revenue collected this month: ${overview.get('total_revenue_collected', 'No data provided.')}",
        f"Number of payments received: {overview.get('payments_received', 'No data provided.')}",
        f"Highest-paying client: {overview.get('highest_paying_client', 'No data provided.')}",
        f"Lowest-paying client: {overview.get('lowest_paying_client', 'No data provided.')}",
        f"Average payment amount: ${overview.get('average_payment_amount', 'No data provided.')}",
        f"New clients this month: {overview.get('new_clients_this_month', 'No data provided.')}",
        f"Lost clients: {overview.get('lost_clients', 'No data provided.')}",
    ]
    for line in overview_lines:
        story.append(Paragraph(line, body_style))

    story.append(Spacer(1, 0.15 * inch))
    story.append(Paragraph("Payment Table", section_style))

    payment_rows = data.get("payment_table", [])
    table_data = [[
        "Business Name",
        "Payment Date",
        "Payment Amount",
        "Payment Type",
        "Notes",
    ]]

    if payment_rows:
        for row in payment_rows:
            table_data.append([
                row.get("business_name", "No data provided."),
                row.get("payment_date", "No data provided."),
                f"${row.get('payment_amount', 0):.2f}",
                row.get("payment_type", "No data provided."),
                row.get("notes", "") or "-",
            ])
    else:
        table_data.append(["No data provided.", "", "", "", ""])

    table = Table(
        table_data,
        colWidths=[1.5 * inch, 1.0 * inch, 1.0 * inch, 1.1 * inch, 1.8 * inch],
        repeatRows=1,
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#115e59")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d9e2ef")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(table)

    totals = data.get("monthly_totals", {})
    story.append(Spacer(1, 0.15 * inch))
    story.append(Paragraph("Monthly Totals", section_style))
    totals_lines = [
        f"Total revenue for the month: ${totals.get('total_revenue_for_month', 'No data provided.')}",
        f"Total overdue revenue: ${totals.get('total_overdue_revenue', 'No data provided.')}",
        f"Total upcoming renewals next month: {totals.get('total_upcoming_renewals_next_month', 'No data provided.')}",
        f"Year-to-date revenue: ${totals.get('year_to_date_revenue', 'No data provided.')}",
    ]
    for line in totals_lines:
        story.append(Paragraph(line, body_style))

    doc.build(story)
    return buffer.getvalue()
