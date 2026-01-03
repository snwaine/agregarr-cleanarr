FROM python:3.12-alpine

WORKDIR /app

RUN apk add --no-cache tzdata && \
    adduser -D -u 1000 appuser

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py /app/app.py
COPY entrypoint.sh /app/entrypoint.sh

RUN chmod +x /app/entrypoint.sh

USER root
ENTRYPOINT ["/app/entrypoint.sh"]
