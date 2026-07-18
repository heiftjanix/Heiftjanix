# AI-Systems — Web-App (aus dem Repo-Root bauen):
#   docker build -t ai-systems -f ai_systems/Dockerfile .
FROM python:3.12-slim

WORKDIR /app
COPY ai_systems/requirements.txt /app/ai_systems/requirements.txt
RUN pip install --no-cache-dir -r /app/ai_systems/requirements.txt

COPY ai_systems /app/ai_systems

# SQLite-Datei außerhalb des Images (Volume), siehe docker-compose.yml
ENV AI_SYSTEMS_DB=/data/ai_systems.db
VOLUME ["/data"]

EXPOSE 8010
CMD ["uvicorn", "ai_systems.app:app", "--host", "0.0.0.0", "--port", "8010"]
