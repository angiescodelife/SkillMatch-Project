from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailOrUsernameBackend(ModelBackend):
    """Authenticate with an email address or a username.

    Accounts created before email login existed keep working with their
    usernames; new accounts sign in with the email shown in the design.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        identifier = (username or kwargs.get('email') or '').strip()
        if not identifier or password is None:
            return None
        user = None
        if '@' in identifier:
            # Emails are not unique in auth_user; only accept an unambiguous match.
            matches = list(UserModel._default_manager.filter(email__iexact=identifier)[:2])
            if len(matches) == 1:
                user = matches[0]
        if user is None:
            try:
                user = UserModel._default_manager.get_by_natural_key(identifier)
            except UserModel.DoesNotExist:
                UserModel().set_password(password)  # mitigate timing attacks
                return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
