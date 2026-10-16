#!/usr/bin/env python3
"""Generate the shareable Carivyo demo guide PDF from maintained project facts."""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "Carivyo-Demo-Guide.pdf"


def paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text.replace("\n", "<br/>"), style)


def build() -> None:
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "GuideTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=24,
        leading=28, textColor=colors.HexColor("#102A43"), alignment=TA_LEFT, spaceAfter=8,
    )
    subtitle = ParagraphStyle(
        "GuideSubtitle", parent=styles["Normal"], fontSize=10.5, leading=15,
        textColor=colors.HexColor("#486581"), spaceAfter=16,
    )
    heading = ParagraphStyle(
        "GuideHeading", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=14,
        leading=18, textColor=colors.HexColor("#102A43"), spaceBefore=12, spaceAfter=6,
    )
    body = ParagraphStyle(
        "GuideBody", parent=styles["BodyText"], fontSize=9.4, leading=13.5,
        textColor=colors.HexColor("#243B53"), spaceAfter=7,
    )
    small = ParagraphStyle(
        "GuideSmall", parent=body, fontSize=8.3, leading=11.5, textColor=colors.HexColor("#486581"),
    )

    document = SimpleDocTemplate(
        str(OUTPUT), pagesize=A4, leftMargin=17 * mm, rightMargin=17 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm, title="Carivyo Demo Guide",
    )
    story = [
        paragraph("Carivyo", title),
        paragraph("Local-first career intelligence workspace · Architecture, technology, and demo guide", subtitle),
        paragraph("What It Solves", heading),
        paragraph(
            "Carivyo turns a submitted resume into an evidence-backed profile, asks only the "
            "highest-impact follow-up questions, ranks fresh verified jobs, and creates a job-specific "
            "resume only after the candidate chooses the job and approves the workflow.", body,
        ),
        paragraph("Architecture", heading),
        paragraph(
            "React and TypeScript provide the local browser UI. A FastAPI modular monolith owns "
            "validation, workflow state, and security. SQLite stores profile, job, conversation, and "
            "audit data. A local artifact vault stores resumes and generated PDFs. Official connectors "
            "supply jobs; a controlled runtime gateway optionally calls Codex or Ollama.", body,
        ),
        paragraph("Technology", heading),
    ]
    rows = [
        ["Layer", "Choice", "Purpose"],
        ["Web", "React 19 + TypeScript + Vite", "Role-aware local interface"],
        ["API", "FastAPI + Pydantic", "Typed local workflows and validation"],
        ["Data", "SQLite + local artifact vault", "Private local state and files"],
        ["AI demo", "Codex CLI + GPT-5.6 Terra", "Bounded synthesis and review"],
        ["Local AI", "Ollama", "Optional fully-local inference"],
        ["Quality", "Poppler, pypdf, ReportLab/Tectonic", "Evidence and PDF checks"],
    ]
    table = Table(rows, colWidths=[28 * mm, 52 * mm, 73 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#102A43")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("LEADING", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#BCCCDC")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F0F4F8")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.extend([table, Spacer(1, 8), paragraph("AI and Trust Boundary", heading)])
    story.append(paragraph(
        "The demo selects Codex CLI with GPT-5.6 Terra. Carivyo stores profiles, jobs, resumes, "
        "and artifacts locally; only compact task context is sent through the authenticated Codex CLI. "
        "The adapter uses a reviewed model catalog, read-only workspace, disabled shell/browser/computer "
        "tools, and bounded time/token budgets. Ollama remains available for users who require fully "
        "local inference. AI-disabled mode retains deterministic import, matching, ATS, and tracking.", body,
    ))
    story.extend([PageBreak(), paragraph("How To Demo", title)])
    steps = [
        "Start clean: run ./reset-demo-data.sh, then ./run-demo.sh.",
        "Submit a resume. Explain that source files are retained locally and parsed into grounded evidence.",
        "Answer the adaptive interview. It asks only unresolved, high-impact search preferences.",
        "Inspect verified jobs and official application links. Eligibility gates run before ranking.",
        "Show Profile > AI runtime: Codex CLI / GPT-5.6 Terra is selected; Ollama is the local option.",
        "Ask chat to explain a job or summarize the profile. The provider receives bounded compact context.",
        "Open Resume Studio for one selected job. Show frozen evidence, ATS validation, and explicit approval.",
        "Finish with application tracking, export/backup controls, and local API docs.",
    ]
    for index, step in enumerate(steps, start=1):
        story.append(paragraph(f"<b>{index}.</b> {step}", body))
    story.extend([
        paragraph("Questions To Expect", heading),
        paragraph("Why is AI optional? Facts, eligibility, ranking gates, and document checks need repeatable evidence. AI provides bounded synthesis, not authority over candidate facts.", body),
        paragraph("Why SQLite? Carivyo is single-user and local-first. SQLite removes setup overhead while keeping transactional state on the candidate's machine.", body),
        paragraph("Why retain Ollama? It provides a transparent fully-local inference mode. The selected provider is never silently changed.", body),
        paragraph("How is the resume safe? Each run freezes approved evidence and the job description, then validates extracted text, PDF rendering, and ATS rules before approval.", body),
        Spacer(1, 8),
        paragraph("Generated from scripts/generate_demo_guide_pdf.py. Keep the Markdown source in docs/DEMO_GUIDE.md as the complete maintained guide.", small),
    ])
    document.build(story)


if __name__ == "__main__":
    build()
    print(OUTPUT)