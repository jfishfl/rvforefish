# 0.5.0-rc1 release audit

## Deployment boundary

This release is approved for a **TX-disarmed monitor-only deployment**.  It
preserves the already tested temporary source-label/current-limit shortcut:

- TM-102 running plus two stable AC legs for 60 seconds -> Generator / 50 A.
- Generator stopped, stale, or service shutdown -> Grid / 30 A.

It cannot transmit RV-C control while the deployed configuration keeps
`monitor_only=true`, `source_address=null`, and every feature payload gate
false.

## Generator-demand corrections

- DGN `0x1FEFF`, CAN priority 6.
- Cooperative start/keepalive payload `01FCFFFFFFFFFFFF`.
- Cooperative release payload `00FCFFFFFFFFFFFF`.
- The Total Coach panel's observed `5D`/`5C` manual-override frames are never
  impersonated.
- A configured TX source is rejected if stock RV-C currently reports that NAD.

## Implemented safety mechanisms

- Ownership marker is written before the first demand frame.
- Demand release is retried and ownership is retained until fresh TM-102
  aggregate demand reports false.
- Restart recovery fails closed when a stale marker cannot be safely released.
- Normal stop requires both direct VE.Bus input-leg currents below the
  configured threshold for a continuous confirmation interval and then a full
  300-second unloaded cooldown.
- Any renewed load resets the cooldown.
- Maximum-run and stop-escalation deadlines remain explicit configuration
  gates.

## Verification result

- Python source compilation: pass.
- Offline unit/replay/safety suite: **138 tests pass**.
- Deployment shell syntax: pass.
- Boot dependency handling waits up to 120 seconds for stock RV-C/`vecan0`;
  manual enable and release installation still fail immediately on a missing
  dependency.
- TX-disarmed deployment configuration: validation required again on Cerbo.

## Gates intentionally left open

- Attended cooperative-demand start/stop test.
- Live load-threshold calibration on both generator-fed legs.
- Process-loss and safe Cerbo-power-loss orphan-demand behavior.
- Authoritative ATS/transfer-source evidence; the current source shortcut
  remains a labeled heuristic.

Until those tests pass, the normal generator feature gate remains disabled.

## Live disarmed deployment

Installed on 2026-08-10 after matching the uploaded SHA-256 digest.  The Cerbo
created rollback backup `/data/apps/foretravel-rvc-backup-20260810-220536`.
Immediate validation found:

- 0.5.0-rc1 service and stock `dbus-rv-c.vecan0` both up.
- Signal K remained off.
- Generator status stopped, aggregate demand false, own demand false, phase
  idle, and no ownership marker.
- All switch controls hidden and no `com.victronenergy.generator.*` service.
- Zero `AUDIT TX` records and zero new service errors.
- CAN remained ERROR-ACTIVE with zero live transmit/receive error counters.
- AggregateBatteries connected with four online and zero stale; DVCC continued
  to use the aggregate service; two Ruuvi services remained registered.

The next commissioning step is attended live testing, not unattended arming.
