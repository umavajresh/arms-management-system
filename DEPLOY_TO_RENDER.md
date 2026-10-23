# ARMS 2.0 Deployment Guide

## 1. Quick Deploy to Render

1. Commit and push all changes to GitHub:
   ```bash
   git add .
   git commit -m "Deploy ARMS 2.0"
   git push origin main
   ```
2. In the [Render Dashboard](https://dashboard.render.com):
   - Click **New** &rarr; **Blueprint** (or **Web Service**).
   - Connect your GitHub repository `umavajresh/arms-management-system`.
   - Render automatically reads [`render.yaml`](./render.yaml).
3. If creating manually as a Web Service:
   - **Root Directory**: `django_arms`
   - **Environment**: `Python 3`
   - **Build Command**: `pip install --upgrade pip && pip install -r requirements.txt && python manage.py migrate && python manage.py collectstatic --noinput`
   - **Start Command**: `gunicorn django_arms.wsgi:application --bind 0.0.0.0:$PORT`
4. Set Environment Variables:
   - `SECRET_KEY`: `<secure-random-key>`
   - `DEBUG`: `False`
   - `ALLOWED_HOSTS`: `*` (or your custom domain)
   - `AVIATIONSTACK_API_KEY`: `<optional-live-radar-key>`

---

## 2. Docker Deployment

Deploy on any cloud VM (AWS EC2, DigitalOcean, Hetzner, GCP):

```bash
# Build and run container in detached mode
docker compose up -d --build
```
Access the application at `http://<your-server-ip>:8001/`.

---

## 3. Local Production Daemon (Gunicorn)

Run as a high-performance background daemon on your Mac or Linux server:

```bash
cd django_arms
../.venv/bin/gunicorn django_arms.wsgi:application --bind 127.0.0.1:8001 --workers 3 --daemon
```

To stop:
```bash
pkill -f "gunicorn.*django_arms"
```
