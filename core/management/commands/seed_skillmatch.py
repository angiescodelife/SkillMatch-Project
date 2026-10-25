from datetime import date, timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core import seed_data
from core.models import (
    CareerPreference, Employer, LearningResource, Opportunity, OpportunitySkill, Skill,
    SkillAlias, UserProfile, UserSkill, normalise_skill_name,
)

DEMO_EMAIL = 'demo.student@skillmatch.test'
DEMO_PASSWORD = 'SkillMatch!2026'


class Command(BaseCommand):
    help = ('Load the skill dictionary, learning resources and labelled sample opportunities. '
            'Safe to run more than once.')

    def add_arguments(self, parser):
        parser.add_argument('--no-opportunities', action='store_true',
                            help='Only load skills and learning resources.')
        parser.add_argument('--demo', action='store_true',
                            help=f'Also create a demo student account ({DEMO_EMAIL}).')

    @transaction.atomic
    def handle(self, *args, **options):
        skills = self.load_skills()
        self.load_resources(skills)
        if not options['no_opportunities']:
            self.load_opportunities(skills)
        if options['demo']:
            self.create_demo(skills)
        self.stdout.write(self.style.SUCCESS('SkillMatch seed data loaded.'))

    # ------------------------------------------------------------------
    def load_skills(self):
        skills = {}
        created = 0
        for name, skill_type, category, aliases in seed_data.SKILLS:
            skill = Skill.resolve(name)
            if skill is None:
                skill = Skill.objects.create(
                    name=name, skill_type=skill_type, category=category, in_dictionary=True
                )
                created += 1
            else:
                # Tidy capitalisation of user-typed names ("python" -> "Python").
                if skill.name != name and skill.name.lower() == name.lower() \
                        and not Skill.objects.filter(name=name).exists():
                    skill.name = name
                skill.skill_type = skill_type
                skill.category = skill.category or category
                skill.in_dictionary = True
                skill.save()
            skills[name] = skill
            for alias in aliases:
                key = normalise_skill_name(alias)
                if key == skill.normalized_name:
                    continue
                if Skill.objects.filter(normalized_name=key).exclude(pk=skill.pk).exists():
                    continue  # a real skill already uses this name
                SkillAlias.objects.get_or_create(
                    normalized_alias=key, defaults={'alias': alias, 'skill': skill}
                )
        self.stdout.write(f'  Skills: {len(skills)} in dictionary ({created} new)')
        return skills

    def load_resources(self, skills):
        count = 0
        for (skill_name, title, provider, rtype, url, hours, level, desc, task) in seed_data.RESOURCES:
            LearningResource.objects.update_or_create(
                skill=skills[skill_name], title=title,
                defaults=dict(provider=provider, resource_type=rtype, url=url, hours=hours,
                              level=level, description=desc, practice_task=task, cost='Free'),
            )
            count += 1
        self.stdout.write(f'  Learning resources: {count}')

    def load_opportunities(self, skills):
        employers = {}
        for name, colour, location, desc in seed_data.EMPLOYERS:
            employers[name], _ = Employer.objects.update_or_create(
                name=name, is_sample=True,
                defaults=dict(brand_colour=colour, location=location, description=desc),
            )
        now = timezone.now()
        for item in seed_data.OPPORTUNITIES:
            start = date.fromisoformat(item['start'])
            opp, _ = Opportunity.objects.update_or_create(
                employer=employers[item['employer']], title=item['title'], is_sample=True,
                defaults=dict(
                    opportunity_type=item['type'], work_style=item['style'],
                    location=item['location'], pay=item['pay'], duration=item['duration'],
                    start_date=start, start_label=start.strftime('%B %Y'),
                    open_to=item['open_to'], eligible_user_types=item['eligible'],
                    summary=item['summary'], description=item['description'],
                    responsibilities=item['responsibilities'],
                    application_url='',
                    application_instructions=(
                        'This is a fictional sample opportunity used to demonstrate SkillMatch. '
                        'There is no real application to submit.'
                    ),
                    posted_at=now - timedelta(days=item['days_ago']),
                    is_active=True,
                ),
            )
            keep = []
            for skill_name, importance, target in item['skills']:
                req, _ = OpportunitySkill.objects.update_or_create(
                    opportunity=opp, skill=skills[skill_name],
                    defaults=dict(importance=importance, target_score=target),
                )
                keep.append(req.pk)
            opp.skill_requirements.exclude(pk__in=keep).delete()
        self.stdout.write(f'  Sample opportunities: {len(seed_data.OPPORTUNITIES)} '
                          f'from {len(employers)} fictional employers')

    def create_demo(self, skills):
        user = User.objects.filter(username=DEMO_EMAIL).first()
        if user is None:
            user = User.objects.create_user(
                username=DEMO_EMAIL, email=DEMO_EMAIL, password=DEMO_PASSWORD,
                first_name='Wanjiru', last_name='Kamau',
            )
        profile, _ = UserProfile.objects.get_or_create(
            user=user, defaults={'user_type': 'student'}
        )
        profile.course_of_study = 'BSc Computer Science'
        profile.career_interest = 'Frontend engineering internships'
        profile.university = 'Riara University'
        profile.location = 'Nairobi, Kenya'
        profile.headline = 'CS student · Aspiring frontend engineer'
        profile.about = ('Final-year computer science student who loves building thoughtful web '
                         'experiences with React and TypeScript.')
        profile.graduation_year = 2027
        profile.degree_level = 'bachelor'
        profile.save()
        prefs, _ = CareerPreference.objects.get_or_create(profile=profile)
        prefs.opportunity_types = ['internship']
        prefs.work_styles = ['hybrid', 'remote']
        prefs.preferred_locations = 'Nairobi'
        prefs.save()
        demo_skills = [
            ('React', 80, 'resume'), ('JavaScript', 85, 'resume'), ('TypeScript', 65, 'resume'),
            ('HTML / CSS', 90, 'resume'), ('Git', 75, 'resume'), ('Python', 70, 'resume'),
            ('SQL', 60, 'resume'), ('Figma', 55, 'self'), ('Communication', 85, 'resume'),
            ('Teamwork', 90, 'resume'), ('Problem solving', 80, 'resume'), ('Adaptability', 85, 'self'),
        ]
        for name, score, source in demo_skills:
            UserSkill.objects.update_or_create(
                profile=profile, skill=skills[name],
                defaults={'proficiency_score': score, 'source': source},
            )
        self.stdout.write(f'  Demo student: {DEMO_EMAIL} / {DEMO_PASSWORD}')
