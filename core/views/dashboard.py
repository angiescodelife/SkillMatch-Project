from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from ..models import LearningResource
from ..services import recommendations as rec
from .helpers import get_profile

STRONG_THRESHOLD = 85
RECOMMEND_THRESHOLD = 50


@login_required
def dashboard(request):
    profile = get_profile(request.user)
    counts = rec.skill_counts(profile)
    completion = rec.profile_completion(profile)

    outcomes = rec.recommend(profile) if counts['total'] else []
    recommended = [o for o in outcomes if (o.score or 0) >= RECOMMEND_THRESHOLD]
    strong = [o for o in recommended if o.score >= STRONG_THRESHOLD]
    top = recommended[0] if recommended else None
    saved_ids = set(profile.saved.values_list('opportunity_id', flat=True))

    next_step = None
    if top and top.gaps:
        gap = top.gaps[0]
        next_step = {
            'gap': gap,
            'resource': LearningResource.objects.filter(skill_id=gap.skill_id).order_by('hours').first(),
            'outcome': top,
        }

    snapshot = profile.user_skills.select_related('skill').order_by('-proficiency_score')[:3]

    hour = timezone.localtime().hour
    greeting = 'Good morning' if hour < 12 else ('Good afternoon' if hour < 17 else 'Good evening')

    return render(request, 'core/dashboard.html', {
        'greeting': greeting,
        'profile': profile,
        'counts': counts,
        'completion': completion,
        'recommended': recommended[:2],
        'recommended_count': len(recommended),
        'strong_count': len(strong),
        'top': top,
        'saved_ids': saved_ids,
        'saved_count': len(saved_ids),
        'next_step': next_step,
        'snapshot': snapshot,
        'has_skills': counts['total'] > 0,
        'active_nav': 'dashboard',
    })
