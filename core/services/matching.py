"""SkillMatch matching engine.

Compares a user's skills (self-assessed and confirmed from their CV) and
career preferences with an opportunity's requirements, and produces an
explainable match score.

Formula (documented on the in-app "How matching works" page)
------------------------------------------------------------
For each skill an opportunity lists, a *credit* between 0 and 1 is given:

    credit = min(1, user_proficiency / role_target)   if the user has the skill
    credit = 0.5 * min(1, related_proficiency / target) if only a related skill
                                                       is found (transformer
                                                       back-end only)
    credit = 0                                         otherwise

Required skills weigh 2, nice-to-have (preferred) skills weigh 1. Credits
are averaged separately for technical and soft skills:

    component = Σ(weight × credit) / Σ(weight)

Role preferences (opportunity type, work style, location, start date and
eligibility) are checked against the user's career preferences; the
component is the share of *set* preferences that match.

    match score = 0.60 × technical + 0.25 × soft + 0.15 × preferences

When a component cannot be calculated (for example a role lists no soft
skills, or the user has not set preferences) it is left out and the other
weights are scaled up proportionally, so the score is never distorted by
missing data. If nothing can be calculated, the score is None ("not
enough information"), never a guess.

The baseline from the brief is also reported for comparison:

    required coverage = matched required skills / total required × 100

Text similarity (TF-IDF or Sentence Transformers) between the profile/CV
and the description does NOT change the score; it is reported and used to
break ties when ranking.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from . import similarity

WEIGHTS = {'technical': 0.60, 'soft': 0.25, 'preferences': 0.15}
IMPORTANCE_WEIGHT = {'required': 2.0, 'preferred': 1.0}
RELATED_CREDIT = 0.5

LABELS = [
    (85, 'Strong match'),
    (70, 'Good match'),
    (50, 'Partial match'),
    (0, 'Early match'),
]


def label_for(score):
    if score is None:
        return 'Not enough information'
    for threshold, label in LABELS:
        if score >= threshold:
            return label
    return LABELS[-1][1]


# ---------------------------------------------------------------------------
# Plain data structures (no ORM), so the engine can be unit-tested directly.
# ---------------------------------------------------------------------------

@dataclass
class UserSkillData:
    skill_id: int
    name: str
    score: int
    skill_type: str = 'technical'


@dataclass
class PreferenceData:
    opportunity_types: list = field(default_factory=list)
    work_styles: list = field(default_factory=list)
    locations: list = field(default_factory=list)
    available_from: Optional[date] = None


@dataclass
class ProfileData:
    skills: dict  # skill_id -> UserSkillData
    user_type: str = 'student'
    preferences: PreferenceData = field(default_factory=PreferenceData)
    text: str = ''


@dataclass
class RequirementData:
    skill_id: int
    name: str
    importance: str  # 'required' | 'preferred'
    target: int
    skill_type: str = 'technical'


@dataclass
class OpportunityData:
    id: int
    requirements: list
    opportunity_type: str = ''
    work_style: str = ''
    location: str = ''
    start_date: Optional[date] = None
    eligible_user_types: list = field(default_factory=list)
    text: str = ''
    type_label: str = ''
    work_style_label: str = ''


@dataclass
class SkillComparison:
    skill_id: int
    name: str
    skill_type: str
    importance: str
    target: int
    user_score: Optional[int]
    status: str  # meets | below | related | missing
    credit: float
    related_to: Optional[str] = None

    @property
    def is_required(self):
        return self.importance == 'required'

    @property
    def gap_points(self):
        if self.user_score is None:
            return self.target
        return max(0, self.target - self.user_score)


@dataclass
class PreferenceCheck:
    key: str
    label: str
    status: str  # match | mismatch | unset


@dataclass
class MatchOutcome:
    opportunity_id: int
    score: Optional[int]
    technical: Optional[int]
    soft: Optional[int]
    preferences: Optional[int]
    weights_used: dict
    required_coverage: Optional[int]
    comparisons: list
    preference_checks: list
    text_similarity: float = 0.0
    opportunity: object = None  # ORM instance when built from the database

    # Convenience views used by templates ---------------------------------
    @property
    def label(self):
        return label_for(self.score)

    @property
    def aligned(self):
        return [c for c in self.comparisons if c.status in ('meets', 'below', 'related')]

    @property
    def meets(self):
        return [c for c in self.comparisons if c.status == 'meets']

    @property
    def below_target(self):
        return [c for c in self.comparisons if c.status == 'below']

    @property
    def missing(self):
        return [c for c in self.comparisons if c.status in ('missing', 'related')]

    @property
    def missing_required(self):
        return [c for c in self.missing if c.is_required]

    @property
    def missing_preferred(self):
        return [c for c in self.missing if not c.is_required]

    @property
    def matched_required(self):
        return [c for c in self.comparisons if c.is_required and c.status in ('meets', 'below')]

    @property
    def matched_preferred(self):
        return [c for c in self.comparisons if not c.is_required and c.status in ('meets', 'below')]

    @property
    def matched_count(self):
        return len([c for c in self.comparisons if c.status in ('meets', 'below')])

    @property
    def total_count(self):
        return len(self.comparisons)

    @property
    def gaps(self):
        """Gaps ordered by priority: core missing, below target, nice-to-have."""
        def rank(c):
            if c.status in ('missing', 'related') and c.is_required:
                return (0, -c.target)
            if c.status == 'below':
                return (1 if c.is_required else 2, -c.gap_points)
            return (3, -c.target)
        return sorted(
            [c for c in self.comparisons if c.status in ('missing', 'related', 'below')],
            key=rank,
        )

    @property
    def strongest(self):
        matched = [c for c in self.comparisons if c.status == 'meets']
        return sorted(matched, key=lambda c: (
            not c.is_required, c.skill_type != 'technical', -(c.user_score or 0)))

    @property
    def components(self):
        rows = []
        for key, title in (('technical', 'Technical alignment'), ('soft', 'Soft skills'),
                           ('preferences', 'Role preferences')):
            value = getattr(self, key)
            rows.append({
                'key': key,
                'title': title,
                'value': value,
                'weight': round(WEIGHTS[key] * 100),
                'effective_weight': round(self.weights_used.get(key, 0) * 100),
            })
        return rows

    @property
    def summary_line(self):
        """One-line reason shown on opportunity cards."""
        strong = [c.name for c in self.strongest[:2]]
        gaps = self.gaps
        if not self.comparisons:
            return 'This role does not list specific skills yet.'
        if strong and gaps:
            gap = gaps[0]
            verb = 'would strengthen' if gap.status == 'below' else 'would round out'
            word = 'Deeper' if gap.status == 'below' else 'Adding'
            return f'Your {_join(strong)} align with this role. {word} {gap.name} {verb} your fit.'
        if strong:
            return f'Your {_join(strong)} align well with what this role asks for.'
        if self.below_target:
            names = _join([c.name for c in self.below_target[:2]])
            return f'You have a start in {names}; building depth would improve your fit.'
        return 'None of the listed skills are in your profile yet. A chance to grow.'

    @property
    def explanation(self):
        """A short paragraph explaining the result, built from real data."""
        sentences = []
        if not self.comparisons:
            sentences.append('This opportunity does not list required skills, so the score '
                             'is based on your role preferences only.')
        else:
            strong = self.strongest[:3]
            if strong:
                sentences.append(
                    f'Your {_join([c.name for c in strong])} '
                    f'{"meets" if len(strong) == 1 else "meet"} or exceed the role\'s target level.'
                )
            sentences.append(f'You meet {self.matched_count} of {self.total_count} listed skills.')
            if self.missing_required:
                names = _join([c.name for c in self.missing_required])
                sentences.append(f'{names} {"is a core requirement" if len(self.missing_required) == 1 else "are core requirements"} not yet in your profile.')
            if self.missing_preferred:
                names = _join([c.name for c in self.missing_preferred])
                plural = len(self.missing_preferred) > 1
                sentences.append(
                    f'{names} {"are" if plural else "is a"} nice-to-have{"s" if plural else ""} '
                    'rather than core requirement' + ('s.' if plural else '.')
                )
            if self.below_target:
                c = self.below_target[0]
                sentences.append(f'Your {c.name} is at {c.user_score}% against a role target of {c.target}%.')
            related = [c for c in self.comparisons if c.status == 'related']
            for c in related[:2]:
                sentences.append(f'Your {c.related_to} is related to {c.name}, so it counts partially.')
        if self.preferences is None:
            sentences.append('Add your career preferences to include location and work style.')
        return ' '.join(sentences)


def _join(names):
    names = list(names)
    if len(names) <= 1:
        return ''.join(names)
    return ', '.join(names[:-1]) + ' and ' + names[-1]


# ---------------------------------------------------------------------------
# Core calculation
# ---------------------------------------------------------------------------

def compare_skills(profile: ProfileData, opportunity: OpportunityData, related=None):
    related = related or {}
    by_name = {s.name: s for s in profile.skills.values()}
    comparisons = []
    for req in opportunity.requirements:
        target = max(1, int(req.target))
        user = profile.skills.get(req.skill_id)
        if user is not None:
            credit = min(1.0, user.score / target)
            status = 'meets' if user.score >= target else 'below'
            comparisons.append(SkillComparison(
                req.skill_id, req.name, req.skill_type, req.importance, target,
                user.score, status, credit,
            ))
            continue
        rel = related.get(req.name)
        if rel and rel[0] in by_name:
            rel_skill = by_name[rel[0]]
            credit = RELATED_CREDIT * min(1.0, rel_skill.score / target)
            comparisons.append(SkillComparison(
                req.skill_id, req.name, req.skill_type, req.importance, target,
                None, 'related', credit, related_to=rel_skill.name,
            ))
            continue
        comparisons.append(SkillComparison(
            req.skill_id, req.name, req.skill_type, req.importance, target, None, 'missing', 0.0,
        ))
    return comparisons


def _component(comparisons, skill_type):
    rows = [c for c in comparisons if c.skill_type == skill_type]
    if not rows:
        return None
    total_weight = sum(IMPORTANCE_WEIGHT[c.importance] for c in rows)
    earned = sum(IMPORTANCE_WEIGHT[c.importance] * c.credit for c in rows)
    return earned / total_weight


def check_preferences(profile: ProfileData, opportunity: OpportunityData):
    prefs = profile.preferences
    checks = []
    type_label = opportunity.type_label or opportunity.opportunity_type
    style_label = opportunity.work_style_label or opportunity.work_style

    if prefs.opportunity_types:
        ok = opportunity.opportunity_type in prefs.opportunity_types
        checks.append(PreferenceCheck('type', type_label, 'match' if ok else 'mismatch'))
    else:
        checks.append(PreferenceCheck('type', type_label, 'unset'))

    if prefs.work_styles:
        ok = opportunity.work_style in prefs.work_styles
        checks.append(PreferenceCheck('work_style', f'{style_label} work style',
                                      'match' if ok else 'mismatch'))
    else:
        checks.append(PreferenceCheck('work_style', f'{style_label} work style', 'unset'))

    loc = (opportunity.location or '').lower()
    if opportunity.work_style == 'remote':
        checks.append(PreferenceCheck('location', 'Remote, work from anywhere', 'match'))
    elif prefs.locations:
        ok = any(p.lower() in loc or (loc and loc in p.lower()) for p in prefs.locations)
        checks.append(PreferenceCheck('location', opportunity.location, 'match' if ok else 'mismatch'))
    else:
        checks.append(PreferenceCheck('location', opportunity.location, 'unset'))

    if opportunity.start_date:
        label = f'Starts {opportunity.start_date:%B %Y}'
        if prefs.available_from:
            ok = prefs.available_from <= opportunity.start_date
            checks.append(PreferenceCheck('start', label, 'match' if ok else 'mismatch'))
        else:
            checks.append(PreferenceCheck('start', label, 'unset'))

    if opportunity.eligible_user_types:
        names = {'student': 'students', 'graduate': 'recent graduates'}
        label = 'Open to ' + ' and '.join(names.get(t, t) for t in opportunity.eligible_user_types)
        ok = profile.user_type in opportunity.eligible_user_types
        checks.append(PreferenceCheck('eligibility', label, 'match' if ok else 'mismatch'))
    return checks


def _preference_component(checks, prefs: PreferenceData):
    decided = [c for c in checks if c.status != 'unset']
    has_preferences = bool(prefs.opportunity_types or prefs.work_styles
                           or prefs.locations or prefs.available_from)
    if not has_preferences:
        # Without stated preferences, only hard eligibility is a real signal
        # (an automatic "remote" location match would just inflate the score).
        decided = [c for c in decided if c.key == 'eligibility']
    if not decided:
        return None
    return sum(1 for c in decided if c.status == 'match') / len(decided)


def calculate_match(profile: ProfileData, opportunity: OpportunityData,
                    related=None, text_similarity=0.0) -> MatchOutcome:
    comparisons = compare_skills(profile, opportunity, related)
    checks = check_preferences(profile, opportunity)

    parts = {
        'technical': _component(comparisons, 'technical'),
        'soft': _component(comparisons, 'soft'),
        'preferences': _preference_component(checks, profile.preferences),
    }
    available = {k: WEIGHTS[k] for k, v in parts.items() if v is not None}
    weight_total = sum(available.values())
    if weight_total:
        weights_used = {k: w / weight_total for k, w in available.items()}
        raw = sum(parts[k] * weights_used[k] for k in available)
        score = int(round(raw * 100))
    else:
        weights_used, score = {}, None

    required = [c for c in comparisons if c.is_required]
    coverage = None
    if required:
        matched = len([c for c in required if c.status in ('meets', 'below')])
        coverage = int(round(matched / len(required) * 100))

    def pct(v):
        return None if v is None else int(round(v * 100))

    return MatchOutcome(
        opportunity_id=opportunity.id,
        score=score,
        technical=pct(parts['technical']),
        soft=pct(parts['soft']),
        preferences=pct(parts['preferences']),
        weights_used=weights_used,
        required_coverage=coverage,
        comparisons=comparisons,
        preference_checks=checks,
        text_similarity=round(float(text_similarity or 0.0), 4),
    )


def potential_score(profile: ProfileData, opportunity: OpportunityData, skill_ids=None):
    """Score the user *would* get if the given gap skills reached the role target.

    Used for the "illustrative match potential" on the skill-gap page.
    """
    skills = dict(profile.skills)
    for req in opportunity.requirements:
        if skill_ids is not None and req.skill_id not in skill_ids:
            continue
        current = skills.get(req.skill_id)
        if current is None or current.score < req.target:
            skills[req.skill_id] = UserSkillData(req.skill_id, req.name, req.target, req.skill_type)
    boosted = ProfileData(skills, profile.user_type, profile.preferences, profile.text)
    return calculate_match(boosted, opportunity).score


def rank(outcomes):
    """Best first: score, then text similarity as a tie-breaker. Unscored last."""
    return sorted(
        outcomes,
        key=lambda o: (o.score is None, -(o.score or 0), -o.text_similarity),
    )
