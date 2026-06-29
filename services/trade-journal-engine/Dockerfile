FROM python:3.11-slim
WORKDIR /app
COPY services/shared /app/shared
RUN pip install --no-cache-dir /app/shared
COPY services/trade-journal-engine /app/trade-journal-engine
RUN pip install --no-cache-dir -r /app/trade-journal-engine/requirements.txt
ENV PYTHONPATH=/app/trade-journal-engine
WORKDIR /app/trade-journal-engine
EXPOSE 8011
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8011"]
