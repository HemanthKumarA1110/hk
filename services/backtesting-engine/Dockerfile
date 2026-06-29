FROM python:3.11-slim
WORKDIR /app
COPY services/shared /app/shared
RUN pip install --no-cache-dir /app/shared
COPY services/backtesting-engine /app/backtesting-engine
RUN pip install --no-cache-dir -r /app/backtesting-engine/requirements.txt
ENV PYTHONPATH=/app/backtesting-engine
WORKDIR /app/backtesting-engine
EXPOSE 8007
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8007"]
