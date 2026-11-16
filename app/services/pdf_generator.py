"""
Service for generating PDF exports
"""
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from typing import List, Dict
import os


class PDFGenerator:
    """Generate PDF exports for quizzes"""
    
    def __init__(self):
        self.styles = getSampleStyleSheet()
        
        # Custom styles
        self.title_style = ParagraphStyle(
            'CustomTitle',
            parent=self.styles['Title'],
            fontSize=24,
            spaceAfter=30,
            alignment=1  # Center
        )
        
        self.question_style = ParagraphStyle(
            'CustomQuestion',
            parent=self.styles['Normal'],
            fontSize=12,
            spaceAfter=6,
            leftIndent=20
        )
        
        self.choice_style = ParagraphStyle(
            'CustomChoice',
            parent=self.styles['Normal'],
            fontSize=10,
            spaceAfter=3,
            leftIndent=40
        )
        
        self.answer_style = ParagraphStyle(
            'CustomAnswer',
            parent=self.styles['Normal'],
            fontSize=10,
            spaceAfter=12,
            leftIndent=40,
            textColor=colors.green
        )
        
        # Try to register a font that supports Unicode (Japanese, etc.)
        self._register_fonts()
    
    def _register_fonts(self):
        """Register fonts for Unicode support"""
        # Try to find a font that supports CJK characters
        # In production, you would need to install and register appropriate fonts
        try:
            # Try common system fonts
            font_paths = [
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
                "/System/Library/Fonts/ヒラギノ角ゴシック.ttc",
                "/Windows/Fonts/msgothic.ttc"
            ]
            
            for font_path in font_paths:
                if os.path.exists(font_path):
                    pdfmetrics.registerFont(TTFont('CJKFont', font_path))
                    # Use this font for our styles
                    self.question_style.fontName = 'CJKFont'
                    self.choice_style.fontName = 'CJKFont'
                    self.answer_style.fontName = 'CJKFont'
                    break
        except:
            # Fall back to default font
            pass
    
    def generate_questions_pdf(
        self,
        quiz_title: str,
        questions: List[Dict],
        output_path: str
    ):
        """Generate questions-only PDF"""
        doc = SimpleDocTemplate(
            output_path,
            pagesize=letter,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=18
        )
        
        story = []
        
        # Title
        story.append(Paragraph(f"Quiz: {quiz_title}", self.title_style))
        story.append(Spacer(1, 0.25*inch))
        
        # Instructions
        instructions = "Please select the correct answer for each question. Write your answer in the space provided."
        story.append(Paragraph(instructions, self.styles['Normal']))
        story.append(Spacer(1, 0.5*inch))
        
        # Questions
        for question in questions:
            # Question text
            q_text = f"{question['number']}. {question['prompt']}"
            story.append(Paragraph(q_text, self.question_style))
            
            # Choices
            for choice in question['choices']:
                choice_text = f"{choice['letter']}. {choice['text']}"
                story.append(Paragraph(choice_text, self.choice_style))
            
            # Space for answer
            story.append(Spacer(1, 0.3*inch))
            answer_line = "Answer: __________"
            story.append(Paragraph(answer_line, self.choice_style))
            
            story.append(Spacer(1, 0.5*inch))
        
        # Build PDF
        doc.build(story)
    
    def generate_answers_pdf(
        self,
        quiz_title: str,
        questions: List[Dict],
        output_path: str
    ):
        """Generate answer key PDF"""
        doc = SimpleDocTemplate(
            output_path,
            pagesize=letter,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=18
        )
        
        story = []
        
        # Title
        story.append(Paragraph(f"Answer Key: {quiz_title}", self.title_style))
        story.append(Spacer(1, 0.25*inch))
        
        # Warning
        warning = "This document contains the correct answers. Do not distribute to students before the quiz."
        story.append(Paragraph(warning, ParagraphStyle(
            'Warning',
            parent=self.styles['Normal'],
            fontSize=10,
            textColor=colors.red,
            alignment=1  # Center
        )))
        story.append(Spacer(1, 0.5*inch))
        
        # Create table for answers
        table_data = [['Question', 'Correct Answer']]
        
        for question in questions:
            table_data.append([
                f"{question['number']}. {question['prompt'][:50]}...",
                question.get('correct_answer', 'N/A')
            ])
        
        # Create table
        table = Table(table_data, colWidths=[4*inch, 1.5*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        
        story.append(table)
        story.append(Spacer(1, 0.5*inch))
        
        # Detailed answers
        story.append(Paragraph("Detailed Answers:", ParagraphStyle(
            'Subtitle',
            parent=self.styles['Heading2'],
            fontSize=14,
            spaceAfter=12
        )))
        
        for question in questions:
            # Question with correct answer
            q_text = f"{question['number']}. {question['prompt']}"
            story.append(Paragraph(q_text, self.question_style))
            
            # Show correct answer
            correct_choice = None
            for choice in question['choices']:
                if choice['letter'] == question.get('correct_answer'):
                    correct_choice = choice
                    break
            
            if correct_choice:
                answer_text = f"Correct Answer: {correct_choice['letter']}. {correct_choice['text']}"
                story.append(Paragraph(answer_text, self.answer_style))
            
            story.append(Spacer(1, 0.3*inch))
        
        # Build PDF
        doc.build(story)