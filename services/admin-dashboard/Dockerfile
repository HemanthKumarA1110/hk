FROM python:3.11-slim
WORKDIR /app
COPY services/shared /app/shared
RUN pip install --no-cache-dir /app/shared
COPY services/admin-dashboard /app/admin-dashboard
RUN pip install --no-cache-dir -r /app/admin-dashboard/requirements.txt
ENV PYTHONPATH=/app/admin-dashboard
WORKDIR /app/admin-dashboard
EXPOSE 8012
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8012"]
