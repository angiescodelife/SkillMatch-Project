"""Backfill new skill fields for records created before migration 0004.

* Skill.normalized_name is computed from the existing name.
* UserSkill.proficiency_score is set from the existing level using the
  mid-points of the design's bands (beginner 30, intermediate 60,
  advanced 85). Existing levels are therefore preserved exactly.
* Every UserProfile gets an empty CareerPreference row.

No rows are deleted. The reverse operation is a no-op.
"""
import re

from django.db import migrations

DEFAULT_SCORE = {'beginner': 30, 'intermediate': 60, 'advanced': 85}
SOFT_HINTS = {
    'communication', 'teamwork', 'leadership', 'problemsolving', 'adaptability',
    'timemanagement', 'criticalthinking', 'collaboration', 'creativity',
    'publicspeaking', 'presentation', 'presentationskills', 'attentiontodetail',
}


def normalise(value):
    value = (value or '').strip().lower().replace('&', 'and')
    return re.sub(r'[^a-z0-9+#]+', '', value)


def forwards(apps, schema_editor):
    Skill = apps.get_model('core', 'Skill')
    UserSkill = apps.get_model('core', 'UserSkill')
    UserProfile = apps.get_model('core', 'UserProfile')
    CareerPreference = apps.get_model('core', 'CareerPreference')

    for skill in Skill.objects.all():
        skill.normalized_name = normalise(skill.name)
        if skill.normalized_name in SOFT_HINTS or 'soft' in (skill.category or '').lower():
            skill.skill_type = 'soft'
        skill.save(update_fields=['normalized_name', 'skill_type'])

    for us in UserSkill.objects.all():
        us.proficiency_score = DEFAULT_SCORE.get(us.proficiency, 30)
        us.save(update_fields=['proficiency_score'])

    for profile in UserProfile.objects.all():
        CareerPreference.objects.get_or_create(profile=profile)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_profile_skills_opportunities_matching'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
