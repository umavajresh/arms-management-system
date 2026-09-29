FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY . /app
RUN pip install --upgrade pip && pip install -r django_arms/requirements.txt
ENV PORT=8000
EXPOSE 8000
CMD ["gunicorn", "django_arms.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
