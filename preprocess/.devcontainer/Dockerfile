# syntax=docker/dockerfile:1

FROM debian:bookworm-slim AS llama-builder
ARG LLAMA_CPP_REF=427291b5b34cd914a31b3fd3b61a68f6184f4b9f
RUN apt-get update && apt-get install -y --no-install-recommends build-essential cmake git ca-certificates libssl-dev
RUN git clone https://github.com/ggml-org/llama.cpp.git /src/llama.cpp && cd /src/llama.cpp && git checkout "$LLAMA_CPP_REF"
RUN cmake -S /src/llama.cpp -B /src/llama.cpp/build -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=OFF -DGGML_CUDA=OFF -DGGML_METAL=OFF -DBUILD_SHARED_LIBS=OFF -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_SERVER=ON && cmake --build /src/llama.cpp/build --target llama-server -j 2

FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

COPY --from=llama-builder /src/llama.cpp/build/bin/llama-server /usr/local/bin/llama-server

ENV SURYA_INFERENCE_BACKEND=llamacpp SURYA_INFERENCE_PARALLEL=1 LLAMA_CPP_NGL=0

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    TORCH_DEVICE=cpu

RUN rm -f /etc/apt/sources.list.d/yarn.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 libgomp1 libssl3 poppler-utils \
    && mkdir -p /home/vscode/.cache \
    && chown -R vscode:vscode /home/vscode/.cache \
    && rm -rf /var/lib/apt/lists/*

COPY preprocess/requirements/requirements.txt preprocess/requirements/requirements-dev.txt /tmp/paper-reader-requirements/

RUN python -m pip install --upgrade pip \
    && python -m pip install \
        --index-url https://download.pytorch.org/whl/cpu \
        "torch==2.7.1" \
        "torchvision==0.22.1" \
    && python -m pip install -r /tmp/paper-reader-requirements/requirements-dev.txt \
    && python -c "import torch, torchvision; assert torch.__version__.startswith('2.7.1'); assert torchvision.__version__.startswith('0.22.1'); assert not torch.cuda.is_available()"

ENV FONT_PATH=/home/vscode/.cache/marker/fonts/GoNotoCurrent-Regular.ttf

RUN llama-server --version
