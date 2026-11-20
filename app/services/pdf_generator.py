"""
Service for generating PDF exports with full EN/MM Unicode shaping.

Uses WeasyPrint (Pango + HarfBuzz) with bundled Noto Sans Myanmar fonts for
accurate Myanmar OpenType shaping, falling back to ReportLab if WeasyPrint is
unavailable in the runtime environment.
"""
from html import escape as html_escape
from pathlib import Path
from typing import Dict, List, Optional
from xml.sax.saxutils import escape as xml_escape

from app.core.language import get_export_labels, normalize_language

FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
MYANMAR_REGULAR_FONT = FONTS_DIR / "NotoSansMyanmar-Regular.ttf"
MYANMAR_BOLD_FONT = FONTS_DIR / "NotoSansMyanmar-Bold.ttf"


def _build_font_face_css() -> str:
    """Build @font-face CSS rules pointing to bundled Noto Sans Myanmar TTFs."""
    rules = []
    if MYANMAR_REGULAR_FONT.exists():
        rules.append(
            f"""
            @font-face {{
                font-family: 'Noto Sans Myanmar';
                src: url('{MYANMAR_REGULAR_FONT.as_uri()}') format('truetype');
                font-weight: 400;
                font-style: normal;
            }}
            """
        )
    if MYANMAR_BOLD_FONT.exists():
        rules.append(
            f"""
            @font-face {{
                font-family: 'Noto Sans Myanmar';
                src: url('{MYANMAR_BOLD_FONT.as_uri()}') format('truetype');
                font-weight: 700;
                font-style: normal;
            }}
            """
        )
    return "\n".join(rules)


def _base_css() -> str:
    return f"""
    {_build_font_face_css()}
    @page {{
        size: letter;
        margin: 0.75in;
    }}
    body {{
        font-family: 'Noto Sans Myanmar', 'Noto Sans', Arial, sans-serif;
        color: #111827;
        font-size: 11pt;
        line-height: 1.55;
    }}
    h1 {{
        text-align: center;
        font-size: 20pt;
        margin-bottom: 12pt;
    }}
    h2 {{
        font-size: 13pt;
        margin-top: 18pt;
        margin-bottom: 8pt;
    }}
    .instructions {{
        text-align: center;
        color: #374151;
        margin-bottom: 20pt;
    }}
    .warning {{
        text-align: center;
        color: #b91c1c;
        font-weight: 700;
        margin-bottom: 18pt;
    }}
    .question-block {{
        margin-bottom: 16pt;
        page-break-inside: avoid;
    }}
    .prompt {{
        font-weight: 700;
        margin-bottom: 6pt;
    }}
    .choice {{
        margin-left: 18pt;
        margin-bottom: 3pt;
    }}
    .answer-blank {{
        margin-left: 18pt;
        margin-top: 8pt;
        color: #374151;
    }}
    .correct-answer {{
        margin-left: 18pt;
        color: #15803d;
        font-weight: 700;
    }}
    .explanation {{
        margin-left: 18pt;
        color: #4b5563;
        font-size: 10pt;
        margin-top: 3pt;
    }}
    table {{
        width: 100%;
        border-collapse: collapse;
        margin-bottom: 18pt;
    }}
    th, td {{
        border: 1px solid #d1d5db;
        padding: 6pt 8pt;
        text-align: left;
    }}
    th {{
        background-color: #374151;
        color: #ffffff;
    }}
    tr:nth-child(even) td {{
        background-color: #f9fafb;
    }}
    """


class PDFGenerator:
    """Generate PDF exports for quizzes (EN / MM)."""

    def _render_html_to_pdf(self, html_content: str, output_path: str) -> bool:
        """Render HTML to PDF via WeasyPrint. Returns False if WeasyPrint is unavailable."""
        try:
            from weasyprint import HTML

            HTML(string=html_content).write_pdf(output_path)
            return True
        except ImportError:
            return False

    def generate_questions_pdf(
        self,
        quiz_title: str,
        questions: List[Dict],
        output_path: str,
        lang: str = "en",
    ) -> None:
        """Generate questions-only PDF."""
        resolved_lang = normalize_language(lang)
        labels = get_export_labels(resolved_lang)

        blocks = []
        for question in questions:
            choices_html = "".join(
                f'<div class="choice">{html_escape(str(c["letter"]))}. {html_escape(str(c["text"]))}</div>'
                for c in question["choices"]
            )
            blocks.append(
                f"""
                <div class="question-block">
                    <div class="prompt">{question["number"]}. {html_escape(str(question["prompt"]))}</div>
                    {choices_html}
                    <div class="answer-blank">{html_escape(labels["answer_blank"])}</div>
                </div>
                """
            )

        html_doc = f"""<!DOCTYPE html>
<html lang="{resolved_lang}">
<head><meta charset="utf-8"><style>{_base_css()}</style></head>
<body>
    <h1>{html_escape(labels["quiz_prefix"])}: {html_escape(quiz_title)}</h1>
    <p class="instructions">{html_escape(labels["instructions"])}</p>
    {"".join(blocks)}
</body>
</html>"""

        if not self._render_html_to_pdf(html_doc, output_path):
            self._generate_questions_reportlab(quiz_title, questions, output_path, labels)

    def generate_answers_pdf(
        self,
        quiz_title: str,
        questions: List[Dict],
        output_path: str,
        lang: str = "en",
    ) -> None:
        """Generate answer key PDF."""
        resolved_lang = normalize_language(lang)
        labels = get_export_labels(resolved_lang)

        table_rows = []
        detail_blocks = []
        for question in questions:
            prompt = str(question["prompt"])
            truncated = f"{prompt[:50]}..." if len(prompt) > 50 else prompt
            correct_letter = str(question.get("correct_answer") or "N/A")
            table_rows.append(
                f"<tr><td>{question['number']}. {html_escape(truncated)}</td>"
                f"<td>{html_escape(correct_letter)}</td></tr>"
            )

            correct_choice = next(
                (c for c in question["choices"] if c["letter"] == question.get("correct_answer")),
                None,
            )
            answer_html = ""
            if correct_choice:
                answer_html = (
                    f'<div class="correct-answer">{html_escape(labels["correct_answer_label"])}: '
                    f'{html_escape(str(correct_choice["letter"]))}. {html_escape(str(correct_choice["text"]))}</div>'
                )
            explanation_html = ""
            if question.get("explanation"):
                explanation_html = (
                    f'<div class="explanation">{html_escape(labels["explanation_label"])}: '
                    f'{html_escape(str(question["explanation"]))}</div>'
                )
            detail_blocks.append(
                f"""
                <div class="question-block">
                    <div class="prompt">{question["number"]}. {html_escape(prompt)}</div>
                    {answer_html}
                    {explanation_html}
                </div>
                """
            )

        html_doc = f"""<!DOCTYPE html>
<html lang="{resolved_lang}">
<head><meta charset="utf-8"><style>{_base_css()}</style></head>
<body>
    <h1>{html_escape(labels["answer_key_prefix"])}: {html_escape(quiz_title)}</h1>
    <p class="warning">{html_escape(labels["warning"])}</p>
    <table>
        <thead>
            <tr>
                <th>{html_escape(labels["col_question"])}</th>
                <th>{html_escape(labels["col_correct_answer"])}</th>
            </tr>
        </thead>
        <tbody>{"".join(table_rows)}</tbody>
    </table>
    <h2>{html_escape(labels["detailed_answers"])}:</h2>
    {"".join(detail_blocks)}
</body>
</html>"""

        if not self._render_html_to_pdf(html_doc, output_path):
            self._generate_answers_reportlab(quiz_title, questions, output_path, labels)

    # --- ReportLab fallback ---

    def _register_reportlab_font(self) -> Optional[str]:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        candidates = [
            str(MYANMAR_REGULAR_FONT),
            "/usr/share/fonts/truetype/noto/NotoSansMyanmar-Regular.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        ]
        for path in candidates:
            if not Path(path).exists():
                continue
            try:
                if path.lower().endswith(".ttc"):
                    font = TTFont("QuizUnicodeFont", path, subfontIndex=0)
                else:
                    font = TTFont("QuizUnicodeFont", path)
                pdfmetrics.registerFont(font)
                return "QuizUnicodeFont"
            except Exception:
                continue
        return None

    def _generate_questions_reportlab(
        self, quiz_title: str, questions: List[Dict], output_path: str, labels: Dict[str, str]
    ) -> None:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

        font_name = self._register_reportlab_font() or "Helvetica"
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle("T", parent=styles["Title"], fontName=font_name, fontSize=20, alignment=1)
        normal_style = ParagraphStyle("N", parent=styles["Normal"], fontName=font_name, fontSize=11)
        q_style = ParagraphStyle("Q", parent=styles["Normal"], fontName=font_name, fontSize=12, leftIndent=16)
        c_style = ParagraphStyle("C", parent=styles["Normal"], fontName=font_name, fontSize=10, leftIndent=32)

        doc = SimpleDocTemplate(output_path, pagesize=letter, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
        story = [
            Paragraph(f"{xml_escape(labels['quiz_prefix'])}: {xml_escape(quiz_title)}", title_style),
            Spacer(1, 0.25 * inch),
            Paragraph(xml_escape(labels["instructions"]), normal_style),
            Spacer(1, 0.4 * inch),
        ]
        for q in questions:
            story.append(Paragraph(f"{q['number']}. {xml_escape(q['prompt'])}", q_style))
            for ch in q["choices"]:
                story.append(Paragraph(f"{xml_escape(ch['letter'])}. {xml_escape(ch['text'])}", c_style))
            story.append(Spacer(1, 0.2 * inch))
            story.append(Paragraph(xml_escape(labels["answer_blank"]), c_style))
            story.append(Spacer(1, 0.35 * inch))
        doc.build(story)

    def _generate_answers_reportlab(
        self, quiz_title: str, questions: List[Dict], output_path: str, labels: Dict[str, str]
    ) -> None:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        font_name = self._register_reportlab_font() or "Helvetica"
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle("T", parent=styles["Title"], fontName=font_name, fontSize=20, alignment=1)
        warn_style = ParagraphStyle("W", parent=styles["Normal"], fontName=font_name, fontSize=10, textColor=colors.red, alignment=1)
        q_style = ParagraphStyle("Q", parent=styles["Normal"], fontName=font_name, fontSize=12, leftIndent=16)
        ans_style = ParagraphStyle("A", parent=styles["Normal"], fontName=font_name, fontSize=10, leftIndent=32, textColor=colors.green)

        doc = SimpleDocTemplate(output_path, pagesize=letter, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
        story = [
            Paragraph(f"{xml_escape(labels['answer_key_prefix'])}: {xml_escape(quiz_title)}", title_style),
            Spacer(1, 0.2 * inch),
            Paragraph(xml_escape(labels["warning"]), warn_style),
            Spacer(1, 0.4 * inch),
        ]

        table_data = [[labels["col_question"], labels["col_correct_answer"]]]
        for q in questions:
            prompt = q["prompt"]
            truncated = f"{prompt[:50]}..." if len(prompt) > 50 else prompt
            table_data.append([f"{q['number']}. {truncated}", q.get("correct_answer") or "N/A"])

        table = Table(table_data, colWidths=[4 * inch, 1.5 * inch])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("FONTNAME", (0, 0), (-1, -1), font_name),
                    ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ]
            )
        )
        story.append(table)
        story.append(Spacer(1, 0.4 * inch))

        for q in questions:
            story.append(Paragraph(f"{q['number']}. {xml_escape(q['prompt'])}", q_style))
            correct = next((c for c in q["choices"] if c["letter"] == q.get("correct_answer")), None)
            if correct:
                story.append(
                    Paragraph(
                        f"{xml_escape(labels['correct_answer_label'])}: {xml_escape(correct['letter'])}. {xml_escape(correct['text'])}",
                        ans_style,
                    )
                )
            story.append(Spacer(1, 0.25 * inch))

        doc.build(story)
