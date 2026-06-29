FROM python:3.11-slim
WORKDIR /app
COPY services/shared /app/shared
RUN pip install --no-cache-dir /app/shared
COPY services/market-data-service /app/market-data-service
RUN pip install --no-cache-dir -r /app/market-data-service/requirements.txt
ENV PYTHONPATH=/app/market-data-service
WORKDIR /app/market-data-service
EXPOSE 8002
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
