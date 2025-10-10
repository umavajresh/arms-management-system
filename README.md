# Django ARMS (Airline Reservation Management System)

This repository contains a Django-based Airline Reservation Management System (ARMS).

## Quick setup (development)

1. Create a Python virtual environment and activate it:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Set required environment variables (recommended, especially for production):

- `DJANGO_SECRET_KEY` (recommended as replacement for SECRET_KEY in settings)
- `ID_ENCRYPTION_KEY` (if using the encrypt template filter)

You can create a `.env` file locally with these keys (do NOT commit `.env`).

4. Run migrations and start the dev server:

```powershell
python manage.py migrate
python manage.py runserver
```

## Preparing to push to GitHub

1. Initialize a git repository (if not already):

```powershell
git init
git add .
git commit -m "Initial import of django_arms"
```

2. Add your GitHub remote and push:

```powershell
git remote add origin https://github.com/<your-username>/<your-repo>.git
git branch -M main
git push -u origin main
```

3. Share the repo URL with your teammates or create a zip and send it.

## Creating a zip for sharing (Windows PowerShell)

From project root (the repository root):

```powershell
Compress-Archive -Path * -DestinationPath ..\django_arms.zip -Force
```

This creates `django_arms.zip` on your Desktop (`..\` relative to the project folder). Teammates can extract and run the project locally.

## Notes & security

- `settings.py` currently contains a hard-coded `SECRET_KEY` and `DEBUG=True`. For production, move secrets to environment variables and set `DEBUG=False`.
- Add missing packages in `requirements.txt` if you use `qr_code`, `captcha`, or `cryptography`.

If you want, I can:
- Replace hard-coded SECRET_KEY with environment-based config and add `.env.example`.
- Update `requirements.txt` with missing packages.
- Initialize the local git repo and create the zip for you now.
