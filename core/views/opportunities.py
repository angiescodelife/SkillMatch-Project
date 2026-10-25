from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from ..models import OPPORTUNITY_TYPES, WORK_STYLES, Application, Opportunity, SavedOpportunity
from ..services import recommendations as rec
from .dashboard import RECOMMEND_THRESHOLD
from .helpers import get_profile, safe_next

PAGE_SIZE = 4


def _int(value, default=None, low=None, high=None):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return default
    if low is not None:
        value = max(low, value)
    if high is not None:
        value = min(high, value)
    return value


def _search(qs, q, loc):
    if q:
        qs = qs.filter(
            Q(title__icontains=q) | Q(employer__name__icontains=q) | Q(summary__icontains=q)
            | Q(skill_requirements__skill__name__icontains=q)
            | Q(skill_requirements__skill__aliases__alias__iexact=q)
        ).distinct()
    if loc:
        terms = [t.strip() for t in loc.replace(' or ', ',').split(',') if t.strip()]
        cond = Q()
        for t in terms:
            if t.lower() == 'remote':
                cond |= Q(work_style='remote')
            else:
                cond |= Q(location__icontains=t)
        qs = qs.filter(cond)
    return qs


@login_required
def opportunity_list(request):
    profile = get_profile(request.user)
    has_skills = profile.user_skills.exists()
    g = request.GET

    q = g.get('q', '').strip()[:100]
    loc = g.get('loc', '').strip()[:100]
    tab = g.get('tab', 'foryou' if has_skills else 'all')
    if tab not in ('foryou', 'all'):
        tab = 'foryou'
    types = [t for t in g.getlist('type') if t in dict(OPPORTUNITY_TYPES)]
    styles = [s for s in g.getlist('style') if s in dict(WORK_STYLES)]
    min_match = _int(g.get('min'), 0, 0, 100)
    start = g.get('start', '')
    skill_ids = [i for i in (_int(x) for x in g.getlist('skill')) if i]
    sort = g.get('sort', 'match')

    base = _search(rec.opportunity_queryset(), q, loc)
    outcomes = rec.match_many(profile, base)

    def passes(o, ignore=None):
        opp = o.opportunity
        if tab == 'foryou' and (o.score or 0) < RECOMMEND_THRESHOLD:
            return False
        if ignore != 'type' and types and opp.opportunity_type not in types:
            return False
        if ignore != 'style' and styles and opp.work_style not in styles:
            return False
        if ignore != 'min' and min_match and (o.score or 0) < min_match:
            return False
        if ignore != 'start' and start and opp.start_label != start:
            return False
        if ignore != 'skill' and skill_ids:
            req_ids = {c.skill_id for c in o.comparisons}
            if not set(skill_ids) & req_ids:
                return False
        return True

    filtered = [o for o in outcomes if passes(o)]
    if sort == 'newest':
        filtered.sort(key=lambda o: o.opportunity.posted_at, reverse=True)

    # Facet counts (each ignores its own filter so options stay discoverable).
    type_counts = {k: 0 for k, _ in OPPORTUNITY_TYPES}
    style_counts = {k: 0 for k, _ in WORK_STYLES}
    for o in outcomes:
        if passes(o, ignore='type'):
            type_counts[o.opportunity.opportunity_type] += 1
        if passes(o, ignore='style'):
            style_counts[o.opportunity.work_style] += 1
    foryou_count = len([o for o in outcomes if (o.score or 0) >= RECOMMEND_THRESHOLD])

    paginator = Paginator(filtered, PAGE_SIZE)
    page = paginator.get_page(g.get('page'))

    user_skills = profile.user_skills.select_related('skill').order_by('skill__name')
    selected_skills = [us.skill for us in user_skills if us.skill_id in skill_ids]
    start_options = (Opportunity.objects.active().exclude(start_label='')
                     .order_by('start_date').values_list('start_label', flat=True).distinct())

    # Removable filter chips.
    params = g.copy()
    params.pop('page', None)

    def without(key, value=None):
        p = params.copy()
        if value is None:
            p.pop(key, None)
        else:
            p.setlist(key, [v for v in p.getlist(key) if v != str(value)])
        return '?' + p.urlencode()

    chips = []
    for t in types:
        chips.append((dict(OPPORTUNITY_TYPES)[t], without('type', t)))
    if styles:
        chips.append((' + '.join(dict(WORK_STYLES)[s] for s in styles).lower().capitalize(),
                      without('style')))
    if min_match:
        chips.append((f'{min_match}%+ match', without('min')))
    if start:
        chips.append((start, without('start')))
    for s in selected_skills:
        chips.append((s.name, without('skill', s.pk)))

    tab_params = params.copy()
    tab_params.pop('tab', None)

    return render(request, 'core/opportunities/list.html', {
        'profile': profile,
        'page': page,
        'outcomes': page.object_list,
        'total': len(filtered),
        'foryou_count': foryou_count,
        'all_count': len(outcomes),
        'tab': tab,
        'q': q, 'loc': loc,
        'types': types, 'styles': styles, 'min_match': min_match, 'start': start,
        'skill_ids': skill_ids, 'sort': sort,
        'type_options': [(k, v, type_counts[k]) for k, v in OPPORTUNITY_TYPES],
        'style_options': [(k, v, style_counts[k]) for k, v in WORK_STYLES],
        'start_options': start_options,
        'user_skills': user_skills,
        'chips': chips,
        'clear_url': '?' + urlencode({k: v for k, v in (('tab', tab), ('q', q), ('loc', loc)) if v}),
        'tab_query': tab_params.urlencode(),
        'page_query': params.urlencode(),
        'saved_ids': set(profile.saved.values_list('opportunity_id', flat=True)),
        'has_skills': has_skills,
        'active_nav': 'opportunities',
    })


@login_required
def opportunity_detail(request, pk):
    profile = get_profile(request.user)
    opp = get_object_or_404(rec.opportunity_queryset(), pk=pk)
    profile_data = rec.build_profile_data(profile)
    outcome = rec.match_many(profile, [opp], profile_data=profile_data)[0]
    plan = rec.gap_plan(outcome, profile_data)
    return render(request, 'core/opportunities/detail.html', {
        'profile': profile,
        'opp': opp,
        'o': outcome,
        'plan': plan,
        'is_saved': profile.saved.filter(opportunity=opp).exists(),
        'application': profile.applications.filter(opportunity=opp).first(),
        'has_skills': bool(profile_data.skills),
        'requirements': opp.skill_requirements.all(),
        'active_nav': 'opportunities',
    })


@login_required
@require_POST
def opportunity_save(request, pk):
    profile = get_profile(request.user)
    opp = get_object_or_404(Opportunity, pk=pk)
    saved, created = SavedOpportunity.objects.get_or_create(profile=profile, opportunity=opp)
    if not created:
        saved.delete()
    is_saved = created
    if request.headers.get('x-requested-with') == 'fetch':
        return JsonResponse({'saved': is_saved, 'count': profile.saved.count()})
    messages.success(request, f'{"Saved" if is_saved else "Removed"} {opp.title}.')
    return redirect(safe_next(request, reverse('opportunity_detail', args=[pk])))


@login_required
@require_POST
def opportunity_apply(request, pk):
    profile = get_profile(request.user)
    opp = get_object_or_404(Opportunity.objects.active(), pk=pk)
    outcome = rec.match_one(profile, opp)
    Application.objects.get_or_create(
        profile=profile, opportunity=opp, defaults={'match_score': outcome.score},
    )
    if opp.application_url:
        return redirect(opp.application_url)
    messages.info(request, opp.application_instructions or
                  'This employer has not added application instructions yet.')
    return redirect('opportunity_detail', pk=pk)


@login_required
def saved_list(request):
    profile = get_profile(request.user)
    saved = list(profile.saved.select_related('opportunity'))
    order = {s.opportunity_id: i for i, s in enumerate(saved)}
    qs = rec.opportunity_queryset().filter(pk__in=order.keys())
    outcomes = sorted(rec.match_many(profile, qs), key=lambda o: order[o.opportunity_id])
    return render(request, 'core/opportunities/saved.html', {
        'profile': profile,
        'outcomes': outcomes,
        'saved_ids': set(order.keys()),
        'has_skills': profile.user_skills.exists(),
        'active_nav': 'saved',
    })
