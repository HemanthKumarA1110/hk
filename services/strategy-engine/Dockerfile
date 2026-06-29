FROM python:3.11-slim
WORKDIR /app
COPY services/shared /app/shared
RUN pip install --no-cache-dir /app/shared
COPY services/strategy-engine /app/strategy-engine
RUN pip install --no-cache-dir -r /app/strategy-engine/requirements.txt
ENV PYTHONPATH=/app/strategy-engine
WORKDIR /app/strategy-engine
EXPOSE 8003
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003"]
