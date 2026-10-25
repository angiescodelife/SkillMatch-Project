#!/usr/bin/env bash
# Render build script: install, collect static files, migrate, load data.
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate --no-input

# Skill dictionary, learning resources and labelled sample opportunities.
# Safe to run on every deploy. SEED_DEMO=true also creates the demo student.
if [ "${SEED_DEMO:-false}" = "true" ]; then
  python manage.py seed_skillmatch --demo
else
  python manage.py seed_skillmatch
fi

# Create an admin account once, from DJANGO_SUPERUSER_* environment variables
# (Render's free plan has no shell). Ignored if the account already exists.
if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ]; then
  python manage.py createsuperuser --no-input || true
fi
