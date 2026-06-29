FROM python:3.11-slim
WORKDIR /app
COPY services/shared /app/shared
RUN pip install --no-cache-dir /app/shared
COPY services/portfolio-manager /app/portfolio-manager
RUN pip install --no-cache-dir -r /app/portfolio-manager/requirements.txt
ENV PYTHONPATH=/app/portfolio-manager
WORKDIR /app/portfolio-manager
EXPOSE 8008
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8008"]
