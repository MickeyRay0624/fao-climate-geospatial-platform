# Pinned MinIO image

Both Compose configurations build this image because the former
`minio/minio:RELEASE.2025-07-23T15-54-02Z` registry image is unavailable.
The server release, command, credentials and persistent `/data` mount stay at
the existing version. The image supports Linux `amd64` and `arm64`.

The Dockerfile downloads the unmodified binary from the [official release](https://github.com/minio/minio/releases/tag/RELEASE.2025-07-23T15-54-02Z)
and verifies the architecture-specific SHA-256 before making it executable.
An unsupported architecture or a mismatched download fails the build.
Compose uses `pull_policy: build` to avoid looking for this project-local
image on Docker Hub; normal Docker build caching still applies.

| Architecture | Binary SHA-256 |
|---|---|
| amd64 | `eef6581f6509f43ece007a6f2eb4c5e3ce41498c8956e919a7ac7b4b170fa431` |
| arm64 | `ec9f48fee97dee7e6ce8fe9f576471bcd52380c035091d8b075b64d606124c7e` |

MinIO is distributed under GNU AGPL version 3. The unchanged upstream
license is included in `LICENSE` and at `/usr/share/licenses/minio/LICENSE`
inside the image. The corresponding source is available at the
[same upstream tag](https://github.com/minio/minio/tree/RELEASE.2025-07-23T15-54-02Z).
This image is a demonstration dependency; the pinned release is not a claim
of current upstream maintenance or production approval.
