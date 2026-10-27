FROM golang:1.26.10-alpine@sha256:9ce231b28998b32e116927c61aa5c406183061d4f3f2d61b292c88e7f6bdf7ca AS source
RUN apk add --no-cache python3
WORKDIR /build
ADD --checksum=sha256:6f18daf5ddbc44230ab37486702c709ef62668a939970f0ccaaa85e6c5cb1efe https://api.github.com/repos/QuantumNous/new-api/tarball/v1.0.0-rc.47 /tmp/newapi.tar.gz
RUN tar -xzf /tmp/newapi.tar.gz --strip-components=1
COPY apply.py /integration/apply.py
COPY overlay /integration/overlay
RUN python3 /integration/apply.py /build

FROM oven/bun:1.4.4@sha256:1d22548f177f4ff38e0c15baa3c2c46c6c2060ba2d1bc573bb4720b407548f1d AS web
WORKDIR /build/web
COPY --from=source /build/web ./
COPY --from=source /build/VERSION /build/VERSION
RUN bun install --frozen-lockfile
RUN VITE_REACT_APP_VERSION=$(cat /build/VERSION) bun run build

FROM source AS binary
ENV CGO_ENABLED=0 GOWORK=off
ARG TARGETOS
ARG TARGETARCH
ENV GOOS=${TARGETOS} GOARCH=${TARGETARCH}
COPY --from=web /build/web/dist /build/web/dist
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build go test ./common ./pkg/billingexpr ./relay/channel/openai ./controller ./setting/billing_setting ./setting/ratio_setting -run 'TestAdmissionBound|TestActvero|TestDeepSeekBuiltin|TestImageModelBuiltin|TestGPT6AstraBuiltin' -count=1
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build go build -trimpath -ldflags="-s -w" -o /new-api .

FROM debian:bookworm-slim@sha256:f06537653ac770703bc45b4b113475bd402f451e85223f0f2837acbf89ab020a
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates tzdata wget && rm -rf /var/lib/apt/lists/*
COPY --from=binary /new-api /new-api
COPY --from=source /build/LICENSE /build/NOTICE /build/THIRD-PARTY-LICENSES.md /licenses/
WORKDIR /data
EXPOSE 3000
ENTRYPOINT ["/new-api"]
