# Evidence register

Primary manuals and current upstream source take precedence over earlier chat
summaries or wiki prose.

## Coach and SilverLeaf manuals

| Evidence | Source | Design consequence |
|---|---|---|
| TM-102 receives `WATER_PUMP_COMMAND 0x1FFB2` and publishes `WATER_PUMP_STATUS 0x1FFB3`; actual status includes pump control and bypass input | TM-102 Application Document, pages 39–41 | Status feedback is authoritative; a sent command is never treated as success |
| TM-102 receives `AUTOFILL_COMMAND 0x1FFB0` and publishes `AUTOFILL_STATUS 0x1FFB1`; configuration includes level cutoff, run-after, timeout, pressure check, and pump interactions | TM-102 Application Document, pages 37–39 | Autofill start requires configuration/interlock discovery; manual valve is not exposed |
| Normal generator applications should demand the TM-102 AGS, while direct `GENERATOR_COMMAND` is for troubleshooting | TM-102 Application Document, generator controller section and pages 51–55 | Use `0x1FEFF`, never `0x1FFDA`, for normal Venus control |
| The Total Coach panel's observed `5D`/`5C` frames assert panel/manual semantics; another network demand source must not copy them | TM-102 Application Document, page 51; live 2026-08-08 capture; current RV-C profile 65S | Cerbo uses cooperative network demand only and leaves quiet/manual state unchanged |
| When demand ends the TM-102 requests the demand DGN; remaining demanders must answer within 3 seconds | TM-102 Application Document, page 51 | Decoder must handle J1939 request frames and respond while this bridge still demands power |
| Generator demand status reports overall, internal, network, external activity, manual override, quiet time/override, and lock | TM-102 Application Document, page 55 | UI exposes provenance rather than a single misleading boolean |
| TM-102 has fixed AGS criterion instances 1–11 with standard types 0/1/3/4/5 and proprietary types 247–250; criteria report on `0x1FEFE` | TM-102 Application Document, pages 52–55 | Decode every documented START-mode criterion but never create/delete/edit it |
| TM-102 threshold timers use 5 s/bit rather than the then-proposed RV-C 6 s/bit; its temporary status-2 assignment was `0x17003` | TM-102 Application Document, pages 52–55 | Apply source-specific timing scale and observe both legacy/current counter DGNs |
| TM-102 proprietary AGS stop reports expose max run time, stop criterion, movement disable, plus time and max-run ceiling | TM-102 Application Document, pages 54–55 | Decode only report operations `0xEF`/`0x7F`; never send configure/reset operations |
| `GENERATOR_STATUS_1 0x1FFDC` reports engine state and runtime; AC output uses `0x1FFDF` | TM-102 Application Document, pages 27–28 | Publish generator telemetry separately from control |
| SurgeGuard ATS bridge publishes `ATS_STATUS 0x1FFAA`; source 0=generator, 1=shore, 253=none | TM-102 Application Document, page 30 | ATS is preferred source authority when fresh |
| SilverLeaf monitors are mirrored; actions on one are reflected on others | Original Total Coach System manual, overview | Venus must follow actual status so every panel remains synchronized |
| SilverLeaf controls pump, autofill, generator, inverter, charger, tanks, and AC status | Original Total Coach System manual, pages 5–8 | Only functions proven active on this coach are exposed; existing controls remain primary |
| PowerTech warns not to stop without idling; idle about five minutes before stopping | PTRV-12 CSI manual, page 7 | Normal Venus stop includes a 300-second unloaded cooldown |
| PowerTech PCM owns preheat, crank, retries, faults, and shutdown inputs | PTRV-12 CSI manual, pages 13–14 | Venus must request demand, not reimplement crank/stop relays |
| TM-102 ambient status uses configurable instances; generic firmware can broadcast internal/external sensors | TM-102 Application Document, feature summary, instance configuration and ambient-status sections | Do not infer storage/plumbing name from instance alone |
| Total Coach TEMP mode shows storage and plumbing bay temperatures | Original Total Coach System manual, Temperature Mode | Include valid TM-102 ambient telemetry in Venus |

Local primary extracts:

- `/tmp/foretravel-wiki/tm-102-application.txt`
- `/tmp/foretravel-wiki/original-total-coach-system-manual.md`
- `/tmp/foretravel-wiki/powertech-ptrv-12-csi-generator-manual.md`

## Current RV-C specification

Source: [RVIA Full Layer Specification, 2026-02-20](https://www.rvia.org/system/files/media/file/RV-C%20Specification%20Full%20Layer%202-20-26_Final_v2.pdf)
and [current DGN table](https://www.rvia.org/rv-c/rv-c-dgn-table).

- AC status voltage is `uint16 × 0.05 V`.
- AC current uses `uint16`, `0x7D00 = 0 A`, `0.05 A/bit`.
- Frequency is `uint16 / 128 Hz`.
- Generator state 0=stopped, 1=preheat, 2=cranking, 3=running,
  4=priming, 5=fault; runtime is minutes.
- Generator AC status normally broadcasts every 500 ms while running.
- `THERMOSTAT_AMBIENT_STATUS 0x1FF9C` is instance plus `uint16` °C;
  standard scaling is `raw × 0.03125 - 273`.
- `AGS_CRITERION_STATUS 0x1FEFE` is multi-instance and on request; current
  standard types are 0–7, with type-dependent bytes 3–7.
- `AGS_CRITERION_STATUS_2 0x1FED2` reports a seconds counter; the current
  standard supersedes the TM-102's documented temporary `0x17003` assignment.
- `AGS_DEMAND_CONFIGURATION_STATUS 0x1FED5` (legacy duplicate `0x1FEE7`)
  reports configured AGS disable policies, not the live state of those inputs.
- `GENERATOR_START_CONFIG_STATUS 0x1FFD9` reports pre-crank, maximum crank,
  and stop timing; its command counterpart remains outside the bridge.
- `TANK_STATUS 0x1FFB7` carries relative level and an independent resolution;
  percentage is `100 × relative / resolution`, not a fixed 255 divisor.  Its
  optional absolute level and capacity fields are litres.
- `WATER_PUMP_STATUS 0x1FFB3` separately reports enabled, actually running,
  hookup detection, measured pressure, pump/regulator settings and operating
  current.  Pressure fields use 100 Pa per bit.
- `AUTOFILL_STATUS 0x1FFB1` reports operating state, valve state and the last
  result (running, success, timeout, manual abort or error); requested state is
  not evidence of actual operation.
- The TM-102 summary-table `1FFEF` generator-demand spelling is a manual typo;
  the detailed TM-102 section and current specification use `1FEFF`.
- `GENERATOR_DEMAND_COMMAND 0x1FEFF` uses CAN priority 6.  A profile 65S
  network demand source uses demand `01`/release `00`, manual override `00`,
  and no external-activity reset.  With all unsupported fields unavailable,
  the complete payloads are `01FCFFFFFFFFFFFF` and `00FCFFFFFFFFFFFF`.

## Current Victron sources

| Evidence | Source | Design consequence |
|---|---|---|
| `com.victronenergy.genset` is telemetry; `com.victronenergy.generator` is start/stop | [Venus D-Bus API](https://github.com/victronenergy/venus/wiki/dbus#generator-data) | Publish telemetry and control separately |
| `/RemoteStartModeEnabled=1` makes Venus start/stop own `/Start` | Venus D-Bus API and current `dbus_generator/genset.py` | Omit both paths from TM-102 telemetry service |
| Switch pane scans `/SwitchableOutput/x/...`; `State` is requested state and `Status` is actual channel status | [Venus switch API](https://github.com/victronenergy/venus/wiki/dbus#switch) and current `dbus-switch.py` | Publish actual status independently and reject/flag unacknowledged writes |
| Current Cerbo RV-C-out supports VE.Bus inverter/charger status and RV-C control of inverter, charger and shore current limit | [Victron Cerbo GX RV-C support](https://www.victronenergy.com/media/pg/Cerbo_GX/en/rv-c-support.html) | Keep those DGNs under stock `dbus-rv-c`; bridge observes only |
| `/Ac/ActiveIn/Source`: 0 unavailable, 1 grid, 2 genset, 3 shore, 240 inverting; value is derived from active input and configured input type | [Venus D-Bus API](https://github.com/victronenergy/venus/wiki/dbus#system) | Physical AC input role must change only after reliable source classification |
| MultiPlus-II 2x120V PowerControl/PowerAssist applies to L1 and the adjustable limit does not constrain L2 | [Official MultiPlus-II 2x120V manual](https://www.victronenergy.com/upload/documents/MultiPlus-II_2x120V/32424-MultiPlus-II___Quattro-II-pdf-en.pdf), PowerControl and specifications | Never infer total generator load from the L1 limit; observe both input-leg currents independently |
| Any synchronized genset service causes `venus-platform` to run `dbus-generator`; only a genset with `/RemoteStartModeEnabled` becomes a controllable start/stop device | current `venus-platform/src/application.cpp` and `dbus-generator/genset.py` | Telemetry-only service is acceptable, but its path audit is mandatory |

Local upstream checkouts used for line-by-line review:

- `/tmp/victron-dbus-switch`
- `/tmp/victron-dbus-generator`
- `/tmp/victron-venus-platform`

## Live coach evidence

| Date | Evidence | Result |
|---|---|---|
| 2026-07-16 | 30-second, 1,840-frame capture | TM-102 `0xFA`; pump on; autofill off; generator stopped; no demand; runtime 75,495 min; no ATS/gen-AC frames |
| 2026-07-17 | 15-second, 914-frame passive shore capture | VE.Bus had AC, but no `0x1FFAA`, `0x1FFAD`, `0x1FFDF`, `0x1FEBB`, or `0x1FEB8` frames |
| 2026-07-17 | Live D-Bus settings | RV-C `vecan0`; AC input 1 configured as Grid (1); an older setting identified `0xE2`, but settings alone do not prove current NAD ownership |
| 2026-07-17 | Monitor-only bridge deployment | Native genset/switch services registered; no generator start/stop owner; pump on, autofill off, generator stopped, runtime 4,529,700 seconds; all UI controls hidden; CAN TX unarmed |
| 2026-07-17 | Live monitor safety audit | Direct D-Bus write was rejected and State remained 0; forbidden start paths absent; no `com.victronenergy.generator.*` owner; 6 CPU ticks/10 s, 16 MiB RSS, 8 KiB bounded log, 328 KiB application; vecan0 remained ERROR-ACTIVE with zero current error counters |
| 2026-07-17 | Structured live audit logger | Recorded authoritative TM-102 transitions: generator stopped, no internal/network demand or lock, pump on, autofill off; every future supported command and every TX frame has exact source/DGN/payload logging |
| 2026-07-17 | Baseline function inventory | Valid TM-102 ambient instance 250 at about 34.3 °C; instances 249/248 broadcast `0xFFFE`; stock Victron source `0xE1` carries inverter/charger status; `0x1FEA3` is CHARGER_STATUS_2 and `0x1FECA` is DM-RV |
| 2026-07-17 | 0.3.0 offline AGS audit | 84 tests cover all fixed TM-102 criteria, current/legacy counters, starter timing, preferred/legacy safety configuration, destination-specific stop reports, their read-only D-Bus projections and PDU1 destination filtering |
| 2026-07-17 | 0.4.0 safety candidate audit | 117 tests cover corrected tank scaling/sentinels, pump/autofill status, TM-102 operations `0xED`/`0xD4`, fail-closed cleanup, marker-before-TX, generator Release retry, and read-only VE.Bus/ATS source diagnostics; candidate is not yet deployed |
| 2026-07-17 | Live read-only VE.Bus load-path check | `/Ac/ActiveIn/L1/Current` and `/Ac/ActiveIn/L2/Current` both exist on Venus OS 3.75 and return numeric values; current shore snapshot was 2.3 A and 0.0 A | Generator cooldown can require both legs without a setting write; live generator-load calibration remains mandatory |
| 2026-08-08 | Attended panel generator cycle | Source `0x9B` sent start `5DFFFFFFFFFFFFFF` and stop `5CFFFFFFFFFFFFFF`; TM-102 source `0xFA` immediately reflected demand and running/stopped state | These prove panel behavior and feedback, but are deliberately not copied for Cerbo network demand |
| 2026-08-08 | Temporary source/current-limit transition | After 60 seconds of TM-102 running plus two stable AC legs, the service changed Input 1 to Generator and 50 A; stop restored Grid and 30 A | The bounded heuristic works operationally but is not equivalent to an ATS authority signal |
| 2026-08-10 | Live RV-C device inventory | Active NADs included `0x9B`, `0xFA`, `0x10`, `0xE1`, `0xA0`-`0xA5`; `0xE2` was unclaimed | `0xE2` is the current candidate transmit source, with a mandatory startup collision check before any TX-capable configuration can run |
| 2026-08-10 | Direct VE.Bus split-phase paths | `com.victronenergy.vebus.ttyS4` returned numeric `/Ac/ActiveIn/L1/V`, `/L2/V`, `/L1/I`, `/L2/I`, and `/Ac/ActiveIn/CurrentLimit` values | Source stability and unloaded-stop decisions use direct VE.Bus values for both legs rather than aggregate or relabeled system paths |
| 2026-08-10 | 0.5.0-rc1 offline safety audit | 138 tests pass, including priority-6 cooperative demand/release payloads, marker-before-TX, bounded release retry, startup recovery, both-leg unload confirmation, five-minute cooldown, source heuristic ordering, and NAD collision refusal | Safe for a TX-disarmed monitor-only deployment; live generator commissioning gates remain closed |
| 2026-08-10 | Post-reboot startup diagnosis | `startup.log` showed valid monitor-only configuration followed by `dbus-rv-c is not running on vecan0`; stock RV-C was healthy after boot, but the custom service link was absent | This was a one-shot rc.local ordering race; 0.5.0-rc1 waits only during boot for stock RV-C readiness and preserves strict manual/install preflight behavior |
| 2026-08-10 | 0.5.0-rc1 TX-disarmed deployment | On-device validation passed; service started alongside stock `dbus-rv-c.vecan0`; rollback backup `/data/apps/foretravel-rvc-backup-20260810-220536`; no demand marker; generator stopped; own demand false; controls hidden; zero `AUDIT TX`; zero new service errors | Monitor/telemetry and the approved Grid/30 A–Generator/50 A shortcut are active; generator command transmission remains impossible in the deployed configuration |
| 2026-08-10 | Post-install battery and sensor regression | All four BLE battery services and AggregateBatteries remained up; aggregate connected at 98.75%, four online, zero stale, ActiveBmsService aggregate, BMSParameters 1; two Ruuvi D-Bus services remained present | No observed BLE, aggregate-BMS, DVCC, or Ruuvi regression from starting 0.5.0-rc1 |
| 2026-08-10 | First attended cooperative-demand start | Cerbo source `0xE2` sent priority-6 `01FCFFFFFFFFFFFF`; TM-102 immediately reported network demand then overall demand, with manual override false, and the generator started | Source address, DGN, priority, payload, and TM-102 cooperative-demand acceptance are proven live |
| 2026-08-10 | First-start state-race recovery | A repeated Stopped status during the normal preheat/crank transition caused rc1 to send three bounded `00FCFFFFFFFFFFFF` releases; TM-102 network demand became false, completed its minimum cycle, stopped, reported overall demand false, cleared the ownership marker, and the service restored Grid/30 A | Safe cleanup passed, but rc1 cannot retain a start demand; rc2 ignores Stopped repeats only while a bounded start is still in progress |
| 2026-08-10 | 0.5.0-rc2 regression audit | 139 tests pass, including the live Stopped-repeat sequence followed by Running; start timeout, fault handling, release retry, marker cleanup, unload confirmation and cooldown tests remain green | Safe for another TX-disarmed deployment and second attended start; normal control remains gated |
| 2026-08-10 | Pre-second-start NAD recheck | A bounded passive listen found active `0xE2` traffic (`0x1FECA`/DM-RV plus an address-claim request), even though stock `dbus-rv-c` did not list a corresponding remote device; `0xE3` was silent for a dedicated 15-second listen | The temporary commissioning profile moved to `0xE3`; the normal configuration still has no transmit source and remains monitor-only |
| 2026-08-10 | Second attended rc2 cooperative-demand start | Source `0xE3` demand was accepted with TM-102 network and overall demand true, manual override false, rc2 phase Running, own-demand marker present, and no fault; the pre-crank Stopped repeat no longer caused release | The rc1 start-state race is closed live |
| 2026-08-10 | Second attended source/current-limit transition | Direct VE.Bus measurements were L1 122.55 V/0.77 A and L2 121.27 V/0.35 A; after the guarded verification the source changed to Generator and the input limit changed to 50 A | Both-leg source validation and the approved temporary 50 A shortcut pass live |
| 2026-08-10 | Normal rc2 unloaded stop and cooldown | A stop request retained demand through fresh two-leg current confirmation below 5 A for 30 seconds and the full 300-second cooldown; TM-102 then reported stopped/no demand, rc2 returned idle with no ownership or cleanup marker, and Grid/30 A was restored | Normal start/stop, unload interlock, cooldown, acknowledgement, and cleanup pass live |
| 2026-08-10 | Post-commissioning safe baseline | Persistent `0.5.0-rc2` service restored with `monitor_only=true`, no source address, generator feature disabled and UI control hidden; stock RV-C up; Signal K off; aggregate connected with four online/zero stale/no BMS cable alarm; three Ruuvi services present; vecan0 ERROR-ACTIVE with live tx/rx error counters zero | No generator TX is possible in the persistent configuration; orphan process-loss testing remains open |
| 2026-08-11 | Water-pump attended commissioning | The generator-only controller was replaced with a pump-only `0xE3` profile; ten ON/OFF pairs produced 20 matching TM-102 status acknowledgements and the final physical/status state was Off | Pump payload, acknowledgement, retry path, and final safe state pass live; autofill remained hidden and TX-disabled |
| 2026-08-11 | rc2 generator process-loss injection | Source `0xE3` started the generator with network demand, no manual override, ownership marker present, then verified PID `3744` was frozen and killed; restart recovered the marker without a new Start and retained demand at 20.85 A total input rather than bypassing unload/cooldown | Marker-before-TX, process death survival, startup ownership recovery, and under-load demand retention pass live |
| 2026-08-11 | Cerbo reboot during orphan recovery | Venus OS rebooted during the recovery run; the marker survived but the temporary service link did not. After service restoration the generator was stopped with Overall Demand false but Network Demand still true, and rc2 had already cleared its marker | Overall Demand is not authoritative cleanup proof for a network source; rc2 orphan gate fails |
| 2026-08-11 | Stopped-generator source-specific cleanup | One source-`0xE3` Release `00FCFFFFFFFFFFFF` changed TM-102 Network Demand true to false while generator status remained stopped; Overall Demand was false and Grid/30 A was restored | Coach returned to a safe no-demand baseline without a new start |
| 2026-08-11 | 0.5.0-rc3 recovery correction | Cleanup and startup recovery now use Network Demand false as category-level proof; regressions cover Overall false/Network true and unrelated Overall true/Network false; full suite is 141 tests | Safe for TX-disarmed deployment and another attended orphan test; persistent generator TX remains gated |
| 2026-08-11 | 0.5.0-rc3 TX-disarmed deployment | Archive SHA-256 `d46ffbfbbbee2788ca2ec0ec1d690838b042bcbfd91aee913367e9e80ca96cb8`; on-device monitor-only validation passed; rollback backup `/data/apps/foretravel-rvc-backup-20260811-002150`; all three controls hidden; generator stopped with Overall/Network/Internal/Manual demand false; marker absent; Grid/30 A restored | rc3 is the persistent safe baseline; no RV-C command TX is possible until another explicit commissioning profile is installed |
| 2026-08-11 | rc3 post-install battery, sensor and CAN audit | Four BLE battery services up; aggregate Connected=1, SOC 98.5%, four online, zero stale, BMS cable alarm zero; aggregate is ActiveBmsService with BMSParameters=1 and DVCC on; three Ruuvi services present; stock RV-C up; Signal K down; vecan0 ERROR-ACTIVE with tx/rx error counters zero; no rc3 TX/error/critical log records | No observed BLE, aggregate-BMS, DVCC, Ruuvi, stock RV-C, or CAN regression from rc3 monitor-only deployment |
| 2026-08-11 | rc3 attended process-loss retest | Source `0xE3` started the generator; verified PID was frozen and killed with Network Demand true and the marker present; restart recovered ownership, retained demand under about 20 A load, then safely cleared a still-true Network Demand bit only after the engine stopped | Network-specific marker recovery and under-load retention pass live; no blind Release occurred during restart |
| 2026-08-11 | Five-minute stop-order correction | rc3 and both earlier rc2 run logs show Overall Demand false and generator Stopped immediately before the bridge's `00FC...` Release, at about five minutes after Start; no TM-102 request for `0x1FEFF` was observed | Earlier wording that Release caused the generator stop is superseded; this TM-102 needs periodic cooperative-demand reassertion to keep the run alive beyond its configured minimum cycle |
| 2026-08-11 | 0.5.0-rc4 keepalive regression audit | A bounded 60-second `01FC...` reassertion continues while the bridge owns demand, including process recovery and unload/cooldown; it stops before Release and never sets manual, quiet-time, lock or activity-reset bits; complete suite is 144 tests | Safe for TX-disarmed deployment and one attended run proving the engine remains running beyond five minutes and stops only after the bridge Release |

The missing ATS data remains a material unresolved condition.  The approved
60-second/two-leg classifier is retained only as an explicit temporary
heuristic for the already tested Grid/30 A and Generator/50 A shortcut.  It is
not treated as authoritative ATS evidence for closing the generator-control
safety gates.
