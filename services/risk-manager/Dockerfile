FROM python:3.11-slim
WORKDIR /app
COPY services/shared /app/shared
RUN pip install --no-cache-dir /app/shared
COPY services/risk-manager /app/risk-manager
RUN pip install --no-cache-dir -r /app/risk-manager/requirements.txt
ENV PYTHONPATH=/app/risk-manager
WORKDIR /app/risk-manager
EXPOSE 8005
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8005"]
