# Changelog

Notable changes to pysam-pv. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- `.github/workflows/docker-publish.yml` publishes the image to
  `ghcr.io/enerplanet/pysam-pv` on every `v*.*.*` tag, tagged without the
  `v` prefix.

### Changed

- `environment/docker-compose.yml` names the published image,
  `ghcr.io/enerplanet/pysam-pv:${PV_SERVICE_IMAGE_TAG:-latest}`, in place of
  `PV_SERVICE_IMAGE` (default `pysam-pv:local`). `--build` still builds the
  checkout under that name.

- `environment/docker-compose.yml` pins the Compose project to `pysam-pv`
  and names the service `api`, so the container is `pysam-pv-api-1`. On
  `tentacron-net` it answers to `pysam-pv` and, until callers move,
  `pv-service`.
