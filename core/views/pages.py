from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render

from ..services import matching, similarity
from ..services import recommendations as rec
from .helpers import get_profile


@login_required
def search(request):
    profile = get_profile(request.user)
    q = request.GET.get('q', '').strip()[:100]
    outcomes, skills = [], []
    if q:
        qs = rec.opportunity_queryset().filter(
            Q(title__icontains=q) | Q(employer__name__icontains=q)
            | Q(skill_requirements__skill__name__icontains=q)
        ).distinct()
        outcomes = rec.match_many(profile, qs)
        skills = profile.user_skills.select_related('skill').filter(skill__name__icontains=q)
    return render(request, 'core/search.html', {
        'profile': profile, 'q': q, 'outcomes': outcomes, 'skills': skills,
        'saved_ids': set(profile.saved.values_list('opportunity_id', flat=True)),
        'has_skills': profile.user_skills.exists(),
    })


def help_page(request):
    return render(request, 'core/pages/help.html', {
        'weights': {k: round(v * 100) for k, v in matching.WEIGHTS.items()},
        'importance': matching.IMPORTANCE_WEIGHT,
        'related_credit': round(matching.RELATED_CREDIT * 100),
        'labels': matching.LABELS,
        'backend': similarity.backend_name(),
        'active_nav': 'help',
        'profile': get_profile(request.user) if request.user.is_authenticated else None,
    })


def privacy(request):
    return render(request, 'core/pages/privacy.html')


def terms(request):
    return render(request, 'core/pages/terms.html')
