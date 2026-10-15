# =============================================================================
# CampusMart AI - alternate process declaration (Heroku-style hosts).
# Render uses render.yaml (preferred) but honors this Procfile too.
# -----------------------------------------------------------------------------
# The API package lives in /backend; uvicorn must run from there so
# `app.main:app` resolves and app/*.py relative imports work.
# =============================================================================
web: cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT
