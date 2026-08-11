# SilverLeaf function inventory and ownership

This inventory prevents two opposite failures: omitting an active Total Coach
function, or exposing a generic TM-102 capability that is not actually wired or
configured on this coach.  A function is considered active only when the
Foretravel display/manual, a live RV-C frame, or physical wiring proves it.

## Evidence rules

1. Live status and command captures from this coach outrank generic feature
   lists.
2. The TM-102 Application Document defines protocol and safety behavior, but
   its feature summary is a capability list, not proof that every option is
   installed.
3. Stock Venus `dbus-rv-c` remains owner wherever it already implements the
   Victron RV-C device.  This bridge observes those commands for audit and does
   not transmit duplicates.
4. An unavailable RV-C value is not a sensor.  In particular, temperature raw
   values `0xFFFE` and `0xFFFF` never create a live Venus sensor.
5. A function with incomplete authority, freshness, payload, or failure-mode
   evidence remains hidden and transmit-disabled.

## Active Total Coach functions

| Function | Coach evidence | Runtime owner | Bridge responsibility | Current gate |
|---|---|---|---|---|
| Fresh/gray/black/LPG tanks | Total Coach TANKS mode; live `TANK_STATUS 0x1FFB7` | TM-102 status; stock Victron RV-C-in UI | Consume fresh-water level for future autofill interlocks; do not duplicate tank services | Read-only active |
| Water pump | PUMP mode and physical switches; live `0x1FFB3` | TM-102 relay/bypass input | Native switch status; later send `0x1FFB2` with feedback timeout | Status active; TX awaiting panel capture |
| Automatic fresh fill | Holding TANKS/PUMP controls fill; live `0x1FFB1` | TM-102 valve, pump, timeout, pressure and level logic | Show operating/valve/result; start only after all interlocks; stop independently gated | Status active; TX disabled |
| Generator engine and AC | GEN mode; live `0x1FFDC`; TM-102/PowerTech manuals | TM-102 demand controller and PowerTech PCM | Native genset telemetry; cooperative demand only; no direct crank/stop | Telemetry active; TX disabled |
| Existing generator AGS | START mode, autocharger/exerciser/quiet-time; live demand status `0x1FF80`; TM-102 pages 51–55 | TM-102 | Show complete demand provenance; decode criteria 1–11, counters, starter timing, disable policy and stop policy; never rewrite criteria | Offline read-only implementation complete; live on-request capture pending |
| Ambient/bay temperature | TEMP mode; live `0x1FF9C` instances 250/249/248 | TM-102 sensors | Create native Venus temperature services only for valid readings; stale data disconnects | Instance 250 valid; 249/248 unavailable |
| AC/SurgeGuard status | 120V mode | TM-102 SurgeGuard bridge when it publishes data; VE.Bus for acceptance | Read-only `/Foretravel/Source/*` diagnostics; classify only with fresh ATS + generator AC + VE.Bus agreement | Candidate implemented; no ATS frames observed; source writes disabled |
| Inverter on/off and status | INV/120V modes; live Victron `INVERTER_*` status | Stock `dbus-rv-c` and VE.Bus | Audit `INVERTER_COMMAND 0x1FFD3`; never send it from this bridge | Stock ownership only |
| Charger on/off and status | INV mode; live Victron `CHARGER_*` status | Stock `dbus-rv-c`, VE.Bus, DVCC/AggregateBatteries | Audit `0x1FFC5`; do not compete with DVCC | Stock ownership only |
| Maximum charger/input current | INV mode; user adjusts shore limit in VRM | Stock `dbus-rv-c`/VE.Bus remote-current path | Audit `0x1FFC4` and `0x1FF95`; no writer | Stock ownership only |
| Date/time | Idle display; live `DATE_TIME_STATUS 0x1FFFF` | TM-102/coach clock | No duplicate Venus clock service | Observe only if troubleshooting |
| Chassis/J1939 bridge | TM-102 feature; live source `0x10` traffic | TM-102 | Do not reinterpret or retransmit bridged chassis messages | Out of bridge scope |

## Temperature instance status

The 2026 RV-C specification defines `THERMOSTAT_AMBIENT_STATUS` byte 0 as
instance and bytes 1–2 as little-endian `uint16` temperature using
`raw × 0.03125 - 273 °C`.

| RV-C instance | Live raw | Result | Venus treatment |
|---:|---:|---:|---|
| 250 (`0xFA`) | approximately `0x266A`–`0x266E` | 34.3–34.4 °C | Publish as generic `SilverLeaf Ambient 250`, device instance 60 |
| 249 (`0xF9`) | `0xFFFE` | Invalid/not configured | Do not create a service |
| 248 (`0xF8`) | `0xFFFE` | Invalid/not configured | Do not create a service |

The TM-102 permits proprietary instance configuration, so instance 250 cannot
yet be honestly named “storage bay” or “plumbing bay.”  Map and rename it only
after photographing the SilverLeaf TEMP page at the same time as a raw capture.

## TM-102 START/AGS inventory

The TM-102 has a predetermined criterion set; Venus does not create, delete,
activate, or edit it.  Read-only status is projected under
`/Foretravel/Ags/*` on the genset service after the panel requests each value.

| Instance | TM-102 function | Type | Venus treatment |
|---:|---|---:|---|
| 1 | House DC-voltage autocharge | 0 | Active/demand, DC instance, threshold and 5-second delay |
| 2 | DC-voltage or Charge Bridge | 0 | Same status; name remains conditional because payload alone cannot distinguish mode |
| 3 | Ambient-temperature demand | 3 | Thermostat instance, temperature, delay and proprietary deadband |
| 4 | Transfer-switch AC-voltage demand | 4 | ATS instance, voltage threshold and delay |
| 5 | DC-voltage topoff | 250 | DC instance, threshold and run time |
| 6 | Scheduled exercise | 249 | Day mask, start time and run time |
| 7 | External GEN SWITCH input | 248 | Configured input delay |
| 8 | External GEN DEMAND input | 248 | Fixed five-second qualification |
| 9 | House-battery SOC autocharge | 1 | Start/stop SOC and delay |
| 10 | SOC topoff | 247 | Start SOC and run time |
| 11 | Quiet time | 5 | Begin/end local time |

Modern `AGS_CRITERION_STATUS_2 0x1FED2` and the TM-102's historical temporary
`0x17003` are both observed.  Starter configuration (`0x1FFD9`), AGS disable
configuration (`0x1FED5`/legacy `0x1FEE7`), and proprietary stop-policy reports
are diagnostic snapshots only.  Their corresponding command/configuration
operations are not part of the runtime transmit surface.

## Live network identities and non-conflicting roles

| Source | Observed role |
|---:|---|
| `0xFA` | TM-102 authoritative coach I/O, generator, tanks, temperature, demand and legacy power status |
| `0x9B` | Total Coach user panel and directed requests/commands |
| `0xE1` | Victron MultiPlus virtual RV-C inverter/charger node |
| `0xE2` | Cerbo main RV-C node and future bridge source after validation |
| `0xA0`–`0xA5` | Victron battery/shunt virtual nodes |
| `0x10` | J1939 traffic bridged by TM-102; product identity is not required for this integration |

The baseline contains both TM-102 legacy `INVERTER_STATUS`/`CHARGER_STATUS`
and Victron `0xE1` status.  This bridge does not resolve that by transmitting a
third status source.  The staged panel-command capture must prove which
instance the Total Coach panel addresses and whether stock `dbus-rv-c` already
provides the intended behavior.

## Generic TM-102 capabilities not proven active

These appear in the generic TM-102 application document but are not established
as active Total Coach functions on this coach.  They stay absent from Venus
until wiring, configuration and live DGNs prove otherwise.

| Capability | Decision |
|---|---|
| Chassis mobility controller | Do not expose; mutually exclusive configurations exist and no active coach control is proven |
| Tile/floor heat and bay thermostat output | Do not control; temperature telemetry is safe, thermostat output is not proven |
| Full dual-zone climate/A/C load management | Do not control; retain Intellitec/coach HVAC ownership |
| Awning control | Do not expose |
| Slide control | Do not expose |
| Water-heater relight/electric-element control | Do not expose |
| Battery-disconnect solenoid | Do not expose |
| Chassis-battery charging solenoid | Do not expose |
| EMS-to-RV-C shedding | Observe only if frames are later proven; do not compete with Intellitec |
| Xanbus/Outback bridge | Legacy Xantrex was removed; do not configure or emulate |
| Serial monitor/data-log service operations | Diagnostic/service-tool scope only |
| Proprietary reset/calibration/configuration PGNs | Forbidden from normal runtime |

## Completion implications

“Fully integrated” for this coach means every active row above has a deliberate
owner, accurate/stale-safe telemetry, and either a validated control path or an
explicitly documented disabled gate.  It does not mean enabling every option
ever supported by TM-102 firmware.
