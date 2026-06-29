FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev && rm -rf /var/lib/apt/lists/*

COPY services/shared /app/shared
RUN pip install --no-cache-dir /app/shared

COPY services/auth-service /app/auth-service
RUN pip install --no-cache-dir -r /app/auth-service/requirements.txt

ENV PYTHONPATH=/app/auth-service
WORKDIR /app/auth-service

EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
