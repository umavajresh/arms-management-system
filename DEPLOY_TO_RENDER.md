# ARMS 2.0 Deployment Guide for Render (100% Free Tier)

This guide walks you through deploying ARMS 2.0 to Render using the verified zero-cost free tier without touching your review-ready `main` branch.

---

## 1. Quick Deploy via Render Dashboard (Recommended)

1. Open your browser and go to the [Render Dashboard](https://dashboard.render.com).
2. Sign in with your GitHub account (`umavajresh`).
3. Click **New +** (top right) and choose **Web Service**.
4. Under **Connect a repository**, find or select:
   ```
   umavajresh/arms-management-system
   ```
   *(If not listed, click "Configure account" to grant Render access to this repository).*

5. Fill in the deployment settings:
   - **Name**: `arms-aviation` (or any name you prefer)
   - **Region**: `Oregon (US West)` or `Frankfurt (EU)`
   - **Branch**: `deployment/arms-safe-launch` *(Ensures your review branch is protected)*
   - **Root Directory**: `django_arms`
   - **Runtime**: `Python 3`
   - **Build Command**:
     ```bash
     pip install --upgrade pip && pip install -r requirements.txt && python manage.py migrate && python manage.py import_data && python manage.py collectstatic --noinput
     ```
   - **Start Command**:
     ```bash
     gunicorn django_arms.wsgi:application --bind 0.0.0.0:$PORT
     ```
   - **Instance Type**: Select **Free** ($0 / month).

6. Under **Environment Variables**, add:
   | Key | Value | Notes |
   | :--- | :--- | :--- |
   | `SECRET_KEY` | `django-insecure-arms-prod-secure-token-2026-v2-xyz` | Any 50+ character random string |
   | `DEBUG` | `False` | Production mode |
   | `ALLOWED_HOSTS` | `*` | Allows your `.onrender.com` domain |
   | `PYTHON_VERSION` | `3.12.8` | Consistent Python runtime |

7. Click **Create Web Service**.
8. Render will start the build log. Once finished (~2-3 minutes), your live public URL will appear at the top:
   ```
   https://arms-aviation.onrender.com
   ```

---

## 2. Deploy via Render Blueprint (`render.yaml`)

Alternatively, use Render's Infrastructure-as-Code Blueprint:

1. In Render Dashboard, click **New +** &rarr; **Blueprint**.
2. Connect `umavajresh/arms-management-system`.
3. Choose branch `deployment/arms-safe-launch`.
4. Render automatically detects [`render.yaml`](./render.yaml), provisions the **Free** instance, generates a secure `SECRET_KEY`, and launches the service.

---

## 3. Post-Deployment Verification Checklist

Once Render shows **"Live"**:
1. Open your public `https://<your-service>.onrender.com` URL in your browser.
2. Verify the homepage loads with the dark cinematic theme.
3. Test **Upcoming Flights** at `/upcoming_flights`.
4. Test the **AI Travel Assistant** at `/travel_chat`.
5. Login as admin at `/login` or register a new traveler account.

*(Note: On Render's free tier, the web service automatically spins down after 15 minutes of inactivity. The first request after sleep may take ~30-50 seconds to warm up).*
