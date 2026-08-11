# Architecture and ownership model

## Decision

Use one small Python service under `/data` with a pure decode/state core and a
thin SocketCAN/D-Bus adapter.  Install monitor-only first.  Do not use Node-RED
for the safety-critical transport loop and do not make stock Victron AGS a
second generator owner.

```text
Total Coach panel and existing switches
                  │ RV-C commands
                  ▼
       SilverLeaf TM-102 (0xFA)
       - sole crank/stop sequencer
       - existing AGS and protections
       - pump/autofill physical I/O
                  │ authoritative RV-C status
                  ▼
        foretravel-rvc bridge on Cerbo
        - decode + freshness + interlocks
        - no physical relay control
        - TX disabled by default
          │                         │
          ▼                         ▼
com.victronenergy.switch.*   com.victronenergy.genset.*
pump/fill/gen request UI     generator telemetry only
                                  (no /Start, no
                                   /RemoteStartModeEnabled)
                  │
                  ▼
com.victronenergy.temperature.foretravel_rvc_i*
valid TM-102 ambient instances; read-only and stale-safe
```

## Control ownership

| Concern | Sole owner | Bridge role |
|---|---|---|
| Physical generator crank/stop relays | TM-102 / PowerTech PCM | Cooperative demand only |
| Existing SilverLeaf AGS criteria | TM-102 | Observe, never rewrite initially |
| Pump relay and bypass input | TM-102 | Request state; display feedback |
| Autofill valve/pump logic | TM-102 | Request only after interlocks |
| VE.Bus charge and inverter control | Victron/DVCC/AggregateBatteries | No writes |
| Active AC source label | systemcalc + guarded bridge setting writer | Write only with authoritative classification |
| Remote dashboards | Native Venus/VRM, optionally Home Assistant later | Consumers, not competing writers |
| Ambient/bay temperatures | TM-102 sensors | Native read-only temperature services for valid instances only |
| RV-C inverter/charger/current-limit commands | Stock `dbus-rv-c` | Decode/audit only; never transmit |

## D-Bus services

### `com.victronenergy.switch.foretravel_rvc`

Channels:

- `water_pump`: toggle, actual `Status` from `0x1FFB3`.
- `autofill`: toggle, hidden until interlocks pass; stop always accepted.
- `generator_request`: toggle representing only this bridge's demand.  Overall
  generator state is separate telemetry.

`State` is requested state; `Status` is actual state/fault/external control.
Monitor-only sets `ShowUIControl=0` and rejects all writes.  Enabling one feature
does not enable the others.

Read-only `/Foretravel/Pump/*`, `/Foretravel/Autofill/*`, and
`/Foretravel/Tank/{Fresh,Black,Gray,Lpg}/*` diagnostics expose actual running,
hookup/pressure, valve/result, configuration, calculated tank level, staleness,
fault, and start-interlock reason.  The bridge does not duplicate the stock
Victron tank services.

### `com.victronenergy.genset.socketcan_vecan0_di40_ucFA`

Telemetry paths are populated only when corresponding RV-C data is fresh:

- `/Connected`
- `/ProductName`, `/CustomName`, `/DeviceInstance`, `/ProductId`, `/Serial`
- `/Mgmt/*`
- `/StatusCode`
- `/Engine/OperatingHours` (Venus seconds; TM-102 minutes × 60)
- `/Engine/Load`, `/Engine/Speed`, `/Engine/CoolantTemperature`
- `/StarterVoltage`
- `/Ac/Frequency`, `/Ac/L1/{Voltage,Current,Power}` when available
- `/NrOfPhases`
- diagnostic `/Foretravel/*` paths for demand provenance and freshness
- read-only `/Foretravel/Ags/Criterion/1..11/*`, `/Safety/*`, `/Starter/*`,
  and `/StopPolicy/*` snapshots

The service intentionally omits `/Start`, `/RemoteStartModeEnabled`, and
`/EnableRemoteStartMode`.  This prevents `dbus-generator` from owning TM-102
control.

The AGS paths are deliberately non-native diagnostics on the telemetry
service.  They do not publish `/Start` and do not register a second generator
controller.  Criteria/configuration normally report only when requested; the
monitor-only bridge waits for the Total Coach panel to make those requests and
never transmits a query itself.  Current RV-C and TM-102 legacy encodings are
kept distinct, including the 5-second TM-102 threshold unit and historical
`0x17003` counter DGN.

### `com.victronenergy.temperature.foretravel_rvc_i<instance>`

A service is created lazily after a TM-102 ambient instance supplies a valid
reading.  It publishes `/Temperature`, `/TemperatureType=2`, stable device
instance mapping, RV-C instance diagnostics, and `/Connected`.  It disconnects
after seven seconds of staleness.  Continuous `0xFFFE`/`0xFFFF` instances do
not create dead UI entries.

## AC source state model

The same physical MultiPlus input receives shore or generator after the ESCO
transfer switch.  VE.Bus alone cannot distinguish them.

Priority of evidence:

1. Fresh ATS selected-source status + fresh generator AC + VE.Bus acceptance.
2. If ATS is unavailable, a future dedicated transfer-source input.
3. Generator running plus voltage/frequency correlation is diagnostic only
   until proven across multiple transitions; it is not yet allowed to rewrite
   the Victron input type.

States:

| State | Required evidence | Victron label write? |
|---|---|---|
| Inverting | VE.Bus not accepting AC, no generator demand | Yes, systemcalc derives 240 |
| Generator starting | demand active, no accepted validated generator AC | No |
| Generator supplying | ATS=generator, generator AC valid/fresh, VE.Bus accepted | Yes, set input type 2 |
| Generator available/not accepted | ATS=generator and generator AC valid, VE.Bus not accepting | No; raise fault |
| Shore supplying | ATS=shore and VE.Bus accepted | Yes, set input type 3 |
| AC unknown | VE.Bus accepted but ATS/source authority stale | No; retain last label and show diagnostic warning |

The 2026-07-17 shore capture contained no ATS messages, so source-label writes
remain disabled.

Version 0.4 polls only the existing `com.victronenergy.system` AC source,
connection, L1/L2 voltage, and L1/L2 current paths at two-second intervals.  It publishes the
configured Victron name alongside a separate conservative classification and
reason under `/Foretravel/Source/*`.  This observer has no write method.  A
configured name such as Grid is never treated as transfer-source authority.

## Freshness and fail-closed behavior

- Five-second TM-102 status messages become stale after seven seconds.
- Generator AC, normally 500 ms while running, becomes stale after two seconds.
- A stale actual state is unavailable/disabled, never assumed off or on.
- A D-Bus write is accepted only if CAN status, TM-102 identity, interface,
  source address, and feature gate are all valid.
- A command starts an acknowledgment timer; status is the only success signal.
- Shutdown and restart do not restore requested-on state from disk.
- Bridge-owned generator demand is marked persistently before Start TX.
  Release is retried, and the marker remains until fresh TM-102 aggregate
  demand status proves False.  With another demander active, the conservative
  marker remains because aggregate status cannot acknowledge one source.
- A bridge-owned autofill start creates a persistent cleanup marker.  Normal
  stop, timeout, shutdown, or restart sends Stop, but the marker is removed
  only after authoritative TM-102 status reports Off.

## Autofill admission and lifecycle

1. Stop is independently gated and remains callable when status is stale.
2. Start requires the installation-verification gate, fresh `AUTOFILL_STATUS`,
   `WATER_PUMP_STATUS`, and fresh-tank `TANK_STATUS`.
3. A TM-102 operation `0xED` configuration report must have been observed
   since process start; its cutoff and policy flags must be valid and its
   no-level-change timeout must be nonzero.
4. Fresh-tank level is calculated as `100 * relative / resolution`; malformed
   fractions are unavailable and fail closed.
5. A required water hookup must be detected, and pump state must not conflict
   with the TM-102 cancel/bypass policy.
6. The TM-102 remains primary controller for cutoff, pump and valve sequencing.
   The bridge adds a separately configured hard maximum run time.
7. Any required live status becoming stale or the hard deadline expiring
   issues Stop and awaits TM-102 Off status.

## Generator lifecycle

1. User turns on `Generator request`.
2. Bridge validates not locked, fresh TM-102 status, no active fault, and TX arm.
3. Bridge sends cooperative demand with one external-activity reset.
4. The bridge reasserts the same cooperative network demand every 60 seconds
   and also answers a TM-102 request for the DGN.  Keepalives contain no
   manual, quiet-time, lock, or external-activity override/reset bits.  Live
   evidence requires the periodic reassertion because this TM-102 otherwise
   ends the run at its configured five-minute minimum-cycle boundary without
   polling the demand source.
5. UI displays Starting until engine and AC status prove progress.
6. On a normal off request, the bridge enters `unload_required`; it does not
   claim to switch coach loads itself.  The user or existing coach load manager
   removes load.
7. Fresh ATS/generator/VE.Bus agreement must prove the accepted source is the
   generator, and both VE.Bus leg currents must remain below an explicitly
   configured threshold for the full confirmation interval.
8. The bridge then requires 300 continuous unloaded seconds.  Any renewed
   load, missing leg, stale current, or lost source authority resets cooldown.
9. After cooldown it releases only its network demand.  A separately explicit
   hard timeout bounds the entire stop sequence and reports a fault if demand
   must be released without confirmed cooldown.
10. If another internal/network/manual demand remains, generator stays running
   and UI says “External demand,” not “failed to stop.”
11. The cleanup marker remains until fresh Network Demand status is False;
   startup sends Release for a stale marker and refuses to run if Release TX is
   not armed.
12. After an unclean process restart, fresh Network Demand true plus an active
   engine proves recovery of the bridge-owned demand.  The bridge immediately
   reasserts the same cooperative demand, then resumes the ordinary
   unload/cooldown state machine.
13. SilverLeaf remains the emergency/manual stop path; if it stops the engine
    while bridge demand is active, the bridge immediately releases its own
    demand so it cannot cause a restart.

Generator TX cannot be enabled until a live failure test proves what the TM-102
does when this demand source disappears.  A latched demand after Cerbo power
loss is an unacceptable unresolved risk.
