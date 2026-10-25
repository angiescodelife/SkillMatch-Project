from allauth.socialaccount.adapter import DefaultSocialAccountAdapter

from .models import CareerPreference, UserProfile


class SkillMatchSocialAccountAdapter(DefaultSocialAccountAdapter):
    """Create a SkillMatch profile for people who sign up with Google."""

    def save_user(self, request, sociallogin, form=None):
        user = super().save_user(request, sociallogin, form)
        profile, _ = UserProfile.objects.get_or_create(user=user, defaults={'user_type': 'student'})
        CareerPreference.objects.get_or_create(profile=profile)
        return user

    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)
        if user.email and not user.username:
            user.username = user.email.lower()[:150]
        return user
