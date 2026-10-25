from pathlib import Path

from django import forms
from django.conf import settings
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.utils.text import slugify

from .models import (
    OPPORTUNITY_TYPES, WORK_STYLES, CareerPreference, Skill, UserProfile,
)
from .services.cv_extraction import ALLOWED_EXTENSIONS, looks_like_valid_file


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

class LoginForm(AuthenticationForm):
    username = forms.CharField(
        label='Email address',
        widget=forms.TextInput(attrs={
            'autofocus': True, 'autocomplete': 'username',
            'placeholder': 'you@university.ac.ke',
        }),
        help_text='You can also use the username you registered with.',
    )
    password = forms.CharField(
        label='Password', strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'current-password',
                                          'placeholder': 'Your password'}),
    )
    remember_me = forms.BooleanField(required=False, initial=True, label='Keep me signed in')

    error_messages = {
        'invalid_login': 'That email and password don\'t match an account. Please try again.',
        'inactive': 'This account is inactive.',
    }


class RegistrationForm(forms.Form):
    full_name = forms.CharField(
        max_length=150, label='Full name',
        widget=forms.TextInput(attrs={'autocomplete': 'name', 'placeholder': 'Your full name'}),
    )
    email = forms.EmailField(
        label='Email address',
        widget=forms.EmailInput(attrs={'autocomplete': 'email', 'placeholder': 'you@university.ac.ke'}),
    )
    university = forms.CharField(
        max_length=150, label='University',
        widget=forms.TextInput(attrs={'placeholder': 'e.g. Riara University'}),
    )
    password = forms.CharField(
        label='Create password', strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password',
                                          'placeholder': 'Create a password'}),
    )
    user_type = forms.ChoiceField(
        label="I'm currently a…",
        choices=[('student', 'University student'), ('graduate', 'Recent graduate')],
        initial='student', widget=forms.RadioSelect,
    )
    agree_terms = forms.BooleanField(
        label='I agree to the Terms of Service and Privacy Policy.',
        error_messages={'required': 'Please accept the Terms of Service and Privacy Policy.'},
    )

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists() or \
                User.objects.filter(username__iexact=email).exists():
            raise forms.ValidationError('An account with this email already exists. Try logging in.')
        return email

    def clean_full_name(self):
        name = ' '.join(self.cleaned_data['full_name'].split())
        if len(name) < 2:
            raise forms.ValidationError('Please enter your name.')
        return name

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get('password')
        if password:
            first, _, last = (cleaned.get('full_name') or '').partition(' ')
            temp_user = User(username=cleaned.get('email', ''), email=cleaned.get('email', ''),
                             first_name=first, last_name=last)
            try:
                password_validation.validate_password(password, temp_user)
            except forms.ValidationError as exc:
                self.add_error('password', exc)
        return cleaned

    def save(self):
        data = self.cleaned_data
        first, _, last = data['full_name'].partition(' ')
        username = data['email'][:150]
        if User.objects.filter(username__iexact=username).exists():  # pragma: no cover
            username = f"{slugify(data['full_name'])[:120]}-{User.objects.count() + 1}"
        user = User.objects.create_user(
            username=username, email=data['email'], password=data['password'],
            first_name=first[:150], last_name=last[:150],
        )
        profile = UserProfile.objects.create(
            user=user, user_type=data['user_type'], university=data['university'],
        )
        CareerPreference.objects.create(profile=profile)
        return user


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

def _year_choices():
    from datetime import date

    this_year = date.today().year
    return [('', 'Select year')] + [(y, y) for y in range(this_year - 6, this_year + 7)]


class ProfileForm(forms.ModelForm):
    full_name = forms.CharField(max_length=150, label='Full name')
    email = forms.EmailField(label='University email')
    graduation_year = forms.TypedChoiceField(
        choices=_year_choices, coerce=int, empty_value=None, required=False,
        label='Graduation year',
    )

    class Meta:
        model = UserProfile
        fields = [
            'location', 'headline', 'about', 'avatar',
            'university', 'course_of_study', 'degree_level', 'graduation_year',
            'education_start', 'education_end',
        ]
        widgets = {
            'location': forms.TextInput(attrs={'placeholder': 'e.g. Nairobi, Kenya'}),
            'headline': forms.TextInput(attrs={'placeholder': 'e.g. CS student · Aspiring backend engineer'}),
            'about': forms.Textarea(attrs={'rows': 3, 'placeholder': 'A few lines about you and what you enjoy building.'}),
            'avatar': forms.FileInput(attrs={'accept': 'image/png,image/jpeg'}),
            'university': forms.TextInput(attrs={'placeholder': 'e.g. Riara University'}),
            'course_of_study': forms.TextInput(attrs={'placeholder': 'e.g. BSc Computer Science'}),
            'education_start': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'education_end': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        }
        labels = {
            'course_of_study': 'Course of study',
            'degree_level': 'Degree level',
            'about': 'About you',
            'education_start': 'Started',
            'education_end': 'Expected completion',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        user = self.instance.user
        self.fields['full_name'].initial = user.get_full_name()
        self.fields['email'].initial = user.email
        self.fields['degree_level'].choices = [('', 'Select degree level')] + list(
            UserProfile.DEGREE_LEVELS)

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.user_id).exists():
            raise forms.ValidationError('Another account already uses this email.')
        return email

    def clean_avatar(self):
        avatar = self.cleaned_data.get('avatar')
        if avatar and hasattr(avatar, 'content_type'):
            if avatar.size > settings.AVATAR_MAX_UPLOAD_SIZE:
                raise forms.ValidationError('Photos must be 5 MB or smaller.')
            if Path(avatar.name).suffix.lower() not in {'.jpg', '.jpeg', '.png'}:
                raise forms.ValidationError('Please upload a JPG or PNG image.')
        return avatar

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get('education_start'), cleaned.get('education_end')
        if start and end and end < start:
            self.add_error('education_end', 'Completion date must be after the start date.')
        return cleaned

    def save(self, commit=True):
        profile = super().save(commit=False)
        user = profile.user
        first, _, last = ' '.join(self.cleaned_data['full_name'].split()).partition(' ')
        user.first_name, user.last_name = first[:150], last[:150]
        old_email = user.email
        user.email = self.cleaned_data['email']
        # Keep email-as-username accounts in step with the new email.
        if user.username.lower() == (old_email or '').lower() and \
                not User.objects.filter(username__iexact=user.email).exclude(pk=user.pk).exists():
            user.username = user.email
        if commit:
            user.save()
            profile.save()
        return profile


class CareerPreferenceForm(forms.ModelForm):
    looking_for = forms.CharField(
        max_length=150, required=False, label='Looking for',
        widget=forms.TextInput(attrs={'placeholder': 'e.g. Backend engineering internships'}),
    )
    opportunity_types = forms.MultipleChoiceField(
        choices=OPPORTUNITY_TYPES, required=False, widget=forms.CheckboxSelectMultiple,
        label='Opportunity types',
    )
    work_styles = forms.MultipleChoiceField(
        choices=WORK_STYLES, required=False, widget=forms.CheckboxSelectMultiple,
        label='Work style',
    )

    class Meta:
        model = CareerPreference
        fields = ['opportunity_types', 'work_styles', 'preferred_locations', 'available_from',
                  'portfolio_url']
        widgets = {
            'preferred_locations': forms.TextInput(attrs={'placeholder': 'e.g. Nairobi, Mombasa'}),
            'available_from': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'portfolio_url': forms.URLInput(attrs={'placeholder': 'https://github.com/your-name'}),
        }
        labels = {
            'preferred_locations': 'Preferred locations',
            'available_from': 'Available from',
            'portfolio_url': 'Project portfolio link',
        }
        help_texts = {'preferred_locations': 'Separate locations with commas.'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['looking_for'].initial = self.instance.profile.career_interest

    def save(self, commit=True):
        prefs = super().save(commit=False)
        prefs.profile.career_interest = self.cleaned_data.get('looking_for', '')
        if commit:
            prefs.save()
            prefs.profile.save(update_fields=['career_interest', 'updated_at'])
        return prefs


class CVUploadForm(forms.Form):
    file = forms.FileField(label='Resume', widget=forms.FileInput(attrs={
        'accept': '.pdf,.docx,application/pdf,'
                  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    }))

    def clean_file(self):
        f = self.cleaned_data['file']
        ext = Path(f.name).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise forms.ValidationError('Please upload a PDF or DOCX file.')
        if f.size > settings.CV_MAX_UPLOAD_SIZE:
            raise forms.ValidationError('Your resume must be 10 MB or smaller.')
        if f.size == 0:
            raise forms.ValidationError('This file is empty.')
        head = f.read()
        f.seek(0)
        if not looks_like_valid_file(head, ext):
            raise forms.ValidationError(
                "This file doesn't look like a valid PDF or Word document. Please re-save it and try again."
            )
        return f


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------

class SkillForm(forms.Form):
    name = forms.CharField(
        max_length=100, label='Skill name',
        widget=forms.TextInput(attrs={'placeholder': 'e.g. Python, SQL, Communication',
                                      'list': 'skill-dictionary', 'autocomplete': 'off'}),
    )
    skill_type = forms.ChoiceField(
        choices=Skill.SKILL_TYPES, initial=Skill.TECHNICAL, label='Type', required=False,
    )
    category = forms.CharField(
        max_length=100, required=False, label='Category',
        widget=forms.TextInput(attrs={'placeholder': 'e.g. Frontend, Data, Soft skill'}),
    )
    proficiency_score = forms.IntegerField(
        min_value=1, max_value=100, initial=50, label='Proficiency',
        widget=forms.NumberInput(attrs={'type': 'range', 'min': 1, 'max': 100, 'step': 1}),
    )

    def clean_name(self):
        name = ' '.join(self.cleaned_data['name'].split())
        if not any(ch.isalnum() for ch in name):
            raise forms.ValidationError('Please enter a skill name.')
        return name


# Backwards-compatible name used by the original skills view.
AddSkillForm = SkillForm


class SkillLevelForm(forms.Form):
    proficiency_score = forms.IntegerField(min_value=1, max_value=100)
