FROM evernode/sashimono:hp.latest-ubt.20.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HP_STATE_DIR=/hp/state

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN python3 -m pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

RUN mkdir -p /hp/state

EXPOSE 9009

ENTRYPOINT ["python3"]
CMD ["main.py"]
