FROM python:3.13-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY pv_service ./pv_service

RUN useradd --system --uid 10001 pv
USER pv

EXPOSE 8080
# PySAM holds the GIL during a run, so concurrency comes from worker
# processes; gunicorn reads WEB_CONCURRENCY for the count.
ENV WEB_CONCURRENCY=2
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--timeout", "120", "pv_service.app:create_app()"]
