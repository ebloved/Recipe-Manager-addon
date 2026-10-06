ARG BUILD_FROM
FROM ${BUILD_FROM}

# --- Системные пакеты ------------------------------------------------------

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        python3-venv \
        ffmpeg \
        jq \
        ca-certificates \
        wget \
        curl \
        gnupg \
    && rm -rf /var/lib/apt/lists/*

# --- Node.js 22 (для yt-dlp n-challenge) -----------------------------------
# Debian-репозиторий содержит устаревший Node.js, ставим свежий из NodeSource.
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# --- yt-dlp ----------------------------------------------------------------

RUN wget -O /usr/local/bin/yt-dlp \
        https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp \
    && chmod a+rx /usr/local/bin/yt-dlp

WORKDIR /app
ENV PYTHONPATH="/app"

COPY requirements.txt .

# --- Python venv -----------------------------------------------------------

RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir curl_cffi \
    && python -c "import frontmatter; print('frontmatter OK')" \
    && python -c "import fastapi, uvicorn, bs4, recipe_scrapers, httpx; print('all deps OK')"

# --- Приложение ------------------------------------------------------------

COPY app/ /app/

RUN mkdir -p /downloads /data

EXPOSE 8099

COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]