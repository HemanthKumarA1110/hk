FROM python:3.11-slim
WORKDIR /app
COPY services/shared /app/shared
RUN pip install --no-cache-dir /app/shared
COPY services/alert-engine /app/alert-engine
RUN pip install --no-cache-dir -r /app/alert-engine/requirements.txt
ENV PYTHONPATH=/app/alert-engine
WORKDIR /app/alert-engine
EXPOSE 8009
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8009"]
