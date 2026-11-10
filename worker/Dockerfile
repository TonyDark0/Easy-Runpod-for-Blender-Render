FROM nvidia/cuda:12.8.1-runtime-ubuntu24.04
ARG BLENDER_VERSION=4.5.4
ARG BLENDER_SERIES=4.5
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl xz-utils python3 python3-venv libgl1 libx11-6 libxi6 libxrender1 libxfixes3 libxkbcommon0 libsm6 && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL "https://download.blender.org/release/Blender${BLENDER_SERIES}/blender-${BLENDER_VERSION}-linux-x64.tar.xz" | tar -xJ -C /opt && ln -s "/opt/blender-${BLENDER_VERSION}-linux-x64/blender" /usr/local/bin/blender
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility,graphics
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install runpod==1.7.13
WORKDIR /app
COPY addon/runpod_render/transport.py .
COPY worker/handler.py worker/render.py ./
CMD ["/opt/venv/bin/python", "handler.py"]

