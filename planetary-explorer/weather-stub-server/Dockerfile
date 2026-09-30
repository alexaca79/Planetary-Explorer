FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 appuser
COPY app.py .

ENV PORT=8080 HOST=0.0.0.0
EXPOSE 8080

USER appuser

CMD ["sh", "-c", "exec uvicorn app:app --host ${HOST} --port ${PORT} --no-server-header"]
