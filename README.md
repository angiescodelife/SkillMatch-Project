# SkillMatch

**An AI-Powered Skill Matching and Employability Recommendation System for University Students and Recent Graduates**
BSc Computer Science final-year project · Django · Django templates, HTML, CSS and JavaScript

SkillMatch compares a student's or graduate's skills, CV and career preferences with internship, graduate-programme and entry-level opportunities. It then explains the result: an explainable match score, the skills they already have, the skills they're missing and a focused learning plan.

---

## 1. Quick start (Windows)

```powershell
cd "C:\Skill project"
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

copy .env.example .env          # then edit DJANGO_SECRET_KEY (see below)
python manage.py migrate         # safe on your existing db.sqlite3, see section 3
python manage.py seed_skillmatch --demo
python manage.py runserver
```

Open http://127.0.0.1:8000/ and log in with the demo student:

| Email | Password |
|---|---|
| `demo.student@skillmatch.test` | `SkillMatch!2026` |

Or create your own account on the registration page. To use the Django admin run `python manage.py createsuperuser`, then visit `/admin/`.

Generate a secret key for `.env` with:
```powershell
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

macOS / Linux: the same steps, using `source venv/bin/activate` and `cp`.

---

## 1b. Deploying on Render

The repository includes `render.yaml` (a Render Blueprint), `build.sh` and `.python-version`.

1. Push the project to GitHub, including `render.yaml`, `build.sh`, `.python-version` and `.gitattributes`.
2. In the Render dashboard, choose **New → Blueprint**, connect the repository and click **Apply**. This creates:
   * `skillmatch-db`: a free PostgreSQL database;
   * `skillmatch`: a free web service.
3. When asked, fill in `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_EMAIL` and `DJANGO_SUPERUSER_PASSWORD`. The admin account is created on the first deploy.
4. Every deploy runs `build.sh`: install → `collectstatic` → `migrate` → `seed_skillmatch`. With `SEED_DEMO=true` it also creates the demo student; set it to `false` to skip that.

Production settings switch on automatically on Render:
* `DEBUG` off, and HTTPS redirect and secure cookies on;
* the Render hostname added to `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`;
* static files served by WhiteNoise;
* the database taken from `DATABASE_URL`.

**Free-plan limits to know** ([Render docs](https://render.com/docs/free)):
* **Sleep:** the service sleeps after 15 minutes without visits, and the first visit afterwards takes about a minute.
* **Uploaded files are temporary.** Résumé files and profile photos are deleted when the service restarts or sleeps. Skills extracted from résumés are kept, because they live in the database.
* **The free database expires 30 days after creation**, followed by a 14-day grace period. Create it close to your evaluation, or upgrade it.
* **No shell on the free plan.** That's why `build.sh` seeds the data and creates the admin account.
* **Semantic matching:** Sentence Transformers isn't installed on Render, so it uses TF-IDF matching.

---

## 2. Running the tests

```powershell
python manage.py test core
```

**77 tests, all passing** (run on 25 Oct 2026, Python 3.13, Django 6.1.1) on both SQLite and PostgreSQL 16. The production setup (gunicorn, WhiteNoise, HTTPS settings, `build.sh` run twice) was also checked against PostgreSQL. The tests cover:

| File | What it covers |
|---|---|
| `core/tests/test_matching.py` | Score formula, required-coverage baseline, partial credit, required vs nice-to-have weights, weight redistribution, empty data, preferences and eligibility, ranking, potential score, related-skill credit, explanation text, TF-IDF similarity, Sentence Transformers integration (with a stub model) |
| `core/tests/test_cv_extraction.py` | Skill name normalisation and aliases, word boundaries ("Java" vs "JavaScript"), spelling variants ("Node.js", "node js"), case-sensitive short terms ("R", "Go"), PDF and DOCX extraction including tables, fake/renamed files, unreadable PDFs |
| `core/tests/test_views.py` | Login with email or legacy username, registration validation, login-required pages, owner-only access to skills and CVs, the CV upload → review → accept workflow, profile, preferences and password changes, opportunity filters, save/apply, skill-gap page, search, idempotent seed command |
| `core/tests/test_migrations.py` | Migrating a pre-upgrade database keeps every existing user, profile, skill and proficiency level |

An end-to-end browser run was also done with Playwright: register → upload CV → review skills → add/edit skill → filter → save → match details → skill gap → search → mobile layout → log out. It completed with no JavaScript errors.

---

## 3. Database and migrations

* **Your existing data is preserved.** Migrations `0001`–`0003` are unchanged. Two new migrations are added:
  * `0004_profile_skills_opportunities_matching`: additive only. New columns have defaults, and the new tables are created.
  * `0005_backfill_skill_data`: fills the new fields for existing rows without deleting anything:
    * proficiency levels are converted to percentages (beginner → 30, intermediate → 60, advanced → 85), so each skill keeps the same level;
    * normalised names are computed;
    * known soft skills are marked as soft;
    * each profile gets an empty career-preferences record.
* As a precaution, **back up `db.sqlite3` before running `migrate`** (copy the file).
* `seed_skillmatch` is safe to run any number of times. It only adds or updates the skill dictionary, learning resources and the labelled sample opportunities. `--demo` also creates the demo student. `--no-opportunities` loads only skills and resources.

### Switching to PostgreSQL (the proposal's target database)
1. Create a database, e.g. `createdb skillmatch`.
2. In `.env` set `DATABASE_ENGINE=postgresql` and the `POSTGRES_*` values.
3. Run `python manage.py migrate` then `python manage.py seed_skillmatch`.

`psycopg2-binary` is already in `requirements.txt`. To move existing SQLite data, use `python manage.py dumpdata --natural-foreign --exclude contenttypes --exclude auth.permission > data.json` with the SQLite settings, then `loaddata data.json` with the PostgreSQL settings.

---

## 4. How matching works

The engine lives in `core/services/matching.py`. It's pure Python with no database access, so it can be unit-tested with controlled data.

For each skill an opportunity lists (with a target level 1–100, and required or nice-to-have):

```
credit = min(1, user proficiency ÷ role target)   if the user has the skill (name or alias)
credit = 0.5 × min(1, related ÷ target)            if only a related skill is found (Sentence Transformers only)
credit = 0                                         otherwise
```

Required skills weigh **2**, nice-to-haves **1**. Credits are averaged separately for technical and soft skills:

```
component       = Σ(weight × credit) / Σ(weight)
role preference = share of the user's stated preferences that the role satisfies
                  (type, work style, location, start date, eligibility)

match score = 0.60 × technical + 0.25 × soft skills + 0.15 × role preferences
```

* If a component can't be calculated (no soft skills listed, no preferences set), it's dropped and the remaining weights are scaled to 100%.
* If nothing can be calculated the score is `None` ("Not enough information"), never a guess.
* The brief's baseline is also stored and displayed: **required coverage = matched required ÷ total required × 100**.
* **Text similarity** compares profile and CV text with the description, using TF-IDF + cosine similarity, or Sentence Transformers when enabled. It's shown and used to break ties in ranking, but it never changes the score.
* Labels: Strong ≥ 85 · Good ≥ 70 · Partial ≥ 50 · Early < 50.
* Every calculation is stored in `MatchResult`, the ERD's Recommendation entity, so results can be audited and employers can later rank applicants.
* The same explanation is shown to users on the in-app **Help → How matching works** page.

### CV extraction (`core/services/cv_extraction.py`)
* Text is read with **pdfplumber** (PDF) or **python-docx** (DOCX, including tables).
* Files are validated by extension, size (max 10 MB) and file signature.
* Skills are found by matching against the controlled **skill dictionary**: 82 skills with aliases, editable in the admin. Matching is tolerant of spacing and punctuation and uses word boundaries.
* If spaCy is installed, a `PhraseMatcher` pass is added.
* Nothing is added automatically. Users **review** the found skills, choose a level for each and confirm.
* Scanned or image-only PDFs give a clear error message.

### Optional: Sentence Transformers (Proposal Objective 2)
```powershell
pip install -r requirements-ai.txt     # large: installs PyTorch
```
Then set `SKILLMATCH_USE_SENTENCE_TRANSFORMERS=True` in `.env`. The model (`all-MiniLM-L6-v2`) downloads on first use. If it can't load, the app automatically falls back to TF-IDF.

---

## 5. Google sign-in (optional, off by default)
1. In Google Cloud Console create an OAuth client of type "Web application".
2. Add the redirect URI `http://127.0.0.1:8000/accounts/google/login/callback/`.
3. Put `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in `.env` and restart the server.

The "Continue with Google" button only appears once both values are set. New Google users get a student profile automatically.

---

## 6. Figma screen → template → backend

| Figma screen | Template | View / URL |
|---|---|---|
| SkillMatch login | `core/auth/login.html` (+ `layouts/auth.html`) | `user_login` · `/login/` |
| SkillMatch registration | `core/auth/register.html` | `register` · `/register/` |
| Student dashboard (desktop + mobile) | `core/dashboard.html` | `dashboard` · `/dashboard/` |
| Student profile and resume | `core/profile/profile.html` (+ `preferences.html`, `account.html`, `cv_review.html`) | `profile`, `career_preferences`, `account_settings`, `cv_upload`, `cv_review` · `/profile/…` |
| Skills overview | `core/skills.html` | `manage_skills`, `skill_update` · `/skills/` |
| Job and internship recommendations (desktop + mobile) | `core/opportunities/list.html` | `opportunity_list` · `/opportunities/` |
| Opportunity match details (desktop + mobile) | `core/opportunities/detail.html` | `opportunity_detail`, `opportunity_save`, `opportunity_apply` |
| Skill gap analysis | `core/skill_gap.html` | `skill_gap` · `/skill-gap/` |
| *(no Figma)* Saved, Search, Help, Privacy, Terms, Password reset | built from the same components | `/saved/`, `/search/`, `/help/` … |

Shared pieces:
* `layouts/app.html`: sidebar, top bar, mobile header and bottom tab bar.
* `partials/`: opportunity card, match ring, badges, form fields and others.
* `static/core/css/skillmatch.css`: one stylesheet with tokens sampled from the Figma frames.
* `static/core/js/skillmatch.js`: small progressive enhancements.
* `core/icons.py`: Lucide icons (ISC licence), served inline.

---

## 7. Files created or modified

**Modified:**
* `config/settings.py`: environment variables, PostgreSQL option, media, allauth, auth backend.
* `config/urls.py`, `core/models.py`, `core/forms.py`, `core/urls.py`, `core/admin.py`, `requirements.txt` (re-saved as UTF-8; it was UTF-16).
* `core/templates/core/dashboard.html`, `home.html`, `skills.html`.

**Replaced:**
* `core/views.py` → the `core/views/` package. The original URL names and skill-management behaviour are kept.
* `core/templates/login.html` → `core/templates/core/auth/login.html`. This fixes a crash: the view looked for `core/login.html`, which didn't exist.
* `core/templates/core/register.html` → `core/auth/register.html`.
* `core/tests.py` → the `core/tests/` package.

**New:**
* `core/services/`: `matching.py`, `similarity.py`, `recommendations.py`, `cv_extraction.py`.
* `core/migrations/0004_…`, `0005_…`.
* `core/management/commands/seed_skillmatch.py`, `core/seed_data.py`.
* `core/backends.py` (email-or-username login), `core/adapters.py` (Google), `core/context_processors.py`, `core/templatetags/skillmatch_tags.py`, `core/icons.py`.
* All templates under `core/templates/core/{layouts,partials,auth,profile,opportunities,pages}`.
* `core/static/core/…`, `.env.example`, `.gitignore`, `requirements-ai.txt`, `README.md`.

---

## 8. What's complete

* Registration (full name, email, university, student/graduate, terms) and login by email or legacy username, with "keep me signed in", password reset (emails print to the console) and password change.
* Profile: personal information, photo, education, career preferences, and a profile-strength checklist calculated from real data.
* Skills: add with dictionary autocomplete and aliases, edit with a 1–100 slider, remove, search and filter. Duplicates are prevented, and each skill is split into technical or soft with its source shown.
* CV upload (PDF/DOCX) → extraction → review → confirm. Files are owner-only, stored outside the public media folder, and can be replaced or deleted.
* Opportunities:
  * search (role, company or skill), location, type and work-style filters with counts, minimum match, start date, "uses my skills" filter;
  * For you / All tabs, sort and pagination;
  * save without a page reload.
* Match details: weighted score ring, explanation, skill alignment against role targets, gaps with learning links, score breakdown, preference fit, apply/save.
* Skill gap analysis: choose the target role, see the gaps behind the score, a learning plan with real free resources, illustrative potential score (recalculated, not hard-coded), "go a little further" suggestions, and skills in demand across your matches.
* Responsive layout following the three mobile Figma frames: bottom tab bar, sticky actions, collapsible filters.
* Empty states for new users and for users with no matches.

## 9. Not yet built / known limitations

* **Employer side** (employer accounts, posting and editing vacancies, reviewing ranked applicants) isn't built yet, as agreed: student screens first. The database is ready for it (`Employer.user`, `Application`, `MatchResult`). Until then, opportunities are managed in the Django admin.
* **Sample data**: the 24 opportunities and 12 employers are fictional and labelled "Sample". Their application buttons record intent but don't submit anywhere.
* **Notifications**: the Figma bell icon is left out because there's no notification feature.
* **Login illustration**: on the login screen, the decorative "94% match" chip reads "Skill match" so no un-calculated percentage appears.
* **Sentence Transformers**: the integration is tested with a stub model. The real model couldn't be downloaded in the build environment, so it's untested end-to-end.
* **Google sign-in**: tested up to the redirect to Google. The full login needs real OAuth credentials.
* **CV extraction** finds dictionary skills only. It doesn't parse job history or education dates, and scanned (image-only) PDFs aren't supported (no OCR).
* **Proposal wording vs. implementation**: the proposal mentions Bootstrap 5. Custom CSS was used instead so the screens match the Figma designs closely, which may be worth a sentence in your report.
* **Before deploying**: set `DJANGO_DEBUG=False`, a real `DJANGO_SECRET_KEY` and `DJANGO_ALLOWED_HOSTS`, and serve over HTTPS. `check --deploy` then only asks for HSTS and the SSL redirect, which depend on your host.
