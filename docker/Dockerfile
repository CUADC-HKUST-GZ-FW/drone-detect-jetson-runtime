FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      iproute2 \
      procps \
      python3 \
      python3-pip \
      tini \
      util-linux \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements-webui.txt /app/requirements-webui.txt
RUN python3 -m pip install --no-cache-dir -r /app/requirements-webui.txt

COPY webui /app/webui

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python3", "-m", "uvicorn", "webui.app:app", "--host", "0.0.0.0", "--port", "18080"]
