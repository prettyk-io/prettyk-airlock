# PTY-SANDBOX-1: sandbox lifecycle service (default-off, compose profile "pty").
#
# Владеет docker.sock и создаёт ephemeral-контейнеры сессий из образа
# pty-sandbox-base:local (профиль изоляции §5 — COS-189).
# Внутренний сервис: слушает cosmo-net (публикация — только 127.0.0.1 для диагностики).
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py logic.py ./

EXPOSE 8190

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8190", "--log-level", "info"]
