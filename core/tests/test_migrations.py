"""Checks that existing (pre-SkillMatch-upgrade) data survives the new migrations."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class LegacyDataMigrationTests(TransactionTestCase):
    migrate_from = [('core', '0003_skill_userskill')]
    migrate_to = [('core', '0005_backfill_skill_data')]

    def test_existing_skills_and_levels_are_preserved(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        User = old_apps.get_model('auth', 'User')
        UserProfile = old_apps.get_model('core', 'UserProfile')
        Skill = old_apps.get_model('core', 'Skill')
        UserSkill = old_apps.get_model('core', 'UserSkill')

        user = User.objects.create(username='angela')
        profile = UserProfile.objects.create(user=user, user_type='student',
                                             course_of_study='CS', career_interest='Backend')
        levels = {'Python': 'advanced', 'SQL': 'intermediate', 'Teamwork': 'beginner'}
        for name, level in levels.items():
            UserSkill.objects.create(profile=profile, skill=Skill.objects.create(name=name),
                                     proficiency=level)

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(self.migrate_to)
        new_apps = executor.loader.project_state(self.migrate_to).apps
        UserSkill = new_apps.get_model('core', 'UserSkill')
        UserProfile = new_apps.get_model('core', 'UserProfile')
        CareerPreference = new_apps.get_model('core', 'CareerPreference')

        rows = {us.skill.name: us for us in UserSkill.objects.select_related('skill')}
        self.assertEqual({k: v.proficiency for k, v in rows.items()}, levels)
        self.assertEqual({k: v.proficiency_score for k, v in rows.items()},
                         {'Python': 85, 'SQL': 60, 'Teamwork': 30})
        self.assertEqual(rows['Teamwork'].skill.skill_type, 'soft')
        self.assertEqual(rows['SQL'].skill.normalized_name, 'sql')
        p = UserProfile.objects.get()
        self.assertEqual((p.course_of_study, p.career_interest), ('CS', 'Backend'))
        self.assertTrue(CareerPreference.objects.filter(profile=p).exists())

        # Leave the database fully migrated for other tests.
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
