# songmaker-scoring-worker — arq worker with scoring + whisper extras
FROM ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 AS uv
FROM python:3.14.10-slim@sha256:3cabfd7d7aaf394e6040e79fa1eec6ca1c52b74ed9188650472695d9a9326999

# The scoring models, pinned by content: each file is fetched at the commit that a Hub revision
# names and refused unless its sha256 matches (the LFS sha256 from the Hub's file listing; for the
# small plain-git files, the hash of the downloaded file). No library resolves a name at build
# or run time: the worker reads these paths from SCORING_WHISPER_MODEL_DIR and
# SCORING_AUDIOBOX_CHECKPOINT. To move to a new revision, change the revision and every hash of
# that model together. The files are root-owned and read-only (ADD fetches 0600 by default; its
# --chmod would also apply to a directory it creates, so the directories exist first), and they
# come first so a change to the packages or the code below never downloads them again.
RUN install -d -m 0755 /opt/songmaker/models/whisper-large-v3 /opt/songmaker/models/audiobox-aesthetics
# Whisper large-v3 (turbo is faster but hallucinates on about 5 % of songs): the files that
# faster_whisper reads from a model directory.
ARG WHISPER_REVISION=edaa852ec7e145841d8ffdb056a99866b5f0a478
ADD --checksum=sha256:a9306624f5ec14270a014b647e5c316b6e03a662c369758d1b90697a7b0655b9 --chmod=0444 \
    https://huggingface.co/Systran/faster-whisper-large-v3/resolve/${WHISPER_REVISION}/config.json \
    /opt/songmaker/models/whisper-large-v3/config.json
ADD --checksum=sha256:7ccc62c6f2765af1f3b46c00c9b5894426835a05021c8b9c01eecb6dfb542711 --chmod=0444 \
    https://huggingface.co/Systran/faster-whisper-large-v3/resolve/${WHISPER_REVISION}/preprocessor_config.json \
    /opt/songmaker/models/whisper-large-v3/preprocessor_config.json
ADD --checksum=sha256:6d8cbd7cd0d8d5815e478dac67b85a26bbe77c1f5e0c6d76d1ce2abc0e5f21ca --chmod=0444 \
    https://huggingface.co/Systran/faster-whisper-large-v3/resolve/${WHISPER_REVISION}/tokenizer.json \
    /opt/songmaker/models/whisper-large-v3/tokenizer.json
ADD --checksum=sha256:c69260f2ab26d659b7c398f9a2b2b48ed0df16c3b47d7326782fd9cba71690c1 --chmod=0444 \
    https://huggingface.co/Systran/faster-whisper-large-v3/resolve/${WHISPER_REVISION}/vocabulary.json \
    /opt/songmaker/models/whisper-large-v3/vocabulary.json
ARG AUDIOBOX_REVISION=9b1dd8e5df9af7216e836a98974fe3b82c56ded6
ADD --checksum=sha256:a4931a7a01c3e6733352e9d85371835f03bf9135f8b31e1583c23538811d4a32 --chmod=0444 \
    https://huggingface.co/facebook/audiobox-aesthetics/resolve/${AUDIOBOX_REVISION}/checkpoint.pt \
    /opt/songmaker/models/audiobox-aesthetics/checkpoint.pt
ADD --checksum=sha256:69f74147e3334731bc3a76048724833325d2ec74642fb52620eda87352e3d4f1 --chmod=0444 \
    https://huggingface.co/Systran/faster-whisper-large-v3/resolve/${WHISPER_REVISION}/model.bin \
    /opt/songmaker/models/whisper-large-v3/model.bin
ENV SCORING_WHISPER_MODEL_DIR=/opt/songmaker/models/whisper-large-v3 \
    SCORING_AUDIOBOX_CHECKPOINT=/opt/songmaker/models/audiobox-aesthetics/checkpoint.pt

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    gcc \
    git \
    libc6-dev \
    && rm -rf /var/lib/apt/lists/* /var/log/dpkg.log /var/log/alternatives.log /var/log/fontconfig.log /var/log/apt/* \
        /var/cache/ldconfig/aux-cache /var/cache/fontconfig/*

COPY --from=uv /uv /uvx /usr/local/bin/
# Build-only (an ARG, not an ENV, so a uv run in the container keeps its cache): a uv cache in a
# layer is dead weight that differs between builds.
ARG UV_NO_CACHE=1

WORKDIR /app

# Uid and gid 1000 own the volumes and the checkpoints bind mount, and Kubernetes' runAsNonRoot
# can verify only a numeric USER.
RUN groupadd --gid 1000 songmaker \
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash songmaker
RUN chown songmaker:songmaker /app
USER 1000:1000

COPY --chown=songmaker pyproject.toml uv.lock ./
# Building the git-sourced libraries leaves lock files in /tmp whose names are random per build.
RUN uv sync --frozen --no-dev --no-install-project \
    --extra server --extra scoring --extra whisper \
    && rm -f /tmp/uv-*.lock

# Both models load from their fixed paths with the network unreachable and no bytecode written, so
# a missing or wrong file fails this build, not the first job, and no layer changes.
RUN --network=none PYTHONDONTWRITEBYTECODE=1 CUDA_VISIBLE_DEVICES= .venv/bin/python -c \
    "import os; \
    from faster_whisper import WhisperModel; \
    from audiobox_aesthetics.infer import AesPredictor; \
    WhisperModel(os.environ['SCORING_WHISPER_MODEL_DIR'], device='cpu', compute_type='int8', local_files_only=True); \
    AesPredictor(checkpoint_pth=os.environ['SCORING_AUDIOBOX_CHECKPOINT'])"

COPY --chown=songmaker:songmaker src/ src/
COPY --chown=root:root alembic.ini ./
COPY --chown=root:root scripts/arq_healthcheck.py scripts/
# uv_cache.json in the project's dist-info holds the install's wall-clock time and is listed in RECORD;
# uv has no switch to leave it out, and nothing runs `uv sync` in the image again.
RUN uv pip install --python .venv/bin/python --no-deps --no-build \
    --editable . \
    && for marker in .venv/lib/python*/site-packages/*.dist-info/uv_cache.json; do \
        sed -i '/\.dist-info\/uv_cache\.json,/d' "${marker%/*}/RECORD" && rm "$marker"; done # why: The local project adds no resolved dependencies and cannot change locked versions.

# The audiofiles volume is shared with the web container and the other
# workers, and Docker seeds an empty named volume from whichever image
# mounts it first — as root when that image lacks the directory. Every
# image that mounts it must carry it, owned by songmaker.
USER root
RUN chown root:root /app && chown -R root:root src && chmod 755 /app && \
    chmod -R a-w src alembic.ini scripts && \
    install -d -o songmaker -g songmaker /app/data/audio
USER 1000:1000

ENTRYPOINT ["/app/.venv/bin/python", "-m", "songmaker_cli.arq_worker"]
