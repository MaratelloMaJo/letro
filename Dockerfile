FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8

WORKDIR /app

RUN adduser --disabled-password --gecos "" letro

COPY . /app

RUN chown -R letro:letro /app

USER letro

CMD ["python", "-m", "letro.verify"]
