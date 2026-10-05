ARG BUILD_FROM
FROM ${BUILD_FROM}

# Системные пакеты
RUN apk add --no-cache \
        python3 \
        py3-pip \
        py3-virtualenv \
        ffmpeg \
        nodejs \
        jq \
        ca-certificates \
        wget

# yt-dlp через wget
RUN wget -O /usr/local/bin/yt-dlp \
        https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp \
    && chmod a+rx /usr/local/bin/yt-dlp

WORKDIR /app
ENV PYTHONPATH="/app"

COPY requirements.txt .

# Изолированное venv
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir curl_cffi \
    && python -c "import frontmatter; print('frontmatter OK:', frontmatter.__version__)" \
    && python -c "import fastapi, uvicorn, bs4, recipe_scrapers, httpx; print('all deps OK')"
COPY app/ /app/

RUN mkdir -p /downloads /data

EXPOSE 8099

COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]