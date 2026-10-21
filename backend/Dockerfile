FROM python:3.13-slim
WORKDIR /app
COPY backend/server.py /app/server.py
COPY backend/schema.sql /app/schema.sql
ENV PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "server.py"]
