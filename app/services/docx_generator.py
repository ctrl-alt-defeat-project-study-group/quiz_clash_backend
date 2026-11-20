"""
Service for generating Word (.docx) exports with EN/MM Unicode font support.
"""
from typing import Dict, List

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

from app.core.language import contains_myanmar, get_export_labels, normalize_language


class DocxGenerator:
    """Generate Word (.docx) exports for quizzes (questions and answer keys)."""

    @staticmethod
    def _pick_font_name(lang: str, quiz_title: str, questions: List[Dict]) -> str:
        if lang == "mm" or contains_myanmar(quiz_title):
            return "Noto Sans Myanmar"
        for q in questions:
            if contains_myanmar(str(q.get("prompt", ""))):
                return "Noto Sans Myanmar"
            for c in q.get("choices", []):
                if contains_myanmar(str(c.get("text", ""))):
                    return "Noto Sans Myanmar"
        return "Calibri"

    @staticmethod
    def _configure_base_font(doc: Document, font_name: str) -> None:
        normal_style = doc.styles["Normal"]
        normal_style.font.name = font_name
        normal_style.font.size = Pt(11)

    @staticmethod
    def _add_styled_paragraph(
        doc: Document,
        text: str,
        *,
        font_name: str,
        size: int = 11,
        bold: bool = False,
        color: RGBColor = None,
        align=None,
        left_indent_pt: int = 0,
    ):
        p = doc.add_paragraph()
        if align is not None:
            p.alignment = align
        if left_indent_pt:
            p.paragraph_format.left_indent = Pt(left_indent_pt)
        run = p.add_run(text)
        run.font.name = font_name
        run.font.size = Pt(size)
        run.bold = bold
        if color is not None:
            run.font.color.rgb = color
        return p

    def generate_questions_docx(
        self,
        quiz_title: str,
        questions: List[Dict],
        output_path: str,
        lang: str = "en",
    ) -> None:
        """Generate a blank questions study sheet as .docx."""
        resolved_lang = normalize_language(lang)
        labels = get_export_labels(resolved_lang)
        font_name = self._pick_font_name(resolved_lang, quiz_title, questions)

        doc = Document()
        self._configure_base_font(doc, font_name)

        self._add_styled_paragraph(
            doc,
            f"{labels['quiz_prefix']}: {quiz_title}",
            font_name=font_name,
            size=18,
            bold=True,
            align=WD_ALIGN_PARAGRAPH.CENTER,
        )
        self._add_styled_paragraph(
            doc,
            labels["instructions"],
            font_name=font_name,
            size=10,
            color=RGBColor(0x37, 0x41, 0x51),
            align=WD_ALIGN_PARAGRAPH.CENTER,
        )

        for q in questions:
            self._add_styled_paragraph(
                doc,
                f"{q['number']}. {q['prompt']}",
                font_name=font_name,
                size=11,
                bold=True,
            )
            for choice in q["choices"]:
                self._add_styled_paragraph(
                    doc,
                    f"{choice['letter']}. {choice['text']}",
                    font_name=font_name,
                    size=10,
                    left_indent_pt=18,
                )
            self._add_styled_paragraph(
                doc,
                labels["answer_blank"],
                font_name=font_name,
                size=10,
                color=RGBColor(0x37, 0x41, 0x51),
                left_indent_pt=18,
            )

        doc.save(output_path)

    def generate_answers_docx(
        self,
        quiz_title: str,
        questions: List[Dict],
        output_path: str,
        lang: str = "en",
    ) -> None:
        """Generate an answer key as .docx."""
        resolved_lang = normalize_language(lang)
        labels = get_export_labels(resolved_lang)
        font_name = self._pick_font_name(resolved_lang, quiz_title, questions)

        doc = Document()
        self._configure_base_font(doc, font_name)

        self._add_styled_paragraph(
            doc,
            f"{labels['answer_key_prefix']}: {quiz_title}",
            font_name=font_name,
            size=18,
            bold=True,
            align=WD_ALIGN_PARAGRAPH.CENTER,
        )
        self._add_styled_paragraph(
            doc,
            labels["warning"],
            font_name=font_name,
            size=10,
            bold=True,
            color=RGBColor(0xB9, 0x1C, 0x1C),
            align=WD_ALIGN_PARAGRAPH.CENTER,
        )

        # Summary table
        table = doc.add_table(rows=1, cols=2)
        table.style = "Table Grid"
        hdr_cells = table.rows[0].cells
        hdr_cells[0].text = labels["col_question"]
        hdr_cells[1].text = labels["col_correct_answer"]

        for q in questions:
            row_cells = table.add_row().cells
            prompt = str(q["prompt"])
            truncated = f"{prompt[:50]}..." if len(prompt) > 50 else prompt
            row_cells[0].text = f"{q['number']}. {truncated}"
            row_cells[1].text = str(q.get("correct_answer") or "N/A")

        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    for run in p.runs:
                        run.font.name = font_name
                        run.font.size = Pt(10)

        self._add_styled_paragraph(
            doc,
            f"{labels['detailed_answers']}:",
            font_name=font_name,
            size=13,
            bold=True,
        )

        for q in questions:
            self._add_styled_paragraph(
                doc,
                f"{q['number']}. {q['prompt']}",
                font_name=font_name,
                size=11,
                bold=True,
            )
            correct = next(
                (c for c in q["choices"] if c["letter"] == q.get("correct_answer")),
                None,
            )
            if correct:
                self._add_styled_paragraph(
                    doc,
                    f"{labels['correct_answer_label']}: {correct['letter']}. {correct['text']}",
                    font_name=font_name,
                    size=10,
                    bold=True,
                    color=RGBColor(0x15, 0x80, 0x3D),
                    left_indent_pt=18,
                )
            if q.get("explanation"):
                self._add_styled_paragraph(
                    doc,
                    f"{labels['explanation_label']}: {q['explanation']}",
                    font_name=font_name,
                    size=10,
                    color=RGBColor(0x4B, 0x55, 0x63),
                    left_indent_pt=18,
                )

        doc.save(output_path)
