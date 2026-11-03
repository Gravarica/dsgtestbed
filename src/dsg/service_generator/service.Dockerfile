FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libsm6 libxext6 zbar-tools \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "flask>=3.0" "prometheus-client>=0.16" "pyyaml>=6" "requests>=2.31" "pytest>=7"

ARG SERVICE_PATH
COPY ${SERVICE_PATH}/requirements.txt ${SERVICE_PATH}/apt.tx[t] /service/
RUN if [ -s /service/apt.txt ]; then \
      apt-get update \
      && xargs -a /service/apt.txt apt-get install -y --no-install-recommends \
      && rm -rf /var/lib/apt/lists/*; \
    fi
RUN pip install --no-cache-dir -r /service/requirements.txt

COPY src/dsg /app/dsg
COPY ${SERVICE_PATH} /service

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    SERVICE_DIRECTORY=/service \
    RECORDS_DIRECTORY=/records

EXPOSE 8080 8000
CMD ["python", "-m", "dsg.service_runtime"]
