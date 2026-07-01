FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias primero para aprovechar el cache de Docker
COPY api/requirements.txt ./api/requirements.txt
RUN pip install --no-cache-dir -r api/requirements.txt

# Copiar el código
COPY aglegal/ ./aglegal/
COPY api/ ./api/

# El directorio data se monta como volumen en docker-compose
RUN mkdir -p data/attachments

EXPOSE 8000

CMD ["uvicorn", "api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
