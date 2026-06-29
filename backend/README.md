# Backend (FastAPI)

Start the backend (development):

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Celery worker:

```bash
celery -A app.tasks.worker.celery_app worker --loglevel=info
```
