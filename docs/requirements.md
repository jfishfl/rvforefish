# Requirements and acceptance gates

This file translates the requested “fully integrate the RV-C functions” goal
into evidence-based completion criteria.  The project is not complete until
every mandatory gate has direct runtime evidence.

## Functional requirements

| ID | Requirement | Acceptance evidence |
|---|---|---|
| F-01 | Show actual water-pump state in Venus even when changed from SilverLeaf or a physical switch | Pump status changes in Venus within 6 seconds for all three control origins |
| F-02 | Control the water pump from Venus | On/off commands are captured, acknowledged by TM-102 status, and do not desynchronize existing controls |
| F-03 | Show generator engine state, runtime, faults, starter voltage, load, RPM, coolant temperature, and AC output when supplied by TM-102 | Native `com.victronenergy.genset.*` paths match a simultaneous RV-C capture and SilverLeaf display |
| F-04 | Show generator demand provenance | Venus distinguishes overall, internal AGS, network, external/manual, quiet-time, and locked states |
| F-05 | Request generator start/stop from Venus without bypassing TM-102 sequencing | Cooperative `GENERATOR_DEMAND_COMMAND` starts and releases only this bridge's demand; SilverLeaf retains crank/stop/protection logic |
| F-06 | Preserve existing SilverLeaf generator, pump, autofill, and AGS controls | Every existing control continues to work with bridge running, stopped, and rebooting |
| F-07 | Show the actual active AC source | Source is Generator or Shore only after authoritative/fresh evidence and VE.Bus acceptance; otherwise show Inverting or Unknown |
| F-08 | Show autofill status | Operating, valve, result, and stale/fault state are visible |
| F-09 | Start/stop autofill from Venus only when safe | Start requires valid configuration, fresh tank level, pressure/hookup policy, and timeout; stop remains available unconditionally |
| F-10 | Surface relevant TM-102 tank data without duplicating stock Victron RV-C tank services | Existing stock tank services are reused; bridge only consumes them for interlocks unless a missing field requires a separate diagnostic path |
| F-11 | Show every valid TM-102 ambient/bay temperature without inventing unavailable sensors | Native temperature service matches simultaneous `0x1FF9C` capture; stale/invalid values disconnect; configurable instance is not given a false physical name |
| F-12 | Preserve native Victron inverter, charger, and current-limit RV-C control | Panel commands are captured and audited; stock `dbus-rv-c` remains the only writer and bridge emits none of `0x1FFD3`, `0x1FFC5`, `0x1FFC4`, or `0x1FF95` |
| F-13 | Account for every Total Coach mode and every generic TM-102 capability | `function-inventory.md` identifies an evidence-backed owner/gate for active functions and explicitly excludes unproven options |
| F-14 | Surface the existing Total Coach START/AGS configuration without becoming a second AGS owner | Criteria 1–11, demand counters, starter timing, safety-disable configuration and stop policy appear as read-only `/Foretravel/Ags/*` paths after panel requests; no corresponding command DGN is transmitted |

## Safety invariants

| ID | Invariant | Verification |
|---|---|---|
| S-01 | Monitor-only is the default after install, upgrade, rollback, or missing config | Fresh install and reboot emit zero RV-C command frames |
| S-02 | The bridge never uses `GENERATOR_COMMAND 0x1FFDA` for ordinary control | Static test and live capture contain no transmitted 0x1FFDA frames |
| S-03 | The bridge does not publish `/RemoteStartModeEnabled` or `/Start` on its genset telemetry service | D-Bus audit proves both paths absent and no stock start/stop owner appears |
| S-04 | No Cerbo relay is assigned or toggled | Settings and relay-state snapshots are unchanged before/after deployment |
| S-05 | No source address is invented | TX refuses to arm unless live `/Settings/Rvc/vecan0/MainInterface/Nad` is valid; current observed NAD is 226 (`0xE2`) |
| S-06 | Status comes from TM-102, never the last command sent | Tests and live operation show external changes immediately override displayed state |
| S-07 | Stale data cannot remain “On”, “Running”, or “Generator” indefinitely | Each datum has a documented maximum age and moves to unavailable/fault when stale |
| S-08 | A failed pump command cannot silently look successful | Missing status acknowledgment causes fault and requested state reverts to actual/unknown |
| S-09 | Generator stop honors PowerTech cooldown | Normal stop requires fresh authoritative generator-source proof and both VE.Bus leg currents below an explicit threshold for a continuous confirmation interval; renewed load resets the timer; only then does a 300-second unloaded cooldown run before demand release; an explicit hard timeout prevents an orphaned demand |
| S-10 | Emergency/manual SilverLeaf stop remains available | Bridge never suppresses SilverLeaf input and immediately reflects resulting external-activity state |
| S-11 | Bridge crash/restart cannot create a new start or silently abandon its demand | Cleanup intent is persisted before Start TX; startup sends Release, release is retried, marker remains until fresh overall demand is False, and a stale marker with TX unarmed refuses startup; orphan-demand/power-loss behavior must still pass live testing before generator TX is enabled |
| S-12 | Autofill never exposes manual-valve-open control | Static API and UI audit show no manual valve control |
| S-13 | One control owner per action | No Node-RED, Signal K, Home Assistant, native GX AGS, or second service writes the same RV-C command paths |
| S-14 | A bridge-owned autofill cannot be orphaned by a process restart | Start creates a persistent cleanup marker; stop/shutdown retains it until fresh TM-102 status proves Off; startup sends fail-safe Stop before normal operation, and refuses to continue if stop TX is not armed |

## Operational requirements

| ID | Requirement | Acceptance evidence |
|---|---|---|
| O-01 | Survive Venus OS service restart and Cerbo reboot | Service returns monitor-only, D-Bus services reappear, and existing coach controls remain functional |
| O-02 | Low resource use | CPU, RSS, D-Bus update rate, CAN RX errors, and `/data` growth are recorded for a 24-hour monitor-only soak |
| O-03 | Durable installation | Files reside under `/data`, runit service is recreated by `/data/rc.local`, and firmware-update recovery is documented |
| O-04 | One-command rollback | Service can be stopped/disabled without modifying Victron packages or the root filesystem |
| O-05 | Auditable | Logs include state transitions, stale-data events, rejected commands, TX frames, source-address checks, and safety gate reasons without secrets |

## Completion gates

1. Offline parser, scaling, state, control, and failure-mode tests pass.
2. Independent static review finds no ownership or fail-open path.
3. Monitor-only deployment passes a 24-hour soak.
4. Pump control passes staged live tests.
5. Generator source detection passes shore → generator → shore transitions.
6. Generator cooperative demand passes start, normal cooldown stop, competing
   demand, service crash, Cerbo reboot/power-loss, and SilverLeaf emergency-stop
   tests.
7. Autofill control either passes all interlocks or remains explicitly disabled;
   disabled theoretical features are not claimed as integrated.
8. Final D-Bus, CAN, UI, logs, resource, and rollback audits pass.
9. Temperature instance mapping is compared with the SilverLeaf TEMP screen;
   unknown physical labels remain neutral rather than guessed.
10. Opening each SilverLeaf START/AGS page produces a simultaneous CAN/D-Bus
    capture proving every configured criterion, safety policy and stop policy;
    absent/unimplemented status remains explicitly unknown.
