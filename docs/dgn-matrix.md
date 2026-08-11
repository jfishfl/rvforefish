# RV-C DGN matrix

All byte positions below are zero-based in code and one-based in the manuals.
Two-bit booleans use `00=false`, `01=true`; `10` and `11` are not treated as
truthy.

| DGN | Direction | Authority/use | Implementation |
|---:|---|---|---|
| `0x1FFB3` WATER_PUMP_STATUS | TM-102 → bus | Actual pump/bypass state, hookup detection, pressure | Decode; max age 7 s; drives switch `Status` |
| `0x1FFB2` WATER_PUMP_COMMAND | Venus → TM-102 | Requested on/off | Built but TX disabled until panel payload capture; require status ack |
| `0x1FFB1` AUTOFILL_STATUS | TM-102 → bus | Actual fill/valve/result | Decode; max age 7 s |
| `0x1FFB0` AUTOFILL_COMMAND | Venus → TM-102 | Start/stop fill | Stop safe; start hard-gated; manual-valve field always unavailable |
| PDU1 `0xEFxx`, operation `0xED` | TM-102 → panel | Proprietary autofill cutoff, run-after, timeout, automatic-start and pump/pressure policies | Decode destination-specific configuration reports only; bridge never queries or writes configuration |
| PDU1 `0xEFxx`, operation `0xD4` | TM-102 → panel | Proprietary water-pump input, relay, bypass and external-instance policies | Decode destination-specific configuration reports only; bridge never queries or writes configuration |
| `0x1FEFF` GENERATOR_DEMAND_COMMAND | Venus/panel → TM-102 | Cooperative AGS demand | Priority 6; bridge uses network demand with no quiet/manual override and no external-activity reset; live TX still commissioning-gated |
| `0x1FF80` GENERATOR_DEMAND_STATUS | TM-102 → bus | Overall/internal/network/manual/quiet/lock state | Decode; max age 7 s; actual provenance |
| `0x1FEFE` AGS_CRITERION_STATUS | TM-102 → bus | Fixed criteria 1–11, including standard and TM-102 proprietary types 247–250 | Decode all documented variants; read-only D-Bus snapshot; TM-102 delay scale is 5 s/bit |
| `0x1FED2` AGS_CRITERION_STATUS_2 | TM-102 → bus | Modern threshold counter | Decode seconds; read-only |
| `0x17003` legacy AGS_CRITERION_STATUS_2 | TM-102 → bus | Pre-assignment TM-102 threshold counter | Decode separately and mark legacy; read-only |
| `0x1FED5` / `0x1FEE7` AGS demand configuration status | TM-102 → bus | Configured disable/safety policies | Decode preferred and legacy assignments; read-only |
| `0x1FFD9` GENERATOR_START_CONFIG_STATUS | TM-102 → bus | Generator input type and pre-crank/max-crank/stop times | Decode and publish read-only |
| PDU1 `0xEFxx`, operation `0xEF`/`0x7F` | TM-102 → panel | Proprietary max run, stop criterion, movement policy and maximum limit | Decode destination-specific reports only; all configuration operations ignored |
| `0x1FFDC` GENERATOR_STATUS_1 | TM-102 → bus | Engine state/runtime/load/starter V | Decode and scale; max age 7 s |
| `0x1FFDB` GENERATOR_STATUS_2 | TM-102 → bus | faults/coolant/RPM | Decode and scale; max age 7 s running, 12 s stopped |
| `0x1FFDF` GENERATOR_AC_STATUS_1 | TM-102 → bus | Generator AC line voltage/current/frequency | Decode and scale; max age 2 s while running |
| `0x1FFAA` ATS_STATUS | TM-102 → bus | Selected source | Preferred source authority; max age 3 s while AC present |
| `0x1FFAD` ATS_AC_STATUS_1 | TM-102 → bus | ATS output AC/faults | Decode and scale; supporting evidence |
| `0x1FFB7` TANK_STATUS | TM-102 → bus | tank level | Decode only for interlocks; stock `dbus-rv-c` remains UI owner |
| `0x1FF9C` THERMOSTAT_AMBIENT_STATUS | TM-102 → bus | Configurable ambient/bay temperature instances | Decode current RV-C `uint16` scale; publish only valid instances as native temperature services |
| `0x1FFD3` INVERTER_COMMAND | panel → Victron RV-C node | Inverter enable/pass-through/load-sense request | Decode and audit only; stock `dbus-rv-c` owns behavior |
| `0x1FFC5` CHARGER_COMMAND | panel → Victron RV-C node | Charger enable/force/CC-CV request | Decode and audit only; stock `dbus-rv-c` and DVCC own behavior |
| `0x1FFC4` CHARGER_CONFIGURATION_COMMAND | panel → Victron RV-C node | Charger algorithm/bank/max-current configuration | Decode and audit only; never transmit |
| `0x1FF95` CHARGER_CONFIGURATION_COMMAND_2 | panel → Victron RV-C node | Shore breaker/current-related configuration | Decode and audit only; never transmit |
| `0x1FEFD` AGS_CRITERION_COMMAND | panel/tools → TM-102 | AGS configuration/query | Decode and audit observed panel commands; bridge never transmits it |
| `0x1FFDA` GENERATOR_COMMAND | diagnostic → generator controller | Direct start/stop | Forbidden for normal operation |
| `0x0EA00` J1939 REQUEST | any node → destination/global | Requests a DGN | Decode requested 3-byte PGN; respond to `0x1FEFF` within 3 s only if our demand remains active |

The 2016 TM-102 document contains one summary-table typo naming generator
demand command as `1FFEF`.  Its detailed generator section/parser example and
the current RV-C specification identify the command as `1FEFF`; the bridge uses
`1FEFF` exclusively.

The current RVIA specification assigns criterion counter status to `0x1FED2`.
The 2016 TM-102 document explicitly says its then-temporary assignment was
`0x17003`; the decoder accepts both and records which one supplied the value.
The current RVIA threshold delay is 0.1 minute (6 seconds) per bit, while the
TM-102 manual explicitly says its implementation uses 5 seconds per bit.

## Command payloads and authorization

These are validated wire-format vectors.  A validated vector is not by itself
authorization to transmit; the runtime feature, failure-test, source-address,
maximum-run, and unloaded-cooldown gates must also pass.

| Action | Payload | Notes |
|---|---|---|
| Pump on | `FD FF FF FF FF FF FF FF` | command=01; unsupported fields unavailable |
| Pump off | `FC FF FF FF FF FF FF FF` | command=00 |
| Autofill on | `FD FF FF FF FF FF FF FF` | operating=01; manual valve unavailable |
| Autofill off | `FC FF FF FF FF FF FF FF` | operating=00; manual valve unavailable |
| Generator network demand start/60-second keepalive | `01 FC FF FF FF FF FF FF` | demand=01, normal/no-action quiet, activity, manual and lock fields; periodic reassertion is required by this live TM-102 behavior |
| Generator release | `00 FC FF FF FF FF FF FF` | clears only this source's demand |

The Total Coach panel was captured sending `5D...` for start and `5C...` for
stop.  Those frames deliberately use Manual Override and Clear External
Activity because the panel is a manual user interface.  RVIA profile 65S
requires an independent Network Demand Source to use Manual Override `00` and
External Activity Reset `00` or `11`; the bridge therefore must not copy the
panel's first byte.
