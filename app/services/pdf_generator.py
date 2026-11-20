"""
Service for generating PDF exports
"""
import os
from typing import Dict, List, Optional
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


class PDFGenerator:
    """Generate PDF exports for quizzes"""

    def __init__(self):
        self.styles = getSampleStyleSheet()
        self.unicode_font_name: Optional[str] = None

        # Custom styles
        self.title_style = ParagraphStyle(
            "CustomTitle",
            parent=self.styles["Title"],
            fontSize=24,
            spaceAfter=30,
            alignment=1,  # Center
        )

        self.question_style = ParagraphStyle(
            "CustomQuestion",
            parent=self.styles["Normal"],
            fontSize=12,
            spaceAfter=6,
            leftIndent=20,
        )

        self.choice_style = ParagraphStyle(
            "CustomChoice",
            parent=self.styles["Normal"],
            fontSize=10,
            spaceAfter=3,
            leftIndent=40,
        )

        self.answer_style = ParagraphStyle(
            "CustomAnswer",
            parent=self.styles["Normal"],
            fontSize=10,
            spaceAfter=12,
            leftIndent=40,
            textColor=colors.green,
        )

        self._register_fonts()

    def _register_fonts(self):
        """Register fonts for Unicode support"""
        font_paths = [
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/System/Library/Fonts/ヒラギノ角ゴシック.ttc",
            "/Windows/Fonts/msgothic.ttc",
        ]

        for font_path in font_paths:
            if not os.path.exists(font_path):
                continue
            try:
                if font_path.lower().endswith(".ttc"):
                    font = TTFont("CJKFont", font_path, subfontIndex=0)
                else:
                    font = TTFont("CJKFont", font_path)
                pdfmetrics.registerFont(font)
                self.unicode_font_name = "CJKFont"
                self.title_style.fontName = "CJKFont"
                self.question_style.fontName = "CJKFont"
                self.choice_style.fontName = "CJKFont"
                self.answer_style.fontName = "CJKFont"
                break
            except Exception:
                continue

    def generate_questions_pdf(
        self,
        quiz_title: str,
        questions: List[Dict],
        output_path: str,
    ):
        """Generate questions-only PDF"""
        doc = SimpleDocTemplate(
            output_path,
            pagesize=letter,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=18,
        )

        story = []

        # Title
        story.append(Paragraph(f"Quiz: {escape(quiz_title)}", self.title_style))
        story.append(Spacer(1, 0.25 * inch))

        # Instructions
        instructions = (
            "Please select the correct answer for each question. "
            "Write your answer in the space provided."
        )
        story.append(Paragraph(instructions, self.styles["Normal"]))
        story.append(Spacer(1, 0.5 * inch))

        # Questions
        for question in questions:
            q_text = f"{question['number']}. {escape(question['prompt'])}"
            story.append(Paragraph(q_text, self.question_style))

            for choice in question["choices"]:
                choice_text = f"{escape(choice['letter'])}. {escape(choice['text'])}"
                story.append(Paragraph(choice_text, self.choice_style))

            story.append(Spacer(1, 0.3 * inch))
            story.append(Paragraph("Answer: __________", self.choice_style))
            story.append(Spacer(1, 0.5 * inch))

        doc.build(story)

    def generate_answers_pdf(
        self,
        quiz_title: str,
        questions: List[Dict],
        output_path: str,
    ):
        """Generate answer key PDF"""
        doc = SimpleDocTemplate(
            output_path,
            pagesize=letter,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=18,
        )

        story = []

        # Title
        story.append(Paragraph(f"Answer Key: {escape(quiz_title)}", self.title_style))
        story.append(Spacer(1, 0.25 * inch))

        # Warning
        warning = (
            "This document contains the correct answers. "
            "Do not distribute to students before the quiz."
        )
        story.append(
            Paragraph(
                warning,
                ParagraphStyle(
                    "Warning",
                    parent=self.styles["Normal"],
                    fontSize=10,
                    textColor=colors.red,
                    alignment=1,  # Center
                ),
            )
        )
        story.append(Spacer(1, 0.5 * inch))

        # Create table for answers
        table_data = [["Question", "Correct Answer"]]
        for question in questions:
            prompt = question["prompt"]
            truncated = f"{prompt[:50]}..." if len(prompt) > 50 else prompt
            table_data.append(
                [
                    f"{question['number']}. {truncated}",
                    question.get("correct_answer") or "N/A",
                ]
            )

        body_font = self.unicode_font_name or "Helvetica"
        header_font = self.unicode_font_name or "Helvetica-Bold"

        table = Table(table_data, colWidths=[4 * inch, 1.5 * inch])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("FONTNAME", (0, 0), (-1, 0), header_font),
                    ("FONTSIZE", (0, 0), (-1, 0), 12),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                    ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
                    ("TEXTCOLOR", (0, 1), (-1, -1), colors.black),
                    ("FONTNAME", (0, 1), (-1, -1), body_font),
                    ("FONTSIZE", (0, 1), (-1, -1), 10),
                    ("GRID", (0, 0), (-1, -1), 1, colors.black),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )

        story.append(table)
        story.append(Spacer(1, 0.5 * inch))

        # Detailed answers
        story.append(
            Paragraph(
                "Detailed Answers:",
                ParagraphStyle(
                    "Subtitle",
                    parent=self.styles["Heading2"],
                    fontSize=14,
                    spaceAfter=12,
                ),
            )
        )

        for question in questions:
            q_text = f"{question['number']}. {escape(question['prompt'])}"
            story.append(Paragraph(q_text, self.question_style))

            correct_choice = None
            for choice in question["choices"]:
                if choice["letter"] == question.get("correct_answer"):
                    correct_choice = choice
                    break

            if correct_choice:
                answer_text = (
                    f"Correct Answer: {escape(correct_choice['letter'])}. "
                    f"{escape(correct_choice['text'])}"
                )
                story.append(Paragraph(answer_text, self.answer_style))

            story.append(Spacer(1, 0.3 * inch))

        doc.build(story)
