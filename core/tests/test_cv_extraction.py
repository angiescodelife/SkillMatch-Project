from django.test import TestCase

from core.models import CV, ExtractedSkill, Skill
from core.services import cv_extraction as cx

from .helpers import TempMediaMixin, make_docx, make_pdf, make_user, skill


class SkillNormalisationTests(TestCase):
    def test_names_and_aliases_resolve(self):
        react = skill('React', aliases=['ReactJS'])
        self.assertEqual(Skill.resolve('  react '), react)
        self.assertEqual(Skill.resolve('ReactJS'), react)
        self.assertEqual(Skill.resolve('react.js'), react)
        self.assertIsNone(Skill.resolve('Angular'))
        self.assertIsNone(Skill.resolve('   '))

    def test_symbols_keep_languages_distinct(self):
        c = skill('C')
        cpp = skill('C++')
        csharp = skill('C#')
        self.assertEqual({c.normalized_name, cpp.normalized_name, csharp.normalized_name},
                         {'c', 'c++', 'c#'})


class FindSkillsTests(TestCase):
    def setUp(self):
        self.java = skill('Java')
        self.js = skill('JavaScript', aliases=['JS'])
        self.node = skill('Node.js', aliases=['NodeJS'])
        self.r = skill('R')
        self.go = skill('Go', aliases=['Golang'])
        self.comm = skill('Communication', skill_type='soft')
        skill('Not In Dictionary', dictionary=False)

    def names(self, text):
        return {f.skill.name for f in cx.find_skills(text)}

    def test_word_boundaries(self):
        self.assertEqual(self.names('Built apps in JavaScript.'), {'JavaScript'})
        self.assertEqual(self.names('Java and JavaScript'), {'Java', 'JavaScript'})

    def test_spacing_and_punctuation_variants(self):
        for text in ['node js', 'Node.js', 'NODE-JS', 'NodeJS']:
            self.assertIn('Node.js', self.names(f'Experience: {text} APIs'), text)

    def test_short_terms_are_case_sensitive(self):
        self.assertIn('R', self.names('Statistics in R and Python'))
        self.assertNotIn('R', self.names('r'))
        self.assertNotIn('Go', self.names("let's go to the meeting"))
        self.assertIn('Go', self.names('Microservices in Golang'))

    def test_only_dictionary_skills_are_found(self):
        self.assertEqual(self.names('Not In Dictionary, communication skills'), {'Communication'})

    def test_counts_occurrences(self):
        found = {f.skill.name: f for f in cx.find_skills('JS, JavaScript and more JavaScript')}
        self.assertEqual(found['JavaScript'].occurrences, 3)


class FileExtractionTests(TestCase):
    def test_pdf_text_extraction(self):
        data = make_pdf(['Jane Doe - Software Engineering Student',
                         'Skills: Python, Django, SQL and teamwork across projects'])
        self.assertTrue(cx.looks_like_valid_file(data, '.pdf'))
        text = cx.extract_text(data, '.pdf')
        self.assertIn('Django', text)

    def test_docx_text_and_tables(self):
        data = make_docx(['Jane Doe, final-year student with project experience in web development.'],
                         [['Languages', 'Python, JavaScript']])
        self.assertTrue(cx.looks_like_valid_file(data, '.docx'))
        text = cx.extract_text(data, '.docx')
        self.assertIn('Python, JavaScript', text)

    def test_renamed_file_is_rejected(self):
        self.assertFalse(cx.looks_like_valid_file(b'MZ\x90\x00 not a pdf', '.pdf'))
        self.assertFalse(cx.looks_like_valid_file(b'PK\x03\x04 broken zip', '.docx'))

    def test_pdf_without_text_raises_friendly_error(self):
        with self.assertRaises(cx.ExtractionError) as ctx:
            cx.extract_text(make_pdf([]), '.pdf')
        self.assertIn('readable text', str(ctx.exception))

    def test_corrupt_pdf_raises_friendly_error(self):
        with self.assertRaises(cx.ExtractionError):
            cx.extract_text(b'%PDF-1.4 garbage', '.pdf')


class ProcessCVTests(TempMediaMixin, TestCase):
    def test_process_cv_creates_pending_skills_and_flags_existing(self):
        from django.core.files.base import ContentFile

        user, profile = make_user()
        py = skill('Python')
        dj = skill('Django')
        from core.models import UserSkill
        UserSkill.objects.create(profile=profile, skill=py, proficiency_score=70)
        cv = CV(profile=profile, original_name='cv.pdf')
        cv.file.save('cv.pdf', ContentFile(make_pdf(
            ['Student developer with Python and Django experience on several projects.'])), save=False)
        cv.save()
        cx.process_cv(cv)
        cv.refresh_from_db()
        self.assertEqual(cv.status, CV.STATUS_PARSED)
        items = {e.skill.name: e for e in cv.extracted_skills.all()}
        self.assertTrue(items['Python'].already_in_profile)
        self.assertEqual(items['Django'].status, ExtractedSkill.PENDING)
        self.assertIsNone(cv.reviewed_at)  # still needs review
        cv.file.delete(save=False)

    def test_failed_extraction_is_recorded(self):
        from django.core.files.base import ContentFile

        user, profile = make_user()
        cv = CV(profile=profile, original_name='empty.pdf')
        cv.file.save('empty.pdf', ContentFile(make_pdf([])), save=False)
        cv.save()
        cx.process_cv(cv)
        self.assertEqual(cv.status, CV.STATUS_FAILED)
        self.assertTrue(cv.error_message)
        cv.file.delete(save=False)
