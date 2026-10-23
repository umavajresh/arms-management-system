FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8001

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY . /app/

WORKDIR /app/django_arms
RUN python manage.py collectstatic --noinput

EXPOSE 8001

CMD ["gunicorn", "django_arms.wsgi:application", "--bind", "0.0.0.0:8001", "--workers", "3"]
