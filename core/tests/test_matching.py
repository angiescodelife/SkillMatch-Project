"""Unit tests for the matching engine, using controlled data (no database)."""
from datetime import date

from django.test import SimpleTestCase

from core.services import matching as m
from core.services import similarity


def profile(skills=None, prefs=None, user_type='student', text=''):
    skills = skills or {}
    data = {
        i: m.UserSkillData(i, name, score, stype)
        for i, (name, score, stype) in skills.items()
    }
    return m.ProfileData(data, user_type, prefs or m.PreferenceData(), text)


def opp(reqs, **kw):
    requirements = [m.RequirementData(i, name, imp, target, stype)
                    for i, (name, imp, target, stype) in reqs.items()]
    return m.OpportunityData(id=kw.pop('id', 1), requirements=requirements, **kw)


REACT, JS, TS, GQL, COMM, TEAM = 1, 2, 3, 4, 5, 6


class SkillCreditTests(SimpleTestCase):
    def test_all_required_skills_meeting_target_score_100(self):
        p = profile({REACT: ('React', 80, 'technical'), JS: ('JavaScript', 90, 'technical')})
        o = opp({REACT: ('React', 'required', 75, 'technical'),
                 JS: ('JavaScript', 'required', 80, 'technical')})
        r = m.calculate_match(p, o)
        self.assertEqual(r.technical, 100)
        self.assertEqual(r.score, 100)  # only the technical component is available
        self.assertEqual(r.required_coverage, 100)
        self.assertEqual([c.status for c in r.comparisons], ['meets', 'meets'])

    def test_baseline_required_coverage_formula(self):
        """matched required ÷ total required × 100, regardless of level."""
        p = profile({REACT: ('React', 10, 'technical'), JS: ('JavaScript', 90, 'technical')})
        o = opp({REACT: ('React', 'required', 75, 'technical'),
                 JS: ('JavaScript', 'required', 80, 'technical'),
                 TS: ('TypeScript', 'required', 60, 'technical'),
                 GQL: ('GraphQL', 'required', 50, 'technical')})
        self.assertEqual(m.calculate_match(p, o).required_coverage, 50)

    def test_proficiency_below_target_gives_partial_credit(self):
        p = profile({REACT: ('React', 30, 'technical')})
        o = opp({REACT: ('React', 'required', 60, 'technical')})
        r = m.calculate_match(p, o)
        self.assertEqual(r.comparisons[0].status, 'below')
        self.assertAlmostEqual(r.comparisons[0].credit, 0.5)
        self.assertEqual(r.technical, 50)
        self.assertEqual(r.below_target[0].gap_points, 30)

    def test_credit_is_capped_at_one(self):
        p = profile({REACT: ('React', 100, 'technical')})
        o = opp({REACT: ('React', 'required', 40, 'technical')})
        self.assertEqual(m.calculate_match(p, o).comparisons[0].credit, 1.0)

    def test_required_skills_weigh_twice_preferred(self):
        p = profile({REACT: ('React', 80, 'technical')})
        o = opp({REACT: ('React', 'required', 70, 'technical'),
                 GQL: ('GraphQL', 'preferred', 50, 'technical')})
        r = m.calculate_match(p, o)
        # (2 × 1 + 1 × 0) / (2 + 1) = 0.667
        self.assertEqual(r.technical, 67)
        self.assertEqual([c.name for c in r.missing_preferred], ['GraphQL'])
        self.assertEqual(r.missing_required, [])

    def test_missing_skills_are_identified(self):
        p = profile({REACT: ('React', 80, 'technical')})
        o = opp({REACT: ('React', 'required', 70, 'technical'),
                 TS: ('TypeScript', 'required', 60, 'technical'),
                 GQL: ('GraphQL', 'preferred', 50, 'technical')})
        r = m.calculate_match(p, o)
        self.assertEqual([c.name for c in r.matched_required], ['React'])
        self.assertEqual([c.name for c in r.missing_required], ['TypeScript'])
        self.assertEqual([c.name for c in r.missing_preferred], ['GraphQL'])
        # Core gaps come first in the gap list.
        self.assertEqual([c.name for c in r.gaps], ['TypeScript', 'GraphQL'])


class WeightingTests(SimpleTestCase):
    def test_weighted_formula(self):
        prefs = m.PreferenceData(opportunity_types=['internship'], work_styles=['hybrid'])
        p = profile({REACT: ('React', 80, 'technical'), COMM: ('Communication', 40, 'soft')}, prefs)
        o = opp({REACT: ('React', 'required', 80, 'technical'),
                 COMM: ('Communication', 'required', 80, 'soft')},
                opportunity_type='internship', work_style='hybrid', location='Nairobi')
        r = m.calculate_match(p, o)
        self.assertEqual((r.technical, r.soft, r.preferences), (100, 50, 100))
        # 0.60 × 1 + 0.25 × 0.5 + 0.15 × 1 = 0.875
        self.assertEqual(r.score, 88)

    def test_missing_component_weights_are_redistributed(self):
        prefs = m.PreferenceData(work_styles=['remote'])
        p = profile({REACT: ('React', 80, 'technical')}, prefs)
        o = opp({REACT: ('React', 'required', 80, 'technical')}, work_style='hybrid')
        r = m.calculate_match(p, o)
        self.assertIsNone(r.soft)
        self.assertEqual(r.preferences, 0)
        self.assertAlmostEqual(r.weights_used['technical'], 0.8)
        self.assertAlmostEqual(r.weights_used['preferences'], 0.2)
        self.assertEqual(r.score, 80)
        self.assertAlmostEqual(sum(r.weights_used.values()), 1.0)

    def test_no_requirements_and_no_preferences_gives_no_score(self):
        r = m.calculate_match(profile({REACT: ('React', 80, 'technical')}), opp({}))
        self.assertIsNone(r.score)
        self.assertIsNone(r.required_coverage)
        self.assertEqual(r.label, 'Not enough information')

    def test_user_without_skills_scores_zero_not_error(self):
        o = opp({REACT: ('React', 'required', 60, 'technical')})
        r = m.calculate_match(profile(), o)
        self.assertEqual(r.score, 0)
        self.assertEqual(r.required_coverage, 0)
        self.assertEqual(len(r.missing_required), 1)

    def test_results_are_deterministic(self):
        p = profile({REACT: ('React', 63, 'technical'), COMM: ('Communication', 71, 'soft')})
        o = opp({REACT: ('React', 'required', 75, 'technical'),
                 COMM: ('Communication', 'preferred', 60, 'soft'),
                 GQL: ('GraphQL', 'preferred', 50, 'technical')})
        scores = {m.calculate_match(p, o).score for _ in range(20)}
        self.assertEqual(len(scores), 1)


class PreferenceTests(SimpleTestCase):
    def test_remote_location_alone_does_not_create_preference_score(self):
        o = opp({REACT: ('React', 'required', 60, 'technical')}, work_style='remote', location='Kenya')
        r = m.calculate_match(profile({REACT: ('React', 60, 'technical')}), o)
        self.assertIsNone(r.preferences)

    def test_eligibility_mismatch_counts_even_without_preferences(self):
        o = opp({REACT: ('React', 'required', 60, 'technical')}, eligible_user_types=['graduate'])
        r = m.calculate_match(profile({REACT: ('React', 60, 'technical')}, user_type='student'), o)
        self.assertEqual(r.preferences, 0)
        self.assertEqual(r.score, 80)  # 0.6 / 0.75 × 1 + 0.15 / 0.75 × 0

    def test_location_and_start_date(self):
        prefs = m.PreferenceData(locations=['Nairobi'], available_from=date(2027, 1, 1))
        o = opp({}, location='Nairobi', work_style='onsite', start_date=date(2027, 2, 1))
        r = m.calculate_match(profile(prefs=prefs), o)
        statuses = {c.key: c.status for c in r.preference_checks}
        self.assertEqual(statuses['location'], 'match')
        self.assertEqual(statuses['start'], 'match')
        late = m.PreferenceData(locations=['Mombasa'], available_from=date(2027, 6, 1))
        r2 = m.calculate_match(profile(prefs=late), o)
        self.assertEqual(r2.preferences, 0)


class RankingAndPotentialTests(SimpleTestCase):
    def test_rank_orders_by_score_then_similarity_with_unscored_last(self):
        a = m.MatchOutcome(1, 70, None, None, None, {}, None, [], [], text_similarity=0.1)
        b = m.MatchOutcome(2, 90, None, None, None, {}, None, [], [], text_similarity=0.0)
        c = m.MatchOutcome(3, 70, None, None, None, {}, None, [], [], text_similarity=0.5)
        d = m.MatchOutcome(4, None, None, None, None, {}, None, [], [])
        self.assertEqual([o.opportunity_id for o in m.rank([a, b, c, d])], [2, 3, 1, 4])

    def test_potential_score_closes_gaps(self):
        p = profile({REACT: ('React', 40, 'technical')})
        o = opp({REACT: ('React', 'required', 80, 'technical'),
                 GQL: ('GraphQL', 'preferred', 50, 'technical')})
        now = m.calculate_match(p, o).score
        self.assertEqual(m.potential_score(p, o), 100)
        self.assertLess(now, 100)
        self.assertEqual(m.potential_score(p, o, skill_ids={GQL}), m.calculate_match(
            profile({REACT: ('React', 40, 'technical'), GQL: ('GraphQL', 50, 'technical')}), o).score)

    def test_related_skill_gets_labelled_partial_credit(self):
        p = profile({7: ('Vue.js', 80, 'technical')})
        o = opp({REACT: ('React', 'required', 80, 'technical')})
        r = m.calculate_match(p, o, related={'React': ('Vue.js', 0.8)})
        c = r.comparisons[0]
        self.assertEqual((c.status, c.related_to), ('related', 'Vue.js'))
        self.assertAlmostEqual(c.credit, 0.5)
        self.assertIn('Vue.js is related to React', r.explanation)
        self.assertEqual(r.required_coverage, 0)  # related ≠ matched in the baseline

    def test_explanation_is_built_from_data(self):
        p = profile({REACT: ('React', 90, 'technical')})
        o = opp({REACT: ('React', 'required', 70, 'technical'),
                 TS: ('TypeScript', 'required', 60, 'technical')})
        text = m.calculate_match(p, o).explanation
        self.assertIn('React', text)
        self.assertIn('You meet 1 of 2 listed skills.', text)
        self.assertIn('TypeScript is a core requirement', text)


class SimilarityTests(SimpleTestCase):
    def test_tfidf_ranks_relevant_document_higher(self):
        docs = ['Build React interfaces with TypeScript and JavaScript for web users.',
                'Manage warehouse inventory and drive delivery trucks.']
        sims = similarity.text_similarities('React TypeScript frontend web developer', docs)
        self.assertGreater(sims[0], sims[1])

    def test_empty_profile_text_returns_zeros(self):
        self.assertEqual(similarity.text_similarities('', ['a b c', 'd e f']), [0.0, 0.0])

    def test_related_skills_disabled_without_transformers(self):
        self.assertEqual(similarity.related_skills(['React'], ['Vue.js']), {})


class FakeEmbedder:
    """Stands in for a SentenceTransformer: maps known words to fixed vectors."""
    VECTORS = {'react': [1, 0, 0], 'vue.js': [0.9, 0.1, 0], 'graphql': [0, 1, 0],
               'farming': [0, 0, 1]}

    def encode(self, texts, normalize_embeddings=True):
        import numpy as np
        rows = []
        for t in texts:
            v = np.zeros(3)
            for word, vec in self.VECTORS.items():
                if word in t.lower():
                    v += vec
            n = np.linalg.norm(v) or 1.0
            rows.append(v / n)
        return np.array(rows)


class SentenceTransformerPathTests(SimpleTestCase):
    def setUp(self):
        from unittest import mock
        patcher = mock.patch.object(similarity, '_sentence_model', return_value=FakeEmbedder())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_backend_reports_transformers(self):
        self.assertEqual(similarity.backend_name(), 'sentence-transformers')

    def test_embedding_similarity_used(self):
        sims = similarity.text_similarities('React developer', ['React role', 'farming role'])
        self.assertGreater(sims[0], 0.9)
        self.assertEqual(sims[1], 0.0)

    def test_related_skills_found_above_threshold_only(self):
        related = similarity.related_skills(['React', 'GraphQL'], ['Vue.js', 'Farming'])
        self.assertEqual(list(related), ['React'])
        self.assertEqual(related['React'][0], 'Vue.js')
