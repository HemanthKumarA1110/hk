FROM python:3.11-slim
WORKDIR /app
COPY services/shared /app/shared
RUN pip install --no-cache-dir /app/shared
COPY services/ai-decision-engine /app/ai-decision-engine
RUN pip install --no-cache-dir -r /app/ai-decision-engine/requirements.txt
ENV PYTHONPATH=/app/ai-decision-engine
WORKDIR /app/ai-decision-engine
EXPOSE 8004
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8004"]
