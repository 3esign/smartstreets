FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY frontend ./frontend

# SQLite lives in /tmp (writable on serverless/container hosts).
ENV SMARTSTREET_DB=/tmp/smartstreet.db
EXPOSE 8000

# $PORT is provided by Render/Railway/Fly; defaults to 8000 locally.
CMD ["sh", "-c", "uvicorn backend.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
