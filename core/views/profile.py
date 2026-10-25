from pathlib import Path

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..forms import CareerPreferenceForm, CVUploadForm, ProfileForm
from ..models import CV, ExtractedSkill, UserSkill
from ..services import cv_extraction
from ..services import recommendations as rec
from .helpers import get_profile


def _sidebar_context(profile):
    return {
        'completion': rec.profile_completion(profile),
        'preferences': rec.get_preferences(profile),
    }


@login_required
def profile(request):
    profile = get_profile(request.user)
    form = ProfileForm(request.POST or None, request.FILES or None, instance=profile)
    if request.method == 'POST':
        if form.is_valid():
            form.save()
            messages.success(request, 'Your profile has been saved.')
            return redirect('profile')
        messages.error(request, 'Please correct the highlighted fields.')
    cv = profile.current_cv
    context = {
        'profile': profile,
        'form': form,
        'cv': cv,
        'cv_form': CVUploadForm(),
        'tab': 'profile',
        'active_nav': 'profile',
        'cv_added_count': cv.extracted_skills.filter(
            status=ExtractedSkill.ACCEPTED, already_in_profile=False).count() if cv else 0,
        'cv_found_count': cv.extracted_skills.count() if cv else 0,
    }
    context.update(_sidebar_context(profile))
    return render(request, 'core/profile/profile.html', context)


@login_required
def career_preferences(request):
    profile = get_profile(request.user)
    prefs = rec.get_preferences(profile)
    form = CareerPreferenceForm(request.POST or None, instance=prefs)
    if request.method == 'POST':
        if form.is_valid():
            form.save()
            messages.success(request, 'Your career preferences have been saved. Matches are updated.')
            return redirect('career_preferences')
        messages.error(request, 'Please correct the highlighted fields.')
    context = {'profile': profile, 'form': form, 'tab': 'preferences', 'active_nav': 'profile'}
    context.update(_sidebar_context(profile))
    return render(request, 'core/profile/preferences.html', context)


@login_required
def account_settings(request):
    profile = get_profile(request.user)
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == 'POST':
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, 'Your password has been changed.')
            return redirect('account_settings')
        messages.error(request, 'Please correct the highlighted fields.')
    for name in form.fields:
        form.fields[name].widget.attrs.setdefault('autocomplete', 'new-password' if 'new' in name else 'current-password')
    context = {'profile': profile, 'form': form, 'tab': 'account', 'active_nav': 'profile',
               'has_usable_password': request.user.has_usable_password()}
    context.update(_sidebar_context(profile))
    return render(request, 'core/profile/account.html', context)


# ---------------------------------------------------------------------------
# CV upload, review and access
# ---------------------------------------------------------------------------

@login_required
@require_POST
def cv_upload(request):
    profile = get_profile(request.user)
    form = CVUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        for error in form.errors.get('file', []):
            messages.error(request, error)
        return redirect('profile')

    upload = form.cleaned_data['file']
    with transaction.atomic():
        previous = list(profile.cvs.filter(is_current=True))
        cv = CV(profile=profile, original_name=Path(upload.name).name[:255], size=upload.size)
        cv.file.save(upload.name, upload, save=False)
        cv.save()
        profile.cvs.exclude(pk=cv.pk).update(is_current=False)

    cv_extraction.process_cv(cv)
    if cv.status == CV.STATUS_FAILED:
        messages.error(request, f'Your resume was uploaded, but we couldn\'t extract skills: {cv.error_message}')
        return redirect('profile')

    # Remove older files once the new one has been processed successfully.
    for old in previous:
        old.file.delete(save=False)
        old.delete()

    found = cv.extracted_skills.count()
    if found == 0:
        messages.info(request, 'Your resume was read, but no skills from our dictionary were found. '
                               'You can add skills manually on the My skills page.')
        return redirect('profile')
    return redirect('cv_review', pk=cv.pk)


@login_required
def cv_review(request, pk):
    profile = get_profile(request.user)
    cv = get_object_or_404(CV, pk=pk, profile=profile)
    items = list(cv.extracted_skills.select_related('skill'))

    if request.method == 'POST':
        added = 0
        with transaction.atomic():
            for item in items:
                if item.already_in_profile:
                    continue
                if request.POST.get(f'keep_{item.pk}'):
                    try:
                        score = int(request.POST.get(f'score_{item.pk}', 40))
                    except (TypeError, ValueError):
                        score = 40
                    score = max(1, min(100, score))
                    UserSkill.objects.update_or_create(
                        profile=profile, skill=item.skill,
                        defaults={'proficiency_score': score, 'source': UserSkill.SOURCE_RESUME},
                    )
                    item.status = ExtractedSkill.ACCEPTED
                    added += 1
                else:
                    item.status = ExtractedSkill.REJECTED
                item.save(update_fields=['status'])
            cv.reviewed_at = timezone.now()
            cv.save(update_fields=['reviewed_at'])
        messages.success(request, f'{added} skill{"s" if added != 1 else ""} from your resume added to your profile.')
        return redirect('skills')

    for item in items:
        item.suggested = cv_extraction.suggested_score(item.occurrences)
    return render(request, 'core/profile/cv_review.html', {
        'profile': profile, 'cv': cv, 'items': items, 'active_nav': 'profile',
        'new_items': [i for i in items if not i.already_in_profile],
        'existing_items': [i for i in items if i.already_in_profile],
    })


@login_required
def cv_download(request, pk):
    profile = get_profile(request.user)
    cv = get_object_or_404(CV, pk=pk, profile=profile)  # owners only
    try:
        handle = cv.file.open('rb')
    except FileNotFoundError:
        raise Http404('File not found')
    return FileResponse(handle, as_attachment=False, filename=cv.original_name)


@login_required
@require_POST
def cv_delete(request, pk):
    profile = get_profile(request.user)
    cv = get_object_or_404(CV, pk=pk, profile=profile)
    cv.file.delete(save=False)
    cv.delete()
    messages.success(request, 'Your resume has been deleted. Skills you confirmed stay on your profile.')
    return redirect('profile')
