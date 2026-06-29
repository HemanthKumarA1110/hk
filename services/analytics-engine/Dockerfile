FROM python:3.11-slim
WORKDIR /app
COPY services/shared /app/shared
RUN pip install --no-cache-dir /app/shared
COPY services/analytics-engine /app/analytics-engine
RUN pip install --no-cache-dir -r /app/analytics-engine/requirements.txt
ENV PYTHONPATH=/app/analytics-engine
WORKDIR /app/analytics-engine
EXPOSE 8010
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010"]
