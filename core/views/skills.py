from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..forms import SkillForm, SkillLevelForm
from ..models import DEFAULT_SCORE_FOR_LEVEL, LEVEL_BANDS, Skill, UserSkill
from .helpers import get_profile


@login_required
def manage_skills(request):
    profile = get_profile(request.user)

    if request.method == 'POST':
        if request.POST.get('action') == 'remove':
            user_skill_id = request.POST.get('user_skill_id')

            deleted, _ = UserSkill.objects.filter(
                id=user_skill_id,
                profile=profile
            ).delete()

            if deleted:
                messages.success(request, 'Skill removed successfully.')
            else:
                messages.error(request, 'Skill could not be found.')

            return redirect('skills')

        data = request.POST.copy()
        # Accept the original form's level field as well as the new score.
        if not data.get('proficiency_score') and data.get('proficiency') in DEFAULT_SCORE_FOR_LEVEL:
            data['proficiency_score'] = DEFAULT_SCORE_FOR_LEVEL[data['proficiency']]
        form = SkillForm(data)

        if form.is_valid():
            skill_name = form.cleaned_data['name']
            category = form.cleaned_data['category'].strip()
            score = form.cleaned_data['proficiency_score']

            skill = Skill.resolve(skill_name)
            if skill is None:
                skill = Skill.objects.create(
                    name=skill_name,
                    category=category,
                    skill_type=form.cleaned_data.get('skill_type') or Skill.TECHNICAL,
                )

            user_skill, created = UserSkill.objects.get_or_create(
                profile=profile,
                skill=skill,
                defaults={'proficiency_score': score, 'source': UserSkill.SOURCE_SELF},
            )

            if created:
                messages.success(request, f'{skill.name} added to your skills!')
            else:
                user_skill.proficiency_score = score
                user_skill.save(update_fields=['proficiency_score'])
                messages.info(
                    request,
                    f'{skill.name} is already on your list. Its proficiency has been updated.'
                )

            return redirect('skills')
        messages.error(request, 'Please check the skill details and try again.')
    else:
        form = SkillForm()

    user_skills = UserSkill.objects.filter(
        profile=profile
    ).select_related('skill').order_by('-proficiency_score', 'skill__name')

    technical = [s for s in user_skills if s.skill.skill_type == Skill.TECHNICAL]
    soft = [s for s in user_skills if s.skill.skill_type == Skill.SOFT]
    self_added = [s for s in user_skills if s.source == UserSkill.SOURCE_SELF]
    categories = sorted({s.skill.category for s in technical if s.skill.category})

    return render(request, 'core/skills.html', {
        'profile': profile,
        'form': form,
        'user_skills': user_skills,
        'technical': technical,
        'soft': soft,
        'resume_count': len([s for s in user_skills if s.source == UserSkill.SOURCE_RESUME]),
        'self_added': self_added,
        'categories': categories,
        'level_bands': LEVEL_BANDS,
        'dictionary': Skill.objects.filter(in_dictionary=True).values_list('name', flat=True),
        'show_add': request.method == 'POST' and form.errors,
        'active_nav': 'skills',
    })


@login_required
@require_POST
def skill_update(request, pk):
    profile = get_profile(request.user)
    user_skill = get_object_or_404(UserSkill, pk=pk, profile=profile)
    form = SkillLevelForm(request.POST)
    if form.is_valid():
        user_skill.proficiency_score = form.cleaned_data['proficiency_score']
        user_skill.save(update_fields=['proficiency_score'])
        messages.success(request, f'{user_skill.skill.name} updated to '
                                  f'{user_skill.proficiency_score}% ({user_skill.get_proficiency_display()}).')
    else:
        messages.error(request, 'Proficiency must be a number between 1 and 100.')
    return redirect('skills')
