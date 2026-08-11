# Foretravel SilverLeaf RV-C integration

Safety-gated integration of the 2006 Foretravel Phenix SilverLeaf TM-102 with
Victron Venus OS on a Cerbo GX Mk2.

> [!CAUTION]
> This is vehicle-control software developed against one specific coach. The
> SetupHelper package ships fail-closed and read-only. Do not enable an RV-C
> command or Victron write gate merely because the package installed.

The project has four separate responsibilities:

1. Decode authoritative TM-102 RV-C status for the generator, its complete
   read-only AGS/START configuration, water pump, autofill, tanks, ambient
   temperatures, and AC source.
2. Publish native Venus telemetry without creating a second generator owner.
3. Offer explicitly enabled, feedback-verified pump, autofill, and cooperative
   generator-demand controls in the Venus switch pane.
4. Classify shore, generator, and inverter operation conservatively so the UI
   never labels an unaccepted or merely requested source as active.

## Current safety posture

- Imported application source: **0.5.0-rc4**, byte-for-byte matched to the
  deployed Cerbo source before publication.
- Offline validation: **144 replay and unit tests passing**.
- Package default: **monitor-only** with no CAN transmission.
- Control features: **all disabled** in `config.default.json`.
- Victron writes: **source relabeling and automatic current-limit changes are
  disabled** in the package default.
- Operational configuration: stored in `/data/rvforefish-data/config.json`,
  outside the GitHub-managed package so an update cannot replace it.
- Live Cerbo: **not changed by publishing or downloading this repository**.

The public package default is completely read-only: it does not transmit RV-C,
relabel the AC source, change the input current limit, write DVCC/AGS, or
operate physical relays. An existing coach configuration may contain an
attended and separately approved temporary source-label/current-limit
heuristic; that operational configuration is deliberately not shipped by this
repository and is never substituted during an update.

The first live projection matched the captured coach state: pump on, autofill
off, generator stopped, no generator demand, and 75,495 runtime minutes.  The
generator service contains no remote-start paths and Venus created no
`com.victronenergy.generator.*` control owner.

The current 0.5.0-rc4 worktree candidate passes 144 offline tests.  Its first
deployed 0.1 resource sample used 6
CPU ticks in 10 seconds (about 0.6% of one core), 16 MiB RSS, an 8 KiB bounded
log, and 328 KiB of application storage.  A direct monitor-only D-Bus write was
rejected and the switch State remained unchanged.

The 2026-08-10 Cerbo installation passed on-device configuration preflight,
started alongside stock `dbus-rv-c.vecan0`, and retained rollback backup
`/data/apps/foretravel-rvc-backup-20260810-220536`.  Post-install checks found
zero `AUDIT TX` records, zero new service errors, no generator-control D-Bus
owner, hidden controls, generator stopped with no demand, both Ruuvi services
present, and AggregateBatteries connected with all four batteries online.

The 2026-08-11 rc3 installation also passed on-device monitor-only preflight
and retained rollback backup
`/data/apps/foretravel-rvc-backup-20260811-002150`.  Its post-install audit
found the generator stopped with all demand classes false, no ownership marker,
Grid/30 A, four online and zero stale BLE batteries, AggregateBatteries still
selected for BMS control, three Ruuvi services, stock RV-C up, Signal K down,
and zero live vecan0 error counters.

Version 0.3.0 additionally understands all eleven fixed TM-102 AGS criterion
instances, current and legacy criterion counters, generator starter timing,
standard AGS safety configuration, and proprietary stop-policy reports.  Every
one of those paths is read-only.  Because the criteria normally report only on
request, they populate after the Total Coach START pages request them; the
bridge never transmits a configuration query while monitor-only.

Version 0.4.0 corrected tank percentage scaling to use the transmitted
resolution, decodes complete pump/autofill status plus the documented TM-102
configuration reports, and publishes explicit stale/result/interlock
diagnostics.  Autofill start requires fresh pump, fill, and fresh-tank
status; a valid nonzero TM-102 timeout; the configured pressure/hookup policy;
and an explicit secondary bridge maximum run time.  Stop works with stale
status, and a persistent cleanup marker causes an unclean restart to send a
fail-safe stop until the TM-102 actually reports Off.

Generator demand uses the same marker-before-TX ordering.  Release is retried,
and its marker remains until fresh Network Demand status proves False; a
stale marker with release TX unarmed makes startup fail closed.  Version
0.5.0 adds RV-C priority-6 cooperative demand using
`01FCFFFFFFFFFFFF` for demand and `00FCFFFFFFFFFFFF` for release.  It does not
copy the Total Coach panel's `5D/5C` manual-override frames.  Both VE.Bus input
leg currents must remain below a configured threshold continuously, followed
by a full five-minute unloaded cooldown, before a normal release.  Live
orphan-demand and Cerbo-power-loss testing remains mandatory before the
generator feature gate can be enabled.

The first attended network-demand start proved that `0xE2` and
`01FCFFFFFFFFFFFF` were accepted by the TM-102 without setting manual
override.  It also exposed a start-state race: a repeated pre-crank Stopped
status triggered an early fail-safe Release even though the generator was
starting normally.  0.5.0-rc2 retains demand through those Stopped repeats
until Running, Fault, or the bounded 120-second start timeout.

The rc2 orphan-process test then proved that Overall Demand can be false while
Network Demand remains true after a Cerbo reboot.  rc3 retains the cleanup
marker in that state and sends a source-specific Release once stopped/faulted;
Network Demand false is the authoritative proof that this network category has
cleared.  The rc3 retest passed process-loss recovery, but it also corrected
the interpretation of every previous five-minute run: the TM-102 stopped just
before the bridge Release, not because of it.  rc4 therefore reasserts the same
cooperative `01FC...` demand every 60 seconds while ownership remains active,
including through unload/cooldown and after fresh process recovery.  Persistent
generator TX remains gated until a live run stays active beyond five minutes
and then stops only after the bridge's `00FC...` Release.

The candidate also preserves the deployed temporary source classifier and
publishes the stricter ATS-based classification as a diagnostic.  The
temporary classifier is explicitly identified as a heuristic and is not
silently promoted to an authoritative ATS signal.

## Verified captures

| Fixture | Frames | Evidence |
|---|---:|---|
| `rvc-baseline.can` | 1,840 | Pump on, autofill off, no generator demand, generator stopped, runtime 75,495 minutes |
| `rvc-shore-passive.can` | 914 | AC present at VE.Bus, but no TM-102 ATS or generator AC frames in 15 seconds |
| live 2026-08-08 cycle | n/a | Panel start `5D...`/stop `5C...`; TM-102 demand and run/stop feedback; guarded Generator/50 A and Grid/30 A transitions |

The coach still does not publish an authoritative ATS source.  The approved
60-second/two-leg heuristic therefore remains a bounded shortcut; a dedicated
transfer-source signal is still the long-term upgrade.

## SetupHelper package

The repository root follows the SetupHelper/PackageManager package contract:

- `version` is the SetupHelper package version.
- `gitHubInfo` identifies the GitHub owner and development branch.
- `setup` installs or removes the `foretravel-rvc` runit service.
- `services/foretravel-rvc` contains the service and bounded log definition.
- `config.default.json` is copied only when no persistent configuration exists.
- `validFirmwareVersions` restricts the initial candidate to the tested Venus
  OS v3.75 baseline.

Use a pinned release tag in PackageManager. Do not configure this control
package to automatically follow `main` or `latest`.

### Existing manual deployment

The SetupHelper installer deliberately refuses to replace the current
`/data/apps/foretravel-rvc` service. Migration is an attended operation:

1. Download the package but do not install it.
2. Run `/data/rvforefish/tools/import-legacy-config.sh`.
3. Review `/data/rvforefish-data/config.json`, especially every write/control
   gate.
4. Confirm the generator is stopped and no generator-demand ownership marker
   exists.
5. Disable the legacy service with
   `/data/apps/foretravel-rvc/disable.sh`.
6. Install the pinned package from PackageManager.
7. Verify service state, CAN errors, D-Bus ownership, battery aggregation, and
   Ruuvi reporting before declaring the migration complete.

The legacy application directory is retained as the rollback target. The
package refuses uninstall while it has a generator-demand ownership marker.

## Run the replay and package tests

```sh
./tools/validate-package.sh
```

## Monitor-only service

```sh
svstat /service/foretravel-rvc
tail -n 100 /var/log/foretravel-rvc/current | tai64nlocal
dbus -y com.victronenergy.genset.socketcan_vecan0_di40_ucFA / GetItems
dbus -y com.victronenergy.switch.foretravel_rvc / GetItems
```

Start the read-only 24-hour safety/resource soak:

```sh
nohup /data/apps/foretravel-rvc/tools/soak-audit.sh 300 288 \
    > /data/log/foretravel-rvc-soak.stdout 2>&1 &
```

For a migrated system, package rollback is intentionally attended:

```sh
/data/rvforefish/setup uninstall
/data/apps/foretravel-rvc/enable.sh
```

Do not perform that rollback while generator demand is owned or while an
attended control operation is in progress.

## Documentation

- [Requirements and acceptance gates](docs/requirements.md)
- [Evidence register](docs/evidence-register.md)
- [RV-C DGN matrix](docs/dgn-matrix.md)
- [SilverLeaf function inventory and ownership](docs/function-inventory.md)
- [Architecture and ownership model](docs/architecture.md)
- [Risk register](docs/risk-register.md)
- [Deployment and validation plan](docs/deployment-and-test-plan.md)
- [0.5.0-rc1 safety and release audit](docs/release-0.5.0-rc1-audit.md)
- [0.5.0-rc2 commissioning regression audit](docs/release-0.5.0-rc2-audit.md)
- [0.5.0-rc3 orphan-demand recovery audit](docs/release-0.5.0-rc3-audit.md)
- [0.5.0-rc4 TM-102 demand keepalive audit](docs/release-0.5.0-rc4-audit.md)
