from django.utils.http import url_has_allowed_host_and_scheme

from ..models import CareerPreference, UserProfile


def get_profile(user):
    """Return the user's profile, creating one for accounts made elsewhere
    (e.g. superusers or Google sign-in) so pages never crash."""
    profile, _ = UserProfile.objects.get_or_create(user=user, defaults={'user_type': 'student'})
    CareerPreference.objects.get_or_create(profile=profile)
    return profile


def safe_next(request, fallback):
    nxt = request.POST.get('next') or request.GET.get('next')
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()},
                                                require_https=request.is_secure()):
        return nxt
    return fallback
