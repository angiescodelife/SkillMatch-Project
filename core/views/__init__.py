"""SkillMatch views, grouped by screen.

The original URL names (home, register, login, logout, dashboard, skills)
are preserved.
"""
from .auth import home, register, user_login, user_logout  # noqa: F401
from .dashboard import dashboard  # noqa: F401
from .profile import (  # noqa: F401
    account_settings, career_preferences, cv_delete, cv_download, cv_review, cv_upload, profile,
)
from .skills import manage_skills, skill_update  # noqa: F401
from .opportunities import (  # noqa: F401
    opportunity_apply, opportunity_detail, opportunity_list, opportunity_save, saved_list,
)
from .gap import skill_gap  # noqa: F401
from .pages import help_page, privacy, search, terms  # noqa: F401
