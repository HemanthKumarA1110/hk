FROM python:3.11-slim

WORKDIR /app

COPY services/shared /app/shared
RUN pip install --no-cache-dir /app/shared

COPY services/api-gateway /app/api-gateway
RUN pip install --no-cache-dir -r /app/api-gateway/requirements.txt

ENV PYTHONPATH=/app/api-gateway
WORKDIR /app/api-gateway

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
