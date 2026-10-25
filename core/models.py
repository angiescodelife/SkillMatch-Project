import re
import uuid
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.storage import FileSystemStorage
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalise_skill_name(value):
    """Return a canonical key for a skill name.

    "  React.js ", "react js" and "ReactJS" all normalise to "reactjs".
    Symbols that carry meaning in skill names (+, #) are kept so that
    "C++" and "C#" stay distinct from "C".
    """
    value = (value or '').strip().lower()
    value = value.replace('&', 'and')
    value = re.sub(r'[^a-z0-9+#]+', '', value)
    return value


class PrivateMediaStorage(FileSystemStorage):
    """Storage for CVs, kept outside MEDIA_ROOT so files are never publicly
    served. Reads PRIVATE_MEDIA_ROOT on every access so tests can override it."""

    @property
    def base_location(self):
        return str(getattr(settings, 'PRIVATE_MEDIA_ROOT', settings.BASE_DIR / 'private_media'))

    @property
    def location(self):
        import os
        return os.path.abspath(self.base_location)

    @property
    def base_url(self):
        return None


def private_storage():
    return PrivateMediaStorage()


def cv_upload_path(instance, filename):
    ext = Path(filename).suffix.lower()
    return f'cvs/{instance.profile_id}/{uuid.uuid4().hex}{ext}'


def avatar_upload_path(instance, filename):
    ext = Path(filename).suffix.lower()
    return f'avatars/{uuid.uuid4().hex}{ext}'


PROFICIENCY_LEVELS = [
    ('beginner', 'Beginner'),
    ('intermediate', 'Intermediate'),
    ('advanced', 'Advanced'),
]

# Percentage bands used by the "What your levels mean" card in the design.
LEVEL_BANDS = {
    'beginner': (1, 39),
    'intermediate': (40, 79),
    'advanced': (80, 100),
}
DEFAULT_SCORE_FOR_LEVEL = {'beginner': 30, 'intermediate': 60, 'advanced': 85}


def level_for_score(score):
    if score is None:
        return 'beginner'
    if score >= 80:
        return 'advanced'
    if score >= 40:
        return 'intermediate'
    return 'beginner'


WORK_STYLES = [
    ('remote', 'Remote'),
    ('hybrid', 'Hybrid'),
    ('onsite', 'On-site'),
]

OPPORTUNITY_TYPES = [
    ('internship', 'Internship'),
    ('full_time', 'Full-time'),
    ('part_time', 'Part-time'),
    ('graduate', 'Graduate programme'),
]


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------

class UserProfile(models.Model):
    USER_TYPES = [
        ('student', 'Student'),
        ('graduate', 'Recent Graduate'),
    ]
    DEGREE_LEVELS = [
        ('certificate', 'Certificate'),
        ('diploma', 'Diploma'),
        ('bachelor', "Bachelor's degree"),
        ('master', "Master's degree"),
        ('other', 'Other'),
    ]

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE
        )

    user_type = models.CharField(
        max_length=20,
        choices=USER_TYPES
        )

    course_of_study = models.CharField(
        max_length=150,
        blank=True
    )

    # Shown in the design as "Looking for" under career preferences.
    career_interest = models.CharField(
        max_length=150,
        blank=True
    )

    university = models.CharField(max_length=150, blank=True)
    location = models.CharField(max_length=120, blank=True)
    headline = models.CharField(max_length=150, blank=True)
    about = models.TextField(blank=True, max_length=1500)
    avatar = models.ImageField(upload_to=avatar_upload_path, blank=True)
    graduation_year = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(1980), MaxValueValidator(2100)],
    )
    degree_level = models.CharField(max_length=20, choices=DEGREE_LEVELS, blank=True)
    education_start = models.DateField(null=True, blank=True)
    education_end = models.DateField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    def __str__(self):
        return self.user.username

    @property
    def display_name(self):
        return self.user.get_full_name() or self.user.username

    @property
    def first_name(self):
        return self.user.first_name or self.user.username

    @property
    def initials(self):
        parts = self.display_name.split()
        if len(parts) >= 2:
            return (parts[0][0] + parts[-1][0]).upper()
        return self.display_name[:2].upper()

    @property
    def is_final_year(self):
        if self.user_type != 'student' or not self.graduation_year:
            return False
        this_year = timezone.localdate().year
        return self.graduation_year in (this_year, this_year + 1)

    @property
    def current_cv(self):
        return self.cvs.filter(is_current=True).first()


class CareerPreference(models.Model):
    """What the user is looking for. Feeds the 'role preferences' score."""

    profile = models.OneToOneField(
        UserProfile, on_delete=models.CASCADE, related_name='preferences'
    )
    opportunity_types = models.JSONField(default=list, blank=True)
    work_styles = models.JSONField(default=list, blank=True)
    preferred_locations = models.CharField(
        max_length=200, blank=True,
        help_text='Comma-separated, e.g. "Nairobi, Mombasa"',
    )
    available_from = models.DateField(null=True, blank=True)
    portfolio_url = models.URLField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def location_list(self):
        return [p.strip() for p in self.preferred_locations.split(',') if p.strip()]

    def work_style_labels(self):
        labels = dict(WORK_STYLES)
        return [labels[w] for w in self.work_styles if w in labels]

    def opportunity_type_labels(self):
        labels = dict(OPPORTUNITY_TYPES)
        return [labels[t] for t in self.opportunity_types if t in labels]

    def __str__(self):
        return f'Preferences for {self.profile}'


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------

class Skill(models.Model):
    TECHNICAL = 'technical'
    SOFT = 'soft'
    SKILL_TYPES = [
        (TECHNICAL, 'Technical'),
        (SOFT, 'Soft skill'),
    ]

    name = models.CharField(max_length=100, unique=True)
    category = models.CharField(max_length=100, blank=True)
    normalized_name = models.CharField(max_length=100, blank=True, db_index=True)
    skill_type = models.CharField(max_length=20, choices=SKILL_TYPES, default=TECHNICAL)
    # Part of the controlled dictionary used for CV extraction.
    in_dictionary = models.BooleanField(default=False)

    class Meta:
        ordering = ['name']

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        self.normalized_name = normalise_skill_name(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    @classmethod
    def resolve(cls, raw_name):
        """Find a skill by name or alias (case/spacing/punctuation-insensitive)."""
        key = normalise_skill_name(raw_name)
        if not key:
            return None
        skill = cls.objects.filter(normalized_name=key).first()
        if skill:
            return skill
        alias = SkillAlias.objects.select_related('skill').filter(normalized_alias=key).first()
        return alias.skill if alias else None


class SkillAlias(models.Model):
    """Alternative spellings, e.g. 'JS' -> JavaScript, 'ReactJS' -> React."""

    skill = models.ForeignKey(Skill, on_delete=models.CASCADE, related_name='aliases')
    alias = models.CharField(max_length=100)
    normalized_alias = models.CharField(max_length=100, unique=True)

    def save(self, *args, **kwargs):
        self.normalized_alias = normalise_skill_name(self.alias)
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.alias} → {self.skill.name}'


class UserSkill(models.Model):
    PROFICIENCY_LEVELS = PROFICIENCY_LEVELS
    SOURCE_SELF = 'self'
    SOURCE_RESUME = 'resume'
    SOURCES = [
        (SOURCE_SELF, 'Self-added'),
        (SOURCE_RESUME, 'Resume'),
    ]

    profile = models.ForeignKey(
        UserProfile,
        on_delete=models.CASCADE,
        related_name='user_skills'
    )

    skill = models.ForeignKey(
        Skill,
        on_delete=models.CASCADE,
        related_name='user_skills'
    )

    # Kept in sync with proficiency_score (see save()).
    proficiency = models.CharField(
        max_length=20,
        choices=PROFICIENCY_LEVELS,
        default='beginner'
    )

    proficiency_score = models.PositiveSmallIntegerField(
        default=30,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
        help_text='Self-assessed proficiency, 1–100.',
    )

    source = models.CharField(max_length=10, choices=SOURCES, default=SOURCE_SELF)

    date_added = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['profile', 'skill'],
                name='unique_skill_per_profile'
            )
        ]

    def save(self, *args, **kwargs):
        self.proficiency = level_for_score(self.proficiency_score)
        if kwargs.get('update_fields') is not None:
            kwargs['update_fields'] = set(kwargs['update_fields']) | {'proficiency', 'updated_at'}
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.profile.user.username} - {self.skill.name}"


# ---------------------------------------------------------------------------
# CVs
# ---------------------------------------------------------------------------

class CV(models.Model):
    STATUS_UPLOADED = 'uploaded'
    STATUS_PARSED = 'parsed'
    STATUS_FAILED = 'failed'
    STATUSES = [
        (STATUS_UPLOADED, 'Uploaded'),
        (STATUS_PARSED, 'Parsed'),
        (STATUS_FAILED, 'Extraction failed'),
    ]

    profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='cvs')
    file = models.FileField(upload_to=cv_upload_path, storage=private_storage)
    original_name = models.CharField(max_length=255)
    size = models.PositiveIntegerField(default=0)
    uploaded_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=20, choices=STATUSES, default=STATUS_UPLOADED)
    extracted_text = models.TextField(blank=True)
    error_message = models.CharField(max_length=300, blank=True)
    is_current = models.BooleanField(default=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-uploaded_at']
        verbose_name = 'CV'

    def __str__(self):
        return f'{self.original_name} ({self.profile})'

    @property
    def pending_count(self):
        return self.extracted_skills.filter(status=ExtractedSkill.PENDING).count()

    @property
    def is_reviewed(self):
        return self.status == self.STATUS_PARSED and self.reviewed_at is not None


class ExtractedSkill(models.Model):
    """A skill found in a CV, awaiting the user's review."""

    PENDING = 'pending'
    ACCEPTED = 'accepted'
    REJECTED = 'rejected'
    STATUSES = [(PENDING, 'Pending'), (ACCEPTED, 'Added'), (REJECTED, 'Dismissed')]

    cv = models.ForeignKey(CV, on_delete=models.CASCADE, related_name='extracted_skills')
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE)
    matched_text = models.CharField(max_length=120)
    occurrences = models.PositiveSmallIntegerField(default=1)
    context = models.CharField(max_length=240, blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default=PENDING)
    already_in_profile = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['cv', 'skill'], name='unique_skill_per_cv'),
        ]
        ordering = ['-occurrences', 'skill__name']

    def __str__(self):
        return f'{self.skill} in {self.cv}'


# ---------------------------------------------------------------------------
# Employers and opportunities
# ---------------------------------------------------------------------------

class Employer(models.Model):
    user = models.OneToOneField(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='employer'
    )
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    website = models.URLField(blank=True)
    location = models.CharField(max_length=120, blank=True)
    brand_colour = models.CharField(
        max_length=7, default='#8B5CF6',
        help_text='Hex colour for the logo tile, e.g. #8B5CF6',
    )
    is_sample = models.BooleanField(
        default=False, help_text='Fictional organisation used for demonstration.'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def initial(self):
        return (self.name[:1] or '?').upper()


class OpportunityQuerySet(models.QuerySet):
    def active(self):
        today = timezone.localdate()
        return self.filter(is_active=True).filter(
            models.Q(deadline__isnull=True) | models.Q(deadline__gte=today)
        )


class Opportunity(models.Model):
    employer = models.ForeignKey(Employer, on_delete=models.CASCADE, related_name='opportunities')
    title = models.CharField(max_length=150)
    opportunity_type = models.CharField(max_length=20, choices=OPPORTUNITY_TYPES)
    work_style = models.CharField(max_length=10, choices=WORK_STYLES)
    location = models.CharField(max_length=120, help_text='City, or "Kenya" for remote roles')
    pay = models.CharField(max_length=80, blank=True, help_text='e.g. "KES 40,000–50,000 / month"')
    duration = models.CharField(max_length=60, blank=True, help_text='e.g. "12 weeks"')
    start_date = models.DateField(null=True, blank=True)
    start_label = models.CharField(max_length=40, blank=True, help_text='e.g. "January 2027"')
    open_to = models.CharField(
        max_length=120, blank=True, help_text='e.g. "Open to 2026 and 2027 graduates"'
    )
    eligible_user_types = models.JSONField(
        default=list, blank=True,
        help_text='Subset of ["student", "graduate"]; empty means everyone.',
    )
    summary = models.CharField(max_length=300, blank=True)
    description = models.TextField()
    responsibilities = models.TextField(blank=True, help_text='One per line')
    application_url = models.URLField(blank=True)
    application_instructions = models.TextField(blank=True)
    deadline = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_sample = models.BooleanField(default=False)
    posted_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    skills = models.ManyToManyField(Skill, through='OpportunitySkill', related_name='opportunities')

    objects = OpportunityQuerySet.as_manager()

    class Meta:
        ordering = ['-posted_at']
        verbose_name_plural = 'opportunities'

    def __str__(self):
        return f'{self.title} · {self.employer}'

    def responsibility_list(self):
        return [line.strip(' -•\t') for line in self.responsibilities.splitlines() if line.strip()]

    @property
    def location_display(self):
        return f'{self.location} · {self.get_work_style_display()}'


class OpportunitySkill(models.Model):
    REQUIRED = 'required'
    PREFERRED = 'preferred'
    IMPORTANCE = [(REQUIRED, 'Required'), (PREFERRED, 'Nice-to-have')]

    opportunity = models.ForeignKey(
        Opportunity, on_delete=models.CASCADE, related_name='skill_requirements'
    )
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE, related_name='requirements')
    importance = models.CharField(max_length=10, choices=IMPORTANCE, default=REQUIRED)
    target_score = models.PositiveSmallIntegerField(
        default=60, validators=[MinValueValidator(1), MaxValueValidator(100)],
        help_text='Proficiency the role expects, 1–100.',
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['opportunity', 'skill'], name='unique_skill_per_opportunity'
            ),
        ]
        ordering = ['importance', '-target_score']

    def __str__(self):
        return f'{self.opportunity.title}: {self.skill} ({self.importance})'


class SavedOpportunity(models.Model):
    profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='saved')
    opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE, related_name='saves')
    saved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['profile', 'opportunity'], name='unique_saved_opportunity'
            ),
        ]
        ordering = ['-saved_at']


class Application(models.Model):
    """Records that a user started an application (on the employer's site)."""

    STATUSES = [
        ('started', 'Started on employer site'),
        ('submitted', 'Submitted'),
        ('shortlisted', 'Shortlisted'),
        ('unsuccessful', 'Unsuccessful'),
    ]
    profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='applications')
    opportunity = models.ForeignKey(
        Opportunity, on_delete=models.CASCADE, related_name='applications'
    )
    status = models.CharField(max_length=20, choices=STATUSES, default='started')
    match_score = models.PositiveSmallIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['profile', 'opportunity'], name='unique_application'
            ),
        ]


class MatchResult(models.Model):
    """Stored output of the matching engine (the ERD's Recommendation entity).

    Results are recalculated whenever they are viewed, and the latest
    calculation is kept here so it can be audited and shown to employers.
    """

    profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='matches')
    opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE, related_name='matches')
    score = models.PositiveSmallIntegerField(null=True, blank=True)
    required_coverage = models.PositiveSmallIntegerField(null=True, blank=True)
    technical_score = models.PositiveSmallIntegerField(null=True, blank=True)
    soft_score = models.PositiveSmallIntegerField(null=True, blank=True)
    preference_score = models.PositiveSmallIntegerField(null=True, blank=True)
    text_similarity = models.FloatField(null=True, blank=True)
    details = models.JSONField(default=dict, blank=True)
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['profile', 'opportunity'], name='unique_match'),
        ]
        ordering = ['-score']


class LearningResource(models.Model):
    RESOURCE_TYPES = [
        ('course', 'Course'),
        ('guided_project', 'Guided project'),
        ('documentation', 'Documentation'),
        ('practice', 'Practice'),
    ]
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE, related_name='resources')
    title = models.CharField(max_length=150)
    provider = models.CharField(max_length=120)
    resource_type = models.CharField(max_length=20, choices=RESOURCE_TYPES, default='course')
    url = models.URLField()
    hours = models.DecimalField(max_digits=4, decimal_places=1, default=1)
    cost = models.CharField(max_length=30, default='Free')
    level = models.CharField(max_length=20, choices=PROFICIENCY_LEVELS, default='beginner')
    description = models.CharField(max_length=300, blank=True)
    practice_task = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['skill__name', 'hours']

    def __str__(self):
        return f'{self.title} ({self.skill})'

    @property
    def hours_label(self):
        h = float(self.hours)
        return f'{int(h) if h.is_integer() else h}-hour'

    @property
    def hours_display(self):
        h = float(self.hours)
        value = int(h) if h.is_integer() else h
        return f'{value} hour' + ('' if value == 1 else 's')
