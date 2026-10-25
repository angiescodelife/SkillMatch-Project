"""CV text extraction and skill identification.

1. Text is extracted from PDF (pdfplumber) or DOCX (python-docx, including
   tables) files.
2. Skills are identified by matching the text against SkillMatch's
   controlled skill dictionary (Skill rows with in_dictionary=True) and
   their aliases. Matching is case-insensitive and tolerant of spacing and
   punctuation ("Node.js", "node js", "NodeJS"), with word boundaries so
   "Java" is not found inside "JavaScript". Very short terms ("R", "C",
   "Go") are matched case-sensitively to limit false positives.
   If spaCy is installed, its PhraseMatcher is used as well (token-level
   matching on lower-cased text) and the results are merged.
3. Every result is stored as an ExtractedSkill awaiting the user's review;
   nothing is added to the profile automatically.
"""
from __future__ import annotations

import io
import logging
import re
import zipfile
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from ..models import CV, ExtractedSkill, Skill, SkillAlias

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {'.pdf', '.docx'}
MIN_TEXT_LENGTH = 40


class ExtractionError(Exception):
    """Raised with a message that is safe to show to the user."""


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def extract_text_from_pdf(data: bytes) -> str:
    import pdfplumber

    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if len(pdf.pages) > 30:
                raise ExtractionError('This PDF has more than 30 pages. Please upload a shorter CV.')
            pages = [page.extract_text() or '' for page in pdf.pages]
    except ExtractionError:
        raise
    except Exception as exc:  # pdfminer raises many different errors
        logger.info('PDF extraction failed: %s', exc)
        raise ExtractionError(
            "We couldn't open this PDF. It may be damaged or password-protected."
        ) from exc
    return '\n'.join(pages)


def extract_text_from_docx(data: bytes) -> str:
    import docx

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:
        logger.info('DOCX extraction failed: %s', exc)
        raise ExtractionError("We couldn't open this Word document. Try saving it again as .docx.") from exc
    parts = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts.append(' | '.join(cell.text for cell in row.cells))
    return '\n'.join(parts)


def extract_text(data: bytes, extension: str) -> str:
    extension = extension.lower()
    if extension == '.pdf':
        text = extract_text_from_pdf(data)
    elif extension == '.docx':
        text = extract_text_from_docx(data)
    else:
        raise ExtractionError('Only PDF and DOCX files are supported.')
    text = re.sub(r'[ \t]+', ' ', text).strip()
    if len(text) < MIN_TEXT_LENGTH:
        raise ExtractionError(
            "We couldn't find readable text in this file. Scanned images aren't supported "
            'yet. Try a PDF exported from Word or Google Docs, or upload a DOCX.'
        )
    return text


def looks_like_valid_file(data: bytes, extension: str) -> bool:
    """Check file signatures so a renamed file can't pass as a CV."""
    extension = extension.lower()
    if extension == '.pdf':
        return data[:5] == b'%PDF-'
    if extension == '.docx':
        if data[:4] != b'PK\x03\x04':
            return False
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                return 'word/document.xml' in zf.namelist()
        except zipfile.BadZipFile:
            return False
    return False


# ---------------------------------------------------------------------------
# Skill identification
# ---------------------------------------------------------------------------

@dataclass
class Found:
    skill: Skill
    matched_text: str
    occurrences: int = 0
    context: str = ''
    terms: set = field(default_factory=set)


def _term_pattern(term: str):
    tokens = [t for t in re.split(r'[\s.\-_/]+', term.strip()) if t]
    if not tokens:
        return None
    body = r'[\s.\-_/]*'.join(re.escape(t) for t in tokens)
    pattern = rf'(?<![A-Za-z0-9+#]){body}(?![A-Za-z0-9+#])'
    flags = 0 if len(term.strip()) <= 2 else re.IGNORECASE
    return re.compile(pattern, flags)


def dictionary_terms():
    """Yield (term, skill) for every dictionary skill name and alias."""
    skills = {s.pk: s for s in Skill.objects.filter(in_dictionary=True)}
    for s in skills.values():
        yield s.name, s
    for alias in SkillAlias.objects.filter(skill_id__in=skills.keys()):
        yield alias.alias, skills[alias.skill_id]


def _context(text, start, end, width=70):
    a, b = max(0, start - width), min(len(text), end + width)
    snippet = text[a:b].replace('\n', ' ')
    return ('…' if a else '') + snippet.strip() + ('…' if b < len(text) else '')


def find_skills(text: str):
    """Return a list of Found results, most frequent first."""
    found: dict[int, Found] = {}
    for term, skill in dictionary_terms():
        pattern = _term_pattern(term)
        if pattern is None:
            continue
        matches = list(pattern.finditer(text))
        if not matches:
            continue
        item = found.setdefault(skill.pk, Found(skill, matches[0].group(0)))
        if not item.context:
            item.context = _context(text, matches[0].start(), matches[0].end())
        item.occurrences += len(matches)
        item.terms.add(term)

    for skill, matched, count in _spacy_matches(text):
        item = found.setdefault(skill.pk, Found(skill, matched))
        item.occurrences = max(item.occurrences, count)

    return sorted(found.values(), key=lambda f: (-f.occurrences, f.skill.name.lower()))


def _spacy_matches(text):
    """Optional spaCy PhraseMatcher pass. Returns [] if spaCy isn't installed."""
    try:
        import spacy
        from spacy.matcher import PhraseMatcher
    except ImportError:
        return []
    nlp = spacy.blank('en')
    matcher = PhraseMatcher(nlp.vocab, attr='LOWER')
    lookup = {}
    for term, skill in dictionary_terms():
        if len(term.strip()) <= 2:
            continue  # short terms are handled case-sensitively by the regex pass
        key = f'S{skill.pk}'
        lookup[key] = skill
        matcher.add(key, [nlp.make_doc(term)])
    doc = nlp(text[:200000])
    counts = {}
    for match_id, start, end in matcher(doc):
        key = nlp.vocab.strings[match_id]
        span = doc[start:end].text
        skill = lookup[key]
        if skill.pk in counts:
            counts[skill.pk][2] += 1
        else:
            counts[skill.pk] = [skill, span, 1]
    return [tuple(v) for v in counts.values()]


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def process_cv(cv: CV) -> CV:
    """Extract text and candidate skills from a stored CV. Never raises."""
    try:
        with cv.file.open('rb') as fh:
            data = fh.read()
        ext = '.' + cv.original_name.rsplit('.', 1)[-1].lower() if '.' in cv.original_name else ''
        text = extract_text(data, ext)
        results = find_skills(text)
    except ExtractionError as exc:
        cv.status = CV.STATUS_FAILED
        cv.error_message = str(exc)[:300]
        cv.save(update_fields=['status', 'error_message'])
        return cv
    except Exception:  # pragma: no cover - unexpected failure
        logger.exception('Unexpected CV processing failure for CV %s', cv.pk)
        cv.status = CV.STATUS_FAILED
        cv.error_message = 'Something went wrong while reading your CV. Please try again.'
        cv.save(update_fields=['status', 'error_message'])
        return cv

    owned = set(cv.profile.user_skills.values_list('skill_id', flat=True))
    with transaction.atomic():
        cv.extracted_skills.all().delete()
        ExtractedSkill.objects.bulk_create([
            ExtractedSkill(
                cv=cv, skill=f.skill, matched_text=f.matched_text[:120],
                occurrences=min(f.occurrences, 999), context=f.context[:240],
                already_in_profile=f.skill.pk in owned,
                status=ExtractedSkill.ACCEPTED if f.skill.pk in owned else ExtractedSkill.PENDING,
            )
            for f in results
        ])
        cv.extracted_text = text
        cv.status = CV.STATUS_PARSED
        cv.error_message = ''
        cv.reviewed_at = timezone.now() if not cv.extracted_skills.filter(
            status=ExtractedSkill.PENDING).exists() else None
        cv.save(update_fields=['extracted_text', 'status', 'error_message', 'reviewed_at'])
    return cv


def suggested_score(occurrences: int) -> int:
    """Starting proficiency suggestion for review. Users can change it."""
    if occurrences >= 4:
        return 70
    if occurrences >= 2:
        return 55
    return 40
