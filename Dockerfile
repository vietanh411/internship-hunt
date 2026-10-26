# Dashboard + API + in-process 09:00 America/Chicago scheduler, for any always-on
# host (VPS, Render, Railway, Fly.io). Pair with PostgreSQL via DATABASE_URL.
FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HUNT_HOST=0.0.0.0 HUNT_PORT=8000
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt && python -m playwright install --with-deps chromium
COPY . .
COPY --from=ui /ui/dist ./frontend/dist
RUN useradd -m hunt && chown -R hunt /app
USER hunt
EXPOSE 8000
CMD ["python", "-m", "hunt", "serve"]
