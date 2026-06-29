FROM python:3.11-slim
WORKDIR /app
COPY services/shared /app/shared
RUN pip install --no-cache-dir /app/shared
COPY services/order-execution-engine /app/order-execution-engine
RUN pip install --no-cache-dir -r /app/order-execution-engine/requirements.txt
ENV PYTHONPATH=/app/order-execution-engine
WORKDIR /app/order-execution-engine
EXPOSE 8006
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8006"]
