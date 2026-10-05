ARG BUILD_FROM
FROM ${BUILD_FROM}

# Системные пакеты
RUN apk add --no-cache \
        ffmpeg \
        nodejs \
        jq \
        ca-certificates \
        wget

# yt-dlp
RUN wget -O /usr/local/bin/yt-dlp \
        https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp \
    && chmod a+rx /usr/local/bin/yt-dlp

WORKDIR /app
ENV PYTHONPATH="/app"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir curl_cffi

COPY app/ /app/
RUN mkdir -p /downloads /data

EXPOSE 8099

COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]