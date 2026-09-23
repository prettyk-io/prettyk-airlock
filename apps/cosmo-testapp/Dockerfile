# Cosmo TestApp — multi-stage docker build

FROM python:3.12-slim AS build
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim AS runtime
WORKDIR /app
COPY --from=build /install /usr/local
COPY app.py .

ENV PYTHONUNBUFFERED=1 \
    TESTAPP_PORT=8000 \
    TESTAPP_DB=memory

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=3 --start-period=10s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/ready', timeout=3).status==200 else 1)"

CMD ["sh", "-c", "exec uvicorn app:app --host 0.0.0.0 --port ${TESTAPP_PORT}"]