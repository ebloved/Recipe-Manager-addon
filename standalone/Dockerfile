FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc python3-dev libxml2-dev libxslt1-dev libjpeg-dev zlib1g-dev \
    ffmpeg curl jq \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /tmp/req_base.txt
COPY standalone/requirements.txt /tmp/req_standalone.txt
RUN pip install --no-cache-dir -r /tmp/req_standalone.txt

COPY app/ /app/
COPY standalone/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8099
CMD ["/app/entrypoint.sh"]
