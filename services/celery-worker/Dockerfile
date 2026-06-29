FROM python:3.11-slim
WORKDIR /app
COPY services/shared /app/shared
RUN pip install --no-cache-dir /app/shared
COPY services/celery-worker /app/celery-worker
RUN pip install --no-cache-dir -r /app/celery-worker/requirements.txt
ENV PYTHONPATH=/app/celery-worker
WORKDIR /app/celery-worker
CMD ["celery", "-A", "app.worker.celery_app", "worker", "--loglevel=info"]
