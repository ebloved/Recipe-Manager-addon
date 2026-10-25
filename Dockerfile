ARG BUILD_FROM
FROM ${BUILD_FROM}

# Установка системных зависимостей (Debian-база HA)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip python3-dev \
    gcc libxml2-dev libxslt1-dev libjpeg-dev zlib1g-dev \
    ffmpeg jq curl \
    && rm -rf /var/lib/apt/lists/*

# Создаём venv, так как run.sh ожидает его в /opt/venv
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Устанавливаем python-зависимости
COPY requirements.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /app
COPY app/ /app/
COPY run.sh /app/run.sh
RUN chmod +x /app/run.sh
COPY config.yaml /app/config.yaml

# Запускаем через bashio
CMD [ "/app/run.sh" ]
