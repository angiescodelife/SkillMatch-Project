import io
import shutil
import tempfile

from django.contrib.auth.models import User
from django.test import override_settings

from core.models import (
    CareerPreference, Employer, Opportunity, OpportunitySkill, Skill, SkillAlias, UserProfile,
    UserSkill,
)


def make_pdf(lines):
    """Build a small, valid single-page PDF containing the given text lines.

    Written by hand so the tests need no PDF-writing library.
    """
    def esc(t):
        return t.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')

    content = ['BT', '/F1 11 Tf', '14 TL', '50 780 Td']
    for line in lines:
        content.append(f'({esc(line)}) Tj T*')
    content.append('ET')
    stream = '\n'.join(content).encode('latin-1')
    objects = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] '
        b'/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>',
        b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    ]
    out = io.BytesIO()
    out.write(b'%PDF-1.4\n')
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f'{i} 0 obj\n'.encode() + body + b'\nendobj\n')
    xref = out.tell()
    out.write(f'xref\n0 {len(objects) + 1}\n0000000000 65535 f \n'.encode())
    for off in offsets:
        out.write(f'{off:010d} 00000 n \n'.encode())
    out.write(f'trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
    return out.getvalue()


def make_docx(paragraphs, table_rows=None):
    import docx

    document = docx.Document()
    for p in paragraphs:
        document.add_paragraph(p)
    if table_rows:
        table = document.add_table(rows=0, cols=len(table_rows[0]))
        for row in table_rows:
            cells = table.add_row().cells
            for cell, value in zip(cells, row):
                cell.text = value
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def make_user(email='student@example.com', password='Str0ng!Passw0rd', user_type='student',
              first='Test', last='Student'):
    user = User.objects.create_user(username=email, email=email, password=password,
                                    first_name=first, last_name=last)
    profile = UserProfile.objects.create(user=user, user_type=user_type)
    CareerPreference.objects.create(profile=profile)
    return user, profile


def skill(name, skill_type='technical', aliases=(), dictionary=True, category=''):
    s = Skill.objects.create(name=name, skill_type=skill_type, in_dictionary=dictionary,
                             category=category)
    for a in aliases:
        SkillAlias.objects.create(skill=s, alias=a)
    return s


def give(profile, skill_obj, score, source='self'):
    return UserSkill.objects.create(profile=profile, skill=skill_obj, proficiency_score=score,
                                    source=source)


def opportunity(title='Test Intern', employer=None, requirements=(), **kwargs):
    employer = employer or Employer.objects.create(name=f'{title} Co', is_sample=True)
    defaults = dict(opportunity_type='internship', work_style='hybrid', location='Nairobi',
                    description=f'{title} description', is_sample=True)
    defaults.update(kwargs)
    opp = Opportunity.objects.create(employer=employer, title=title, **defaults)
    for skill_obj, importance, target in requirements:
        OpportunitySkill.objects.create(opportunity=opp, skill=skill_obj, importance=importance,
                                        target_score=target)
    return opp


class TempMediaMixin:
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media = tempfile.mkdtemp()
        cls._private = tempfile.mkdtemp()
        cls._override = override_settings(MEDIA_ROOT=cls._media, PRIVATE_MEDIA_ROOT=cls._private)
        cls._override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        shutil.rmtree(cls._media, ignore_errors=True)
        shutil.rmtree(cls._private, ignore_errors=True)
        super().tearDownClass()
