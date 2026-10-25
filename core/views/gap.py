from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from ..services import recommendations as rec
from .helpers import get_profile


@login_required
def skill_gap(request):
    """Skill-gap analysis for a target opportunity (default: strongest match)."""
    profile = get_profile(request.user)
    profile_data = rec.build_profile_data(profile)
    outcomes = rec.match_many(profile, rec.opportunity_queryset(), profile_data=profile_data) \
        if profile_data.skills else []

    target = None
    requested = request.GET.get('opportunity')
    if requested and requested.isdigit():
        target = next((o for o in outcomes if o.opportunity_id == int(requested)), None)
        if target is None and not profile_data.skills:
            opp = rec.opportunity_queryset().filter(pk=int(requested)).first()
            if opp:
                target = rec.match_many(profile, [opp], profile_data=profile_data)[0]
    if target is None and outcomes:
        target = outcomes[0]

    plan = rec.gap_plan(target, profile_data) if target else None
    return render(request, 'core/skill_gap.html', {
        'profile': profile,
        'target': target,
        'plan': plan,
        'choices': outcomes[:15],
        'in_demand': rec.in_demand_gaps(outcomes),
        'has_skills': bool(profile_data.skills),
        'active_nav': 'gap',
    })
