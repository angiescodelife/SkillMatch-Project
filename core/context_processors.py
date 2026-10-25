from django.conf import settings


def skillmatch(request):
    """Values used by the shared layout (sidebar, top bar, auth screens)."""
    data = {'GOOGLE_LOGIN_ENABLED': settings.GOOGLE_LOGIN_ENABLED}
    user = getattr(request, 'user', None)
    if user is not None and user.is_authenticated:
        profile = getattr(user, 'userprofile', None)
        data['nav_profile'] = profile
        data['nav_saved_count'] = profile.saved.count() if profile else 0
    return data
