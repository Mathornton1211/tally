FROM node:24-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
# tesseract reads the amount and date off a receipt photo. Optional at runtime:
# tally.receipts falls back to manual entry when it is not installed.
# postgresql-client is NOT optional: db.migrate takes a dump before any schema
# change on a database that has data in it, and refuses to migrate without one.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr postgresql-client \
    && apt-get clean \
    && find /var/lib/apt/lists -type f -delete
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY tally/ ./tally/
COPY --from=web /web/dist ./web/dist
RUN useradd -r -u 10001 tally
# Receipt images live here, on a bind mount, not in Postgres.
RUN mkdir -p /data/receipts && chown tally:tally /data/receipts
USER tally
EXPOSE 8000
CMD ["uvicorn", "tally.api:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
