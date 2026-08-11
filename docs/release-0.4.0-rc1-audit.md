# Release 0.4.0-rc1 audit

Built 2026-07-17 as an enhanced **monitor-only** candidate.  It has not been
installed on the Cerbo; the immutable 0.3.0 baseline continues its original
24-hour soak.

## Artifact identity

- Archive: `dist/foretravel-rvc-release-0.4.0-rc1.tgz`
- SHA-256 authority: adjacent
  `dist/foretravel-rvc-release-0.4.0-rc1.sha256`
- The digest is deliberately not copied into this embedded audit page: doing
  so would make the archive hash self-referential and stale after every rebuild.
- Members: 40
- Packaged version: `0.4.0`
- Sealed 0.3.0 SHA-256 remains
  `1e7191318654d4b870977d6ece212b582d14ca092b4419fb91d7dcb2fbe6060f`

## Safety gates in the packaged configuration

- `monitor_only = true`
- Water-pump TX disabled and payload unvalidated
- Autofill Stop and Start TX disabled and payload unvalidated
- Generator-demand TX disabled and payload unvalidated
- Source-label writes disabled
- No generator or autofill maximum run time is silently inferred

## Verification performed

- 117 offline unit tests passed.
- Python bytecode compilation passed for source and tests.
- Example and packaged JSON parsed and validated.
- Packaged application validated itself as monitor-only with CAN TX unarmed.
- All packaged shell entry points passed `sh -n`.
- Static source scan found no Victron setting write, AC-input-type write, or
  direct `GENERATOR_COMMAND 0x1FFDA` implementation.
- Corrected pressure/current sentinel handling was checked against RV-C 2026
  tables 5.3 and 6.29.2b.
- Generator and autofill ownership markers are created before Start TX.
- Release/Stop retries and marker clearing require authoritative TM-102 state;
  stale markers with cleanup TX unarmed refuse startup.

## Deployment gate

Do not install this candidate until the original 0.3.0 24-hour soak reaches
its expected 289 TSV lines and passes the soak analyzer.  After installation,
run a second monitor-only soak and prove zero TX before enabling one staged
control at a time.
