"""Database-facing layer around the matching engine.

Builds plain data from Django models, runs the engine, stores results
(MatchResult) and assembles the skill-gap learning plan and profile
completeness shown on the dashboard.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from django.db.models import Prefetch

from ..models import (
    CareerPreference, CV, ExtractedSkill, LearningResource, MatchResult, Opportunity,
    OpportunitySkill, Skill, UserProfile, UserSkill,
)
from . import matching, similarity

MAX_CV_TEXT = 20000


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def get_preferences(profile):
    prefs, _ = CareerPreference.objects.get_or_create(profile=profile)
    return prefs


def build_profile_data(profile: UserProfile) -> matching.ProfileData:
    user_skills = profile.user_skills.select_related('skill')
    skills = {
        us.skill_id: matching.UserSkillData(
            us.skill_id, us.skill.name, us.proficiency_score, us.skill.skill_type
        )
        for us in user_skills
    }
    prefs = get_preferences(profile)
    preference_data = matching.PreferenceData(
        opportunity_types=list(prefs.opportunity_types or []),
        work_styles=list(prefs.work_styles or []),
        locations=prefs.location_list(),
        available_from=prefs.available_from,
    )
    cv = profile.current_cv
    text_parts = [
        profile.course_of_study, profile.career_interest, profile.headline, profile.about,
        ' '.join(s.name for s in skills.values()),
    ]
    if cv and cv.extracted_text:
        text_parts.append(cv.extracted_text[:MAX_CV_TEXT])
    return matching.ProfileData(
        skills=skills,
        user_type=profile.user_type,
        preferences=preference_data,
        text='\n'.join(p for p in text_parts if p),
    )


def opportunity_queryset():
    return Opportunity.objects.active().select_related('employer').prefetch_related(
        Prefetch('skill_requirements',
                 queryset=OpportunitySkill.objects.select_related('skill'))
    )


def build_opportunity_data(opp: Opportunity) -> matching.OpportunityData:
    reqs = sorted(
        (matching.RequirementData(
            r.skill_id, r.skill.name, r.importance, r.target_score, r.skill.skill_type)
         for r in opp.skill_requirements.all()),
        # Required before nice-to-have, technical before soft, highest target first.
        key=lambda r: (r.importance != 'required', r.skill_type != 'technical', -r.target, r.name),
    )
    text = '\n'.join([
        opp.title, opp.summary, opp.description, opp.responsibilities,
        ' '.join(r.name for r in reqs),
    ])
    return matching.OpportunityData(
        id=opp.pk,
        requirements=reqs,
        opportunity_type=opp.opportunity_type,
        work_style=opp.work_style,
        location=opp.location,
        start_date=opp.start_date,
        eligible_user_types=list(opp.eligible_user_types or []),
        text=text,
        type_label=opp.get_opportunity_type_display(),
        work_style_label=opp.get_work_style_display(),
    )


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def match_many(profile, opportunities, persist=True, profile_data=None):
    """Score every opportunity for this profile. Returns outcomes ranked best-first."""
    opportunities = list(opportunities)
    if not opportunities:
        return []
    profile_data = profile_data or build_profile_data(profile)
    opp_data = [build_opportunity_data(o) for o in opportunities]
    sims = similarity.text_similarities(profile_data.text, [d.text for d in opp_data])

    # Related-skill detection (transformer back-end only; returns {} otherwise).
    missing_names = {
        r.name for d in opp_data for r in d.requirements if r.skill_id not in profile_data.skills
    }
    related = similarity.related_skills(
        sorted(missing_names), [s.name for s in profile_data.skills.values()]
    )

    outcomes = []
    for opp, data, sim in zip(opportunities, opp_data, sims):
        outcome = matching.calculate_match(profile_data, data, related, sim)
        outcome.opportunity = opp
        outcome.opportunity_data = data
        outcomes.append(outcome)
    if persist:
        save_results(profile, outcomes)
    return matching.rank(outcomes)


def match_one(profile, opportunity, persist=True):
    opp = opportunity_queryset().filter(pk=opportunity.pk).first() or opportunity
    results = match_many(profile, [opp], persist=persist)
    return results[0]


def recommend(profile, persist=True):
    return match_many(profile, opportunity_queryset(), persist=persist)


def save_results(profile, outcomes):
    existing = {
        m.opportunity_id: m
        for m in MatchResult.objects.filter(
            profile=profile, opportunity_id__in=[o.opportunity_id for o in outcomes]
        )
    }
    to_create, to_update = [], []
    for o in outcomes:
        details = {
            'weights_used': o.weights_used,
            'matched_required': [c.name for c in o.matched_required],
            'missing_required': [c.name for c in o.missing_required],
            'matched_preferred': [c.name for c in o.matched_preferred],
            'missing_preferred': [c.name for c in o.missing_preferred],
            'below_target': [c.name for c in o.below_target],
            'similarity_backend': similarity.backend_name(),
        }
        values = dict(
            score=o.score, required_coverage=o.required_coverage, technical_score=o.technical,
            soft_score=o.soft, preference_score=o.preferences, text_similarity=o.text_similarity,
            details=details,
        )
        row = existing.get(o.opportunity_id)
        if row is None:
            to_create.append(MatchResult(profile=profile, opportunity_id=o.opportunity_id, **values))
        else:
            for k, v in values.items():
                setattr(row, k, v)
            to_update.append(row)
    if to_create:
        MatchResult.objects.bulk_create(to_create, ignore_conflicts=True)
    if to_update:
        MatchResult.objects.bulk_update(to_update, list(values.keys()))


# ---------------------------------------------------------------------------
# Skill-gap learning plan
# ---------------------------------------------------------------------------

@dataclass
class GapItem:
    comparison: matching.SkillComparison
    resource: LearningResource | None
    priority: str

    @property
    def status_text(self):
        c = self.comparison
        if c.status == 'related':
            return f'Related: you have {c.related_to}'
        if c.user_score is None:
            return 'Not listed in your profile'
        return f'{c.user_score}% in your profile'

    @property
    def is_priority(self):
        return self.priority in ('Core gap', 'Below target')


def gap_plan(outcome: matching.MatchOutcome, profile_data: matching.ProfileData | None = None):
    gaps = outcome.gaps
    skill_ids = [g.skill_id for g in gaps]
    resources = {}
    for r in LearningResource.objects.filter(skill_id__in=skill_ids).order_by('hours'):
        resources.setdefault(r.skill_id, r)

    items = []
    for c in gaps:
        if c.status in ('missing', 'related'):
            priority = 'Core gap' if c.is_required else 'Nice-to-have'
        else:
            priority = 'Below target' if c.is_required else 'Nice-to-have'
        items.append(GapItem(c, resources.get(c.skill_id), priority))

    hours = sum(float(i.resource.hours) for i in items if i.resource)
    potential = None
    if profile_data is not None and getattr(outcome, 'opportunity_data', None):
        potential = matching.potential_score(profile_data, outcome.opportunity_data)

    # "Go a little further": a skill already meeting the target by the smallest margin.
    further = None
    candidates = sorted(outcome.meets, key=lambda c: (c.user_score or 0) - c.target)
    for c in candidates:
        res = LearningResource.objects.filter(skill_id=c.skill_id).exclude(level='beginner').first() \
            or LearningResource.objects.filter(skill_id=c.skill_id).first()
        if res:
            further = {'comparison': c, 'resource': res}
            break

    return {
        'items': items,
        'hours': hours,
        'potential': potential,
        'further': further,
        'priority_count': len([i for i in items if i.is_priority]) or len(items),
        'core_count': len([i for i in items if i.is_priority]),
    }


def in_demand_gaps(outcomes, limit=5, top_n=10):
    """Skills missing most often across the user's best matches."""
    counter, names = Counter(), {}
    for o in outcomes[:top_n]:
        for c in o.missing:
            counter[c.skill_id] += 2 if c.is_required else 1
            names[c.skill_id] = c.name
    return [{'skill_id': sid, 'name': names[sid], 'weight': w}
            for sid, w in counter.most_common(limit)]


# ---------------------------------------------------------------------------
# Profile completeness
# ---------------------------------------------------------------------------

def profile_completion(profile: UserProfile):
    user = profile.user
    prefs = get_preferences(profile)
    cv = profile.current_cv
    skill_count = profile.user_skills.count()
    nouns = {
        'Personal information': 'personal details', 'Education added': 'education',
        'Resume reviewed': 'resume', 'Skills confirmed': 'skills',
        'Project portfolio': 'project portfolio', 'Availability': 'availability',
    }
    items = [
        ('Personal information', bool(user.get_full_name() and profile.location
                                       and profile.headline and profile.about),
         'Add your name, location, headline and a short bio.'),
        ('Education added', bool(profile.university and profile.course_of_study
                                  and profile.graduation_year and profile.degree_level),
         'Add your university, course, degree level and graduation year.'),
        ('Resume reviewed', bool(cv and cv.is_reviewed),
         'Upload your resume and review the skills we find.'),
        ('Skills confirmed', skill_count >= 3, 'Add at least three skills.'),
        ('Project portfolio', bool(prefs.portfolio_url), 'Link a portfolio, GitHub or project page.'),
        ('Availability', bool(prefs.available_from), 'Tell us when you can start.'),
    ]
    done = sum(1 for _, ok, _ in items if ok)
    percent = int(round(done / len(items) * 100))
    missing = [label for label, ok, _ in items if not ok]
    missing_nouns = [nouns[label] for label in missing]
    if len(missing_nouns) > 1:
        phrase = ', '.join(missing_nouns[:-1]) + ' and ' + missing_nouns[-1]
    else:
        phrase = ''.join(missing_nouns)
    return {
        'percent': percent,
        'missing_phrase': phrase,
        'items': [{'label': l, 'done': ok, 'hint': h} for l, ok, h in items],
        'missing': missing,
        'missing_count': len(missing),
    }


def skill_counts(profile):
    qs = profile.user_skills.select_related('skill')
    technical = qs.filter(skill__skill_type=Skill.TECHNICAL).count()
    soft = qs.filter(skill__skill_type=Skill.SOFT).count()
    return {'total': technical + soft, 'technical': technical, 'soft': soft}
