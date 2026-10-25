from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from core.models import (
    CV, Application, ExtractedSkill, MatchResult, Opportunity, SavedOpportunity, Skill,
    UserProfile, UserSkill,
)
from core.services import recommendations as rec

from .helpers import TempMediaMixin, give, make_docx, make_pdf, make_user, opportunity, skill

PASSWORD = 'Str0ng!Passw0rd'


class AuthTests(TestCase):
    def test_login_page_renders(self):
        # Previously raised TemplateDoesNotExist (template was in the wrong folder).
        response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Your future is waiting.')

    def test_login_with_email_and_with_legacy_username(self):
        make_user('new@example.com', PASSWORD)
        legacy = User.objects.create_user('legacyuser', '', PASSWORD)
        UserProfile.objects.create(user=legacy, user_type='graduate')

        r = self.client.post(reverse('login'), {'username': 'NEW@example.com', 'password': PASSWORD,
                                                'remember_me': 'on'})
        self.assertRedirects(r, reverse('dashboard'))
        self.client.logout()
        r = self.client.post(reverse('login'), {'username': 'legacyuser', 'password': PASSWORD})
        self.assertRedirects(r, reverse('dashboard'))
        self.assertTrue(self.client.session.get_expire_at_browser_close())

    def test_wrong_password_shows_error(self):
        make_user('a@example.com', PASSWORD)
        r = self.client.post(reverse('login'), {'username': 'a@example.com', 'password': 'nope'})
        self.assertContains(r, "don&#x27;t match an account")

    def test_login_ignores_unsafe_next(self):
        make_user('a@example.com', PASSWORD)
        r = self.client.post(reverse('login') + '?next=https://evil.example/',
                             {'username': 'a@example.com', 'password': PASSWORD,
                              'next': 'https://evil.example/'})
        self.assertRedirects(r, reverse('dashboard'))

    def test_registration_creates_user_profile_and_preferences(self):
        r = self.client.post(reverse('register'), {
            'full_name': 'Amina Otieno', 'email': 'Amina@Example.com', 'university': 'Riara University',
            'password': PASSWORD, 'user_type': 'graduate', 'agree_terms': 'on',
        })
        self.assertRedirects(r, reverse('profile'))
        user = User.objects.get(email='amina@example.com')
        self.assertEqual(user.get_full_name(), 'Amina Otieno')
        self.assertEqual(user.userprofile.user_type, 'graduate')
        self.assertEqual(user.userprofile.university, 'Riara University')
        self.assertTrue(hasattr(user.userprofile, 'preferences'))

    def test_registration_validation(self):
        make_user('taken@example.com', PASSWORD)
        r = self.client.post(reverse('register'), {
            'full_name': 'X Y', 'email': 'taken@example.com', 'university': 'U',
            'password': '123', 'user_type': 'student',
        })
        self.assertEqual(r.status_code, 200)
        form = r.context['form']
        self.assertIn('email', form.errors)
        self.assertIn('password', form.errors)
        self.assertIn('agree_terms', form.errors)

    def test_logout_requires_post(self):
        user, _ = make_user()
        self.client.force_login(user)
        self.client.get(reverse('logout'))
        self.assertIn('_auth_user_id', self.client.session)
        self.client.post(reverse('logout'))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_private_pages_require_login(self):
        for name in ['dashboard', 'profile', 'skills', 'opportunities', 'skill_gap', 'saved',
                     'career_preferences', 'account_settings', 'search']:
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 302, name)
            self.assertIn(reverse('login'), r['Location'])

    def test_public_pages(self):
        for name in ['home', 'register', 'help', 'privacy', 'terms', 'password_reset']:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)


class SkillViewTests(TestCase):
    def setUp(self):
        self.user, self.profile = make_user()
        self.client.force_login(self.user)
        self.react = skill('React', aliases=['ReactJS'])

    def test_add_skill_resolves_alias_and_prevents_duplicates(self):
        self.client.post(reverse('skills'), {'name': 'reactjs', 'proficiency_score': 70})
        self.client.post(reverse('skills'), {'name': 'React', 'proficiency_score': 85})
        self.assertEqual(self.profile.user_skills.count(), 1)
        us = self.profile.user_skills.get()
        self.assertEqual((us.skill, us.proficiency_score, us.proficiency), (self.react, 85, 'advanced'))

    def test_new_skill_created_with_type(self):
        self.client.post(reverse('skills'), {'name': 'Negotiation', 'skill_type': 'soft',
                                             'proficiency_score': 45})
        s = Skill.objects.get(name='Negotiation')
        self.assertEqual(s.skill_type, 'soft')
        self.assertEqual(self.profile.user_skills.get(skill=s).proficiency, 'intermediate')

    def test_legacy_level_field_still_accepted(self):
        self.client.post(reverse('skills'), {'name': 'React', 'proficiency': 'advanced'})
        self.assertEqual(self.profile.user_skills.get().proficiency_score, 85)

    def test_invalid_score_rejected(self):
        r = self.client.post(reverse('skills'), {'name': 'React', 'proficiency_score': 500})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.profile.user_skills.count(), 0)

    def test_update_and_remove_are_scoped_to_owner(self):
        other, other_profile = make_user('other@example.com')
        theirs = give(other_profile, self.react, 50)
        r = self.client.post(reverse('skill_update', args=[theirs.pk]), {'proficiency_score': 99})
        self.assertEqual(r.status_code, 404)
        self.client.post(reverse('skills'), {'action': 'remove', 'user_skill_id': theirs.pk})
        theirs.refresh_from_db()
        self.assertEqual(theirs.proficiency_score, 50)

        mine = give(self.profile, self.react, 50)
        self.client.post(reverse('skill_update', args=[mine.pk]), {'proficiency_score': 90})
        mine.refresh_from_db()
        self.assertEqual(mine.proficiency, 'advanced')
        self.client.post(reverse('skills'), {'action': 'remove', 'user_skill_id': mine.pk})
        self.assertFalse(UserSkill.objects.filter(pk=mine.pk).exists())

    def test_skills_page_lists_technical_and_soft(self):
        give(self.profile, self.react, 80)
        give(self.profile, skill('Teamwork', skill_type='soft'), 60)
        r = self.client.get(reverse('skills'))
        self.assertEqual([s.skill.name for s in r.context['technical']], ['React'])
        self.assertEqual([s.skill.name for s in r.context['soft']], ['Teamwork'])


class CVViewTests(TempMediaMixin, TestCase):
    def setUp(self):
        self.user, self.profile = make_user()
        self.client.force_login(self.user)
        skill('Python')
        skill('Django')
        skill('Teamwork', skill_type='soft')

    def upload(self, data, name='resume.pdf'):
        return self.client.post(reverse('cv_upload'), {'file': SimpleUploadedFile(name, data)})

    def test_upload_review_and_accept(self):
        r = self.upload(make_pdf(['Final-year student. Python, Django and teamwork on group projects.']))
        cv = CV.objects.get(profile=self.profile)
        self.assertRedirects(r, reverse('cv_review', args=[cv.pk]))
        self.assertNotIn(self._media, cv.file.path)  # stored outside public media
        items = {e.skill.name: e for e in cv.extracted_skills.all()}
        self.assertEqual(set(items), {'Python', 'Django', 'Teamwork'})
        self.assertEqual(self.profile.user_skills.count(), 0)  # nothing added before review

        post = {f'keep_{items["Python"].pk}': '1', f'score_{items["Python"].pk}': '75',
                f'keep_{items["Teamwork"].pk}': '1', f'score_{items["Teamwork"].pk}': '60'}
        r = self.client.post(reverse('cv_review', args=[cv.pk]), post)
        self.assertRedirects(r, reverse('skills'))
        skills = {us.skill.name: us for us in self.profile.user_skills.select_related('skill')}
        self.assertEqual(set(skills), {'Python', 'Teamwork'})
        self.assertEqual(skills['Python'].source, UserSkill.SOURCE_RESUME)
        self.assertEqual(skills['Python'].proficiency_score, 75)
        cv.refresh_from_db()
        self.assertTrue(cv.is_reviewed)
        self.assertEqual(cv.extracted_skills.get(skill__name='Django').status, ExtractedSkill.REJECTED)

    def test_docx_upload(self):
        self.upload(make_docx(['Experienced with Django and Python across many university projects.']),
                    'resume.docx')
        cv = CV.objects.get(profile=self.profile)
        self.assertEqual(cv.status, CV.STATUS_PARSED)
        self.assertEqual(cv.extracted_skills.count(), 2)

    def test_rejects_wrong_type_size_and_fake_files(self):
        self.upload(b'hello', 'resume.txt')
        self.upload(b'not really a pdf', 'resume.pdf')
        with self.settings(CV_MAX_UPLOAD_SIZE=10):
            self.upload(make_pdf(['Python developer with Django experience and more text here.']))
        self.assertEqual(CV.objects.count(), 0)

    def test_unreadable_pdf_shows_error(self):
        r = self.upload(make_pdf([]), 'scan.pdf')
        self.assertRedirects(r, reverse('profile'))
        cv = CV.objects.get(profile=self.profile)
        self.assertEqual(cv.status, CV.STATUS_FAILED)
        page = self.client.get(reverse('profile'))
        self.assertContains(page, 'readable text')

    def test_replacing_cv_deletes_old_file(self):
        self.upload(make_pdf(['First resume with Python skills and a lot of other text.']))
        first = CV.objects.get()
        path = first.file.path
        self.upload(make_pdf(['Second resume with Django skills and a lot of other text.']))
        self.assertEqual(CV.objects.count(), 1)
        import os
        self.assertFalse(os.path.exists(path))

    def test_cv_access_is_owner_only(self):
        self.upload(make_pdf(['Python developer with Django experience and more text here.']))
        cv = CV.objects.get()
        self.assertEqual(self.client.get(reverse('cv_download', args=[cv.pk])).status_code, 200)
        other, _ = make_user('other@example.com')
        self.client.force_login(other)
        for name in ['cv_download', 'cv_review']:
            self.assertEqual(self.client.get(reverse(name, args=[cv.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('cv_delete', args=[cv.pk])).status_code, 404)
        self.assertTrue(CV.objects.filter(pk=cv.pk).exists())

    def test_delete_cv_keeps_confirmed_skills(self):
        self.upload(make_pdf(['Python developer with Django experience and more text here.']))
        cv = CV.objects.get()
        give(self.profile, Skill.objects.get(name='Python'), 70, 'resume')
        self.client.post(reverse('cv_delete', args=[cv.pk]))
        self.assertFalse(CV.objects.exists())
        self.assertEqual(self.profile.user_skills.count(), 1)


class ProfileViewTests(TempMediaMixin, TestCase):
    def setUp(self):
        self.user, self.profile = make_user()
        self.client.force_login(self.user)

    def test_save_profile_and_education(self):
        r = self.client.post(reverse('profile'), {
            'full_name': 'Test Person', 'email': 'new.email@example.com', 'location': 'Nairobi',
            'headline': 'CS student', 'about': 'Hello', 'university': 'Riara University',
            'course_of_study': 'BSc Computer Science', 'degree_level': 'bachelor',
            'graduation_year': '2027',
        })
        self.assertRedirects(r, reverse('profile'))
        self.user.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(self.user.email, 'new.email@example.com')
        self.assertEqual(self.user.username, 'new.email@example.com')  # email-as-username kept in step
        self.assertEqual(self.profile.graduation_year, 2027)
        completion = rec.profile_completion(self.profile)
        self.assertEqual(completion['items'][0]['done'], True)
        self.assertEqual(completion['items'][1]['done'], True)

    def test_email_must_be_unique(self):
        make_user('taken@example.com')
        r = self.client.post(reverse('profile'), {'full_name': 'A B', 'email': 'taken@example.com'})
        self.assertIn('email', r.context['form'].errors)

    def test_preferences_save(self):
        r = self.client.post(reverse('career_preferences'), {
            'looking_for': 'Backend internships', 'opportunity_types': ['internship'],
            'work_styles': ['remote', 'hybrid'], 'preferred_locations': 'Nairobi, Kisumu',
            'available_from': '2027-01-01', 'portfolio_url': 'https://github.com/example',
        })
        self.assertRedirects(r, reverse('career_preferences'))
        prefs = rec.get_preferences(self.profile)
        self.assertEqual(prefs.work_styles, ['remote', 'hybrid'])
        self.assertEqual(prefs.location_list(), ['Nairobi', 'Kisumu'])
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.career_interest, 'Backend internships')

    def test_change_password(self):
        r = self.client.post(reverse('account_settings'), {
            'old_password': PASSWORD, 'new_password1': 'An0ther!Passw0rd',
            'new_password2': 'An0ther!Passw0rd'})
        self.assertRedirects(r, reverse('account_settings'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('An0ther!Passw0rd'))

    def test_profile_created_for_users_without_one(self):
        admin = User.objects.create_superuser('admin', 'admin@example.com', PASSWORD)
        self.client.force_login(admin)
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)
        self.assertTrue(UserProfile.objects.filter(user=admin).exists())


class OpportunityViewTests(TestCase):
    def setUp(self):
        self.user, self.profile = make_user()
        self.client.force_login(self.user)
        self.react = skill('React')
        self.sql = skill('SQL')
        self.comm = skill('Communication', skill_type='soft')
        self.good = opportunity('Frontend Intern', requirements=[
            (self.react, 'required', 70), (self.comm, 'required', 60)])
        self.weak = opportunity('Data Intern', work_style='remote', opportunity_type='full_time',
                                requirements=[(self.sql, 'required', 70)])
        self.closed = opportunity('Closed Intern', is_active=False,
                                  requirements=[(self.react, 'required', 10)])

    def test_new_user_sees_empty_states(self):
        r = self.client.get(reverse('dashboard'))
        self.assertContains(r, 'find your first matches')
        r = self.client.get(reverse('opportunities'))
        self.assertEqual(r.context['tab'], 'all')
        self.assertEqual(r.context['total'], 2)  # inactive roles hidden

    def test_dashboard_scores_come_from_engine(self):
        give(self.profile, self.react, 70)
        give(self.profile, self.comm, 30)
        r = self.client.get(reverse('dashboard'))
        top = r.context['top']
        self.assertEqual(top.opportunity, self.good)
        expected = rec.match_one(self.profile, self.good).score
        self.assertEqual(top.score, expected)
        self.assertContains(r, f'{expected}%')
        # Stored for auditing / employer review
        stored = MatchResult.objects.get(profile=self.profile, opportunity=self.good)
        self.assertEqual(stored.score, expected)
        self.assertEqual(stored.details['missing_required'], [])

    def test_list_filters_and_for_you_threshold(self):
        give(self.profile, self.react, 80)
        give(self.profile, self.comm, 80)
        r = self.client.get(reverse('opportunities'))
        self.assertEqual([o.opportunity for o in r.context['outcomes']], [self.good])
        r = self.client.get(reverse('opportunities'), {'tab': 'all', 'style': 'remote'})
        self.assertEqual([o.opportunity for o in r.context['outcomes']], [self.weak])
        r = self.client.get(reverse('opportunities'), {'tab': 'all', 'min': '90'})
        self.assertEqual([o.opportunity for o in r.context['outcomes']], [self.good])
        r = self.client.get(reverse('opportunities'), {'tab': 'all', 'q': 'sql'})
        self.assertEqual([o.opportunity for o in r.context['outcomes']], [self.weak])
        r = self.client.get(reverse('opportunities'), {'tab': 'all', 'skill': self.react.pk})
        self.assertEqual([o.opportunity for o in r.context['outcomes']], [self.good])
        r = self.client.get(reverse('opportunities'), {'tab': 'all', 'type': 'full_time'})
        self.assertEqual([o.opportunity for o in r.context['outcomes']], [self.weak])

    def test_detail_shows_alignment_and_gaps(self):
        give(self.profile, self.react, 80)
        r = self.client.get(reverse('opportunity_detail', args=[self.good.pk]))
        o = r.context['o']
        self.assertEqual([c.name for c in o.meets], ['React'])
        self.assertEqual([c.name for c in o.missing_required], ['Communication'])
        self.assertContains(r, 'Where you already align')
        self.assertContains(r, 'Room to grow')

    def test_inactive_opportunity_404(self):
        r = self.client.get(reverse('opportunity_detail', args=[self.closed.pk]))
        self.assertEqual(r.status_code, 404)

    def test_save_toggle_and_json(self):
        url = reverse('opportunity_save', args=[self.good.pk])
        self.client.post(url)
        self.assertTrue(SavedOpportunity.objects.filter(profile=self.profile).exists())
        r = self.client.post(url, HTTP_X_REQUESTED_WITH='fetch')
        self.assertEqual(r.json(), {'saved': False, 'count': 0})

    def test_apply_records_application(self):
        give(self.profile, self.react, 80)
        r = self.client.post(reverse('opportunity_apply', args=[self.good.pk]))
        self.assertRedirects(r, reverse('opportunity_detail', args=[self.good.pk]))
        app = Application.objects.get(profile=self.profile)
        self.assertIsNotNone(app.match_score)
        self.good.application_url = 'https://example.com/apply'
        self.good.save()
        r = self.client.post(reverse('opportunity_apply', args=[self.good.pk]))
        self.assertEqual(r['Location'], 'https://example.com/apply')
        self.assertEqual(Application.objects.count(), 1)

    def test_skill_gap_page_and_choice(self):
        give(self.profile, self.react, 50)
        r = self.client.get(reverse('skill_gap'))
        self.assertEqual(r.context['target'].opportunity, self.good)
        r = self.client.get(reverse('skill_gap'), {'opportunity': self.weak.pk})
        target = r.context['target']
        self.assertEqual(target.opportunity, self.weak)
        self.assertEqual(r.context['plan']['potential'], 100)

    def test_search(self):
        give(self.profile, self.react, 50)
        r = self.client.get(reverse('search'), {'q': 'react'})
        self.assertEqual([o.opportunity for o in r.context['outcomes']], [self.good])
        self.assertEqual(len(r.context['skills']), 1)

    def test_saved_page(self):
        SavedOpportunity.objects.create(profile=self.profile, opportunity=self.weak)
        r = self.client.get(reverse('saved'))
        self.assertEqual([o.opportunity for o in r.context['outcomes']], [self.weak])


class SeedCommandTests(TestCase):
    def test_seed_is_idempotent_and_labelled(self):
        call_command('seed_skillmatch', '--demo', verbosity=0, stdout=open('/dev/null', 'w'))
        counts = (Skill.objects.count(), Opportunity.objects.count())
        call_command('seed_skillmatch', '--demo', verbosity=0, stdout=open('/dev/null', 'w'))
        self.assertEqual(counts, (Skill.objects.count(), Opportunity.objects.count()))
        self.assertFalse(Opportunity.objects.filter(is_sample=False).exists())
        # Every seeded opportunity can be matched without errors.
        demo = UserProfile.objects.get(user__email='demo.student@skillmatch.test')
        outcomes = rec.recommend(demo)
        self.assertEqual(len(outcomes), Opportunity.objects.active().count())
        self.assertTrue(all(o.score is not None for o in outcomes))
