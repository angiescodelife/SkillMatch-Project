"""Text-similarity helpers for the matching engine.

Two back-ends are supported:

* **TF-IDF + cosine similarity** (scikit-learn). Always available and the
  default. Compares the words used in a profile/CV with the words used in
  an opportunity description.
* **Sentence Transformers** (optional, Proposal Objective 2). When
  SKILLMATCH_USE_SENTENCE_TRANSFORMERS is true and the package is
  installed, texts are embedded with a transformer model so that meaning,
  not just shared wording, is compared. This back-end is also used to spot
  *related* skills (e.g. "Vue.js" for a "React" requirement), which the
  matching engine credits partially and labels explicitly.

If the transformer model cannot be loaded for any reason the code falls
back to TF-IDF, so the application never fails because of the AI layer.
"""
import logging
from functools import lru_cache

from django.conf import settings

logger = logging.getLogger(__name__)

RELATED_SKILL_THRESHOLD = 0.72


@lru_cache(maxsize=1)
def _sentence_model():
    if not getattr(settings, 'SKILLMATCH_USE_SENTENCE_TRANSFORMERS', False):
        return None
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        logger.warning('sentence-transformers not installed; using TF-IDF fallback.')
        return None
    try:
        return SentenceTransformer(settings.SKILLMATCH_SENTENCE_MODEL)
    except Exception:  # pragma: no cover - network/model errors
        logger.exception('Could not load sentence-transformers model; using TF-IDF.')
        return None


def backend_name():
    return 'sentence-transformers' if _sentence_model() is not None else 'tf-idf'


def _cosine_rows(matrix_a, matrix_b):
    from sklearn.metrics.pairwise import cosine_similarity

    return cosine_similarity(matrix_a, matrix_b)


def text_similarities(profile_text, documents):
    """Return one similarity score (0–1) per document for the profile text."""
    documents = list(documents)
    if not documents:
        return []
    if not (profile_text or '').strip():
        return [0.0] * len(documents)

    model = _sentence_model()
    if model is not None:
        try:
            vectors = model.encode([profile_text] + documents, normalize_embeddings=True)
            sims = _cosine_rows(vectors[:1], vectors[1:])[0]
            return [max(0.0, float(s)) for s in sims]
        except Exception:  # pragma: no cover
            logger.exception('Embedding failed; falling back to TF-IDF.')

    from sklearn.feature_extraction.text import TfidfVectorizer

    try:
        vectoriser = TfidfVectorizer(
            stop_words='english', ngram_range=(1, 2), sublinear_tf=True, min_df=1
        )
        matrix = vectoriser.fit_transform([profile_text] + documents)
    except ValueError:  # empty vocabulary (e.g. only stop words)
        return [0.0] * len(documents)
    sims = _cosine_rows(matrix[0:1], matrix[1:])[0]
    return [float(s) for s in sims]


def related_skills(missing_names, user_names, threshold=RELATED_SKILL_THRESHOLD):
    """Map each missing skill name to the most similar skill the user has.

    Only available with the Sentence Transformers back-end; with TF-IDF the
    short skill names do not carry enough signal, so no related-skill credit
    is given (an honest "missing" is better than a false "related").
    Returns {missing_name: (user_skill_name, similarity)}.
    """
    model = _sentence_model()
    missing_names, user_names = list(missing_names), list(user_names)
    if model is None or not missing_names or not user_names:
        return {}
    try:
        miss_vec = model.encode(missing_names, normalize_embeddings=True)
        user_vec = model.encode(user_names, normalize_embeddings=True)
    except Exception:  # pragma: no cover
        logger.exception('Embedding failed for related skills.')
        return {}
    sims = _cosine_rows(miss_vec, user_vec)
    result = {}
    for i, name in enumerate(missing_names):
        j = int(sims[i].argmax())
        if float(sims[i][j]) >= threshold:
            result[name] = (user_names[j], float(sims[i][j]))
    return result
