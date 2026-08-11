# Changelog

## v0.5.0b4 - initial SetupHelper candidate

- Import the exact `0.5.0-rc4` source currently deployed on the Foretravel
  Cerbo GX.
- Add a SetupHelper-compatible service package named `rvforefish`.
- Store configuration and generator ownership state outside the downloaded
  package so updates cannot silently replace safety settings.
- Ship a fail-closed default: monitor-only, no RV-C transmission, no control
  features, no source-label writes, and no automatic current-limit changes.
- Refuse to replace an existing manually managed `foretravel-rvc` service.
- Preserve an explicit, non-destructive migration path from the legacy
  `/data/apps/foretravel-rvc` deployment.
- Restrict the initial package to the tested Venus OS v3.75 baseline.
- Add automated package checks and the full 144-test replay/unit suite.
