# Stage 1: build the React frontend
FROM node:20-slim AS ui-builder
WORKDIR /app/ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build

# Stage 2: Python runtime + built UI
FROM python:3.11-slim
WORKDIR /app

COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

COPY data/ ./data/
COPY models/ ./models/
COPY --from=ui-builder /app/ui/dist ./ui/dist

EXPOSE 8000
CMD uvicorn src.api:app --host 0.0.0.0 --port ${PORT:-8000}
