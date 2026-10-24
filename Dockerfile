FROM node:26.12.1-alpine@sha256:40cd011b55415bc894e45b02fdd5a5dfde056921b7d23a64c74f80497af48797 AS frontend-deps
WORKDIR /frontend
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN apk add --no-cache zip
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN npm install --global corepack@0.36.0 && corepack enable && pnpm install --frozen-lockfile

FROM frontend-deps AS frontend-build
COPY frontend .
COPY VERSION /VERSION
COPY MIN_NATIVE_VERSION /MIN_NATIVE_VERSION
COPY MIN_DESKTOP_VERSION /MIN_DESKTOP_VERSION
# The artwork credits, which every build writes into THIRD_PARTY_NOTICES.txt
# (frontend/scripts/third-party-notices.mjs reads ../NOTICE.md).
COPY NOTICE.md /NOTICE.md
ARG VITE_API_URL=/api/v1
ARG VITE_VERSION_SUFFIX=
# The dev signing key's public half: the dev app accepts updates signed with it.
ARG VITE_OTA_DEV_PUBLIC_KEY=
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_VERSION_SUFFIX=$VITE_VERSION_SUFFIX
ENV VITE_OTA_DEV_PUBLIC_KEY=$VITE_OTA_DEV_PUBLIC_KEY
# Browser SPA build (base "/") served by the backend at /app/static.
RUN pnpm run build
# The document editor for the server (backend/app/services/editor_engine.py).
RUN pnpm build:editor-server
# Capacitor-flavored OTA bundle (base "", __IS_CAPACITOR__=true) shipped at /app/ota so the
# native app can download the web bundle matching this backend version. build:capacitor
# overwrites dist/, so stash the browser build first, then zip the capacitor build with
# index.html at the zip root (cd dist before zipping — do NOT nest under dist/).
RUN cp -r dist /tmp/browser-dist \
 && pnpm build:capacitor \
 && mkdir -p /ota \
 && (cd dist && zip -qr /ota/bundle.zip .) \
 && sha256sum /ota/bundle.zip | cut -d' ' -f1 > /ota/bundle.sha256 \
 && rm -rf dist && mv /tmp/browser-dist dist
# The statement the app installs an update on, signed when the build is given
# the release key as the secret `ota_signing_key` (see scripts/sign-ota.mjs).
RUN --mount=type=secret,id=ota_signing_key \
    node scripts/sign-ota.mjs /ota "$(cat /VERSION)${VITE_VERSION_SUFFIX}" \
      "$(cat /MIN_NATIVE_VERSION)" "$(cat /MIN_DESKTOP_VERSION)" /run/secrets/ota_signing_key

# The virtualenv is built in a stage of its own, on the same base, and copied
# into the runtime below. It depends on the lockfile alone, so a build reuses it
# until the lockfile changes; built in the runtime stage it sat above the
# package refresh, which every published build runs again, and was rebuilt
# (and stored in the build cache again) every time. uv never reaches the image.
FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS backend-deps
# uv (pinned, hash-checked) for native, lockfile-based dependency installs.
# From PyPI rather than uv's ghcr.io image, which refused pulls under load.
COPY backend/uv-requirements.txt /tmp/
RUN pip install --no-cache-dir --disable-pip-version-check --root-user-action=ignore \
        --only-binary=:all: --require-hashes -r /tmp/uv-requirements.txt
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_PREFERENCE=only-system
WORKDIR /app
# No app source needed: this is a package=false project. --no-dev keeps
# test/lint tooling out of the runtime image.
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-dev

# The stages that depend on the lockfiles alone, which is all the CI build cache
# keeps (docker-image.yml): every other layer differs from one build to the
# next. Nothing ships from here, and an image build never builds it.
FROM scratch AS dependencies
COPY --from=frontend-deps /frontend/package.json /frontend/
COPY --from=backend-deps /app/pyproject.toml /backend/

FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS backend-runtime
ARG VERSION=0.1.0
LABEL org.opencontainers.image.version="${VERSION}"
LABEL org.opencontainers.image.title="Initiative"
LABEL org.opencontainers.image.description="Initiative project management application"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# dist-upgrade, not upgrade. `apt-get upgrade` leaves a package at its current
# version when the new one "cannot be upgraded without changing the install
# status of another package", and it never removes one -- so a security update
# that needs a dependency change is held back, silently, while this line still
# looks like it applied everything available.
#
# Then assert it: a simulated pass must find nothing left to install. Without
# that the claim "available security updates are applied" is a claim nothing
# checks, and the image that quietly kept a vulnerable package looks exactly
# like the image that had nothing to keep.
#
# This layer sits above the application so a code change reuses it. A build
# that must apply today's updates passes a new APT_REFRESH, which is all it
# takes to run this layer again, and every layer above it.
ARG APT_REFRESH=
RUN apt-get update \
    && apt-get dist-upgrade -y \
    && apt-get install -y --no-install-recommends gosu \
    && remaining="$(apt-get --simulate dist-upgrade | grep '^Inst ' || true)" \
    && if [ -n "$remaining" ]; then \
         echo "packages still upgradable after dist-upgrade:" >&2; \
         echo "$remaining" >&2; \
         exit 1; \
       fi \
    && rm -rf /var/lib/apt/lists/*
# uv is a build-time tool: it synced the venv in backend-deps and is never
# invoked again — entrypoint.sh and start.sh run everything out of
# /app/.venv/bin. Copying only /app keeps both binaries out of the image, and
# with them a package manager and its own dependencies, which have no
# reason to ship with this application.
#
# This is the first thing written to /app, so the directory comes from
# backend-deps with its times too, and an unchanged venv is the same layer
# every build. Anything that wrote to /app before it would give /app a new
# time, and the 340 MB layer a new digest, on every build.
COPY --from=backend-deps /app /app
WORKDIR /app
COPY backend/ .
# Put the synced venv on PATH so uvicorn/alembic/python resolve to it
ENV PATH="/app/.venv/bin:$PATH"
COPY VERSION ./VERSION
COPY MIN_NATIVE_VERSION ./MIN_NATIVE_VERSION
COPY MIN_DESKTOP_VERSION ./MIN_DESKTOP_VERSION
# Which build this is. The dev build passes `dev`, and only a dev image names the
# dev app in its passkey association files (app/core/native_apps.py).
ARG IMAGE_CHANNEL=release
RUN echo "$IMAGE_CHANNEL" > ./IMAGE_CHANNEL
COPY CHANGELOG.md ./CHANGELOG.md
COPY --from=frontend-build /frontend/dist ./static
COPY --from=frontend-build /frontend/dist-editor/editor.js ./editor/editor.js
COPY --from=frontend-build /ota/ ./ota/
COPY backend/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && mkdir -p /app/uploads
ENTRYPOINT ["/entrypoint.sh"]
CMD ["sh", "start.sh"]
