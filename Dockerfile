# syntax=docker/dockerfile:1
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY ipmi-mqtt.py ./
COPY ipmi_mqtt_core.py ./
COPY ["config/config - example.yaml", "./config/config.example.yaml"]

VOLUME ["/app/config"]

CMD ["python3", "/app/ipmi-mqtt.py"]
