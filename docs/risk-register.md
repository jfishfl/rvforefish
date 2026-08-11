# Risk register

Scores use probability × impact on a 1–5 scale.  Any open score ≥12 blocks
control enablement.

| ID | Risk | P | I | Score | Mitigation / gate | Status |
|---|---|---:|---:|---:|---|---|
| R-01 | Bridge and stock Venus AGS both own generator | 3 | 5 | 15 | Telemetry service omits remote-start paths; D-Bus audit | Mitigated in design |
| R-02 | Generator demand remains latched after bridge/Cerbo failure | 3 | 5 | 15 | Marker-before-Start, bounded Release retry, marker retained until fresh overall demand False, startup Release/refusal when unarmed, live process-loss/Cerbo-power-loss test; do not enable until proven | **Open blocker; offline mitigations pass** |
| R-03 | Wrong source label while generator runs but ATS remains on shore | 3 | 4 | 12 | Keep 60-second/two-leg shortcut explicitly heuristic; require ATS/transfer authority or exhaustive failure-case evidence before it can satisfy a control interlock | **Open blocker; shortcut operational** |
| R-04 | Pump UI says off while physical bypass keeps it on | 3 | 3 | 9 | `WATER_PUMP_STATUS` authoritative; show bypass/external status | Test pending |
| R-05 | Autofill floods coach or runs dry | 2 | 5 | 10 | Fresh level/config/pressure interlocks, timeout, stop always available | Start disabled |
| R-06 | Command uses wrong source address or collides | 2 | 5 | 10 | Live inventory shows candidate `0xE2` free; startup rechecks stock RV-C device inventory and refuses a collision | Offline and live inventory mitigated; recheck at commissioning |
| R-07 | Incorrect RV-C scaling misleads UI | 2 | 3 | 6 | 2026 RV-C physical-units table + synthetic vectors + live cross-check | Offline mitigated |
| R-08 | A stale message remains presented as current | 3 | 4 | 12 | Per-DGN deadlines, offline tests, and live invalid-value projection | Monitor-only validated; control test pending |
| R-09 | Normal stop damages hot diesel generator | 2 | 5 | 10 | Fresh authoritative generator source + both VE.Bus leg currents below explicit threshold + continuous confirmation + 300-second unloaded cooldown; renewed load resets cooldown; bounded hard-timeout fault | Offline interlock implemented; live load calibration/test pending |
| R-10 | Source-label writer fights user/system settings | 3 | 3 | 9 | Separate gate, write only on confirmed transition, restore prior setting on disable | Open |
| R-11 | Added service overloads Cerbo or `/data` | 2 | 3 | 6 | bounded logs, event-only D-Bus updates, 24-hour resource soak | 0.6% one-core CPU sample, 16 MiB RSS, 8 KiB log; soak pending |
| R-12 | Firmware update removes service hook | 4 | 2 | 8 | `/data` install + documented reinstall/health check | Pending |
| R-13 | Existing panel behavior changes due to broadcast commands | 2 | 5 | 10 | monitor soak first; one feature at a time; rollback command/service | Pending |
| R-14 | 30 A shore wiring fault is confused with RV-C integration | 3 | 4 | 12 | Treat as separate electrical incident; no integration dependence | Separated |
| R-15 | Autofill remains active after bridge crash/restart or a failed stop acknowledgement | 2 | 5 | 10 | Persistent ownership marker, startup/shutdown Stop, marker retained until fresh Off status, local hard timeout, stale-status Stop; live crash/power-loss test required | Offline mitigated; live test pending |
