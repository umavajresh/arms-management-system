Quick Render deployment

1. Push this repository (or your fork) to GitHub. Example:

```bash
git add .
git commit -m "Prepare for Render deployment"
git push origin main
```

2. In Render dashboard: New -> Web Service -> Connect your GitHub repo `umavajresh/arms-management-system`.

3. Render will detect `render.yaml` and create a service. If manual, set:
   - Environment: `Python 3`
   - Build Command: `pip install --upgrade pip && pip install -r django_arms/requirements.txt && python django_arms/manage.py collectstatic --noinput`
   - Start Command: `gunicorn django_arms.wsgi:application --bind 0.0.0.0:$PORT`

4. Set environment variables in Render (Dashboard -> Environment):
   - `SECRET_KEY` — generate a secure random string
   - `DEBUG` = `False`
   - `ALLOWED_HOSTS` = yourdomain.com (or `*` to test)
   - `AVIATIONSTACK_API_KEY` = your live flight API key
   - `DATABASE_URL` (if using Postgres)

5. After deploy, open the Live URL. Run migrations in Render Shell:

```bash
python django_arms/manage.py migrate
python django_arms/manage.py createsuperuser
```

That's it — Render manages TLS and scaling.
