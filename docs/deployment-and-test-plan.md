# Deployment and validation plan

## Stage 0 — Offline evidence and replay

- Preserve captures with hashes.
- Decode only documented fields and standard units.
- Test unknown/unavailable values, stale data, bad frames, and source authority.
- Static-audit every potential CAN and D-Bus write.

Exit: all offline tests pass; TX cannot be armed by default.

## Stage 1 — Monitor-only Cerbo deployment

- Install under `/data/apps/foretravel-rvc`.
- Create a runit service and bounded multilog output.
- Open `vecan0` read-only; publish D-Bus telemetry and hidden switch channels.
- Do not publish genset remote-start paths.
- When explicitly approved for this coach, preserve the separately gated
  temporary source-label/current-limit shortcut.  It may write only AC Input 1
  type and the VE.Bus active-input current limit; it never writes DVCC, AGS,
  relays, or RV-C commands.
- Compare logs/UI to SilverLeaf for shore, inverter, pump changes, and one
  attended generator cycle.
- Soak for 24 hours and record CPU/RSS/storage/CAN error counters.

The included read-only sampler records those gates plus unexpected generator
control ownership, any bridge `AUDIT TX`, battery-service count, and active-BMS
availability:

```sh
nohup /data/apps/foretravel-rvc/tools/soak-audit.sh 300 288 \
    > /data/log/foretravel-rvc-soak.stdout 2>&1 &
```

Its TSV output is `/data/log/foretravel-rvc-soak.tsv`.  A valid monitor-only
soak has `service_up=1`, `can_state=ERROR-ACTIVE`, no increasing CAN error or
drop counters attributable to the bridge, `audit_tx_count=0`, and
`generator_owner_count=0` for every sample.

Validate it deterministically after the final sample:

```sh
PYTHONPATH=/data/apps/foretravel-rvc/src \
    /data/apps/foretravel-rvc/tools/analyze-soak.py \
    /data/log/foretravel-rvc-soak.tsv
```

The analyzer fails on missing samples, long gaps, a down service, non-active
CAN state, increased CAN error/drop counters, any bridge TX, any generator
control owner, or a bounded-log overrun.  Battery-service/DVCC outages are
reported as separate warnings because they are not caused by this bridge.

Rollback: run `/data/apps/foretravel-rvc/disable.sh`.  The service shutdown
path restores the conservative Grid/30 A defaults before the service link and
boot hook are removed; verify both values after rollback.

Release upgrades use `install-release.sh`.  The installer validates the staged
configuration as TX-disarmed monitor-only, removes the `/service` link, waits
for both runsv children to exit, retains a timestamped application backup, and
only then swaps directories.  This avoids an old multilog child retaining the
bounded log's lock.  An upgrade deliberately resets controls to monitor-only.

## Stage 2 — Water pump

1. Capture SilverLeaf pump on/off commands and TM-102 status responses.
2. Compare source, DGN, payload, repetition, and response latency.
3. Enable pump only.
4. Test SilverLeaf panel → Venus, physical/bay switch → Venus, Venus → pump.
5. Disconnect/restart bridge during on and off states.
6. Force missing status by stopping monitor and confirm UI disables/faults.

Exit: 20 consecutive bidirectional operations with no desynchronization and
bounded acknowledgment latency.

## Stage 3 — AC source identification

Capture synchronized channels for:

- RV-C raw traffic,
- VE.Bus active input V/F/acceptance/state,
- SilverLeaf screen/physical source,
- generator start/stop markers.

Test transitions:

1. Inverter → shore.
2. Shore → generator (shore still connected).
3. Generator → shore.
4. Generator start with transfer prevented or input rejected.
5. Generator cooldown and stop.

If `ATS_STATUS` remains absent, install or identify an authoritative transfer
signal. Voltage/frequency correlation alone remains diagnostic until it proves
zero false positives across transitions and failure cases.

Exit: source classifier has authoritative evidence and never calls “Generator”
before VE.Bus accepts generator power.

## Stage 4 — Generator cooperative demand

Preconditions:

- Current RV-C profile 65S network-demand payload verified: priority 6,
  `01FCFFFFFFFFFFFF` demand and `00FCFFFFFFFFFFFF` release.  The panel's
  manual-override `5D`/`5C` payloads are not copied.
- Candidate source `0xE2` is free immediately before commissioning and the
  runtime collision check passes.
- Generator and AC telemetry freshness verified.
- Normal 300-second unloaded cooldown implemented.
- Both VE.Bus input-leg current paths validated during a live generator run;
  unloaded threshold, confirmation interval, and hard-stop timeout explicitly
  configured.
- Start timeout and maximum-run policy configured.
- The disarmed release has first passed its Cerbo preflight, service restart,
  D-Bus projection, source-label/current-limit, battery-aggregate, and Ruuvi
  regression checks.

Tests, attended with exhaust clear and loads controlled:

1. Start from Venus with SilverLeaf AGS off.
2. Verify preheat/crank/run/AC/transfer progression.
3. Request off with load present; verify the bridge remains in
   `unload_required` and does not start the cooldown.
4. Remove generator loads; verify both leg currents remain below threshold for
   the full confirmation interval, followed by five continuous unloaded
   minutes, demand release, and stop.
5. Reapply a load during cooldown; verify cooldown resets and no Release is
   sent.
6. Start from SilverLeaf; verify Venus shows external/manual demand.
7. While Venus demands, add an internal/SilverLeaf demand, release Venus, and
   prove generator remains running for the other demand.
8. Stop bridge process while its demand is active and observe TM-102 behavior.
9. Restart bridge; prove startup no-demand cleanup.
10. Simulate Cerbo power loss if a safe hardware test plan exists.
11. Exercise quiet time, generator lock, failed start, VE.Bus rejection, and
   emergency SilverLeaf stop.

Exit: R-02 and R-03 are closed with direct evidence.  Otherwise generator TX
remains disabled.

## Stage 5 — Autofill

- Capture existing panel start/stop and result status.
- Observe destination-specific TM-102 autofill operation `0xED` and water-pump
  operation `0xD4` reports by opening the existing panel pages.  Compare every
  decoded field with the panel; do not transmit a query or configuration write.
- With the bridge monitor-only, open every Total Coach START/AGS page and save
  the simultaneous `0x1FEFE`, `0x1FED2`/`0x17003`, `0x1FFD9`,
  `0x1FED5`/`0x1FEE7`, and proprietary stop-report capture.  Compare every
  populated `/Foretravel/Ags/*` path to the panel before considering AGS
  observation complete.
- Map fresh/black tank instances and validate coach-level warning workflow.
- Enable stop first and prove it from Venus while fill is inactive and active.
- Before start can be armed, require: installation-verification gate, fresh
  autofill/pump/fresh-tank status, an observed nonzero TM-102 timeout, valid
  cutoff and policy flags, level below cutoff, hookup when configured, pump
  policy satisfied, and an explicit local hard maximum run time.
- Then perform an attended start with hose connected and tanks observed.
- Test missing/stale tank, malformed tank resolution, stale pressure/status,
  hookup absent, pump bypass/running policies, zero TM-102 timeout, configured
  cutoff already reached, TM-102 timeout, local hard timeout, full level,
  unacknowledged start, process crash, graceful shutdown, restart with stale
  ownership marker, and CAN/network loss.
- During crash/restart tests, prove the marker remains until a fresh
  `AUTOFILL_STATUS` reports Off and that a process with stop TX unarmed refuses
  to continue with a stale marker.

Exit: all interlocks and orphan-cleanup paths fail closed, and actual status
always overrides requested state.  If configuration cannot be verified,
autofill remains status-only and the project documents that limitation.

## Final audit

- Re-run all offline and live tests.
- Verify exactly one writer per control.
- Verify no forbidden D-Bus/CAN paths.
- Confirm UI/VRM source and statuses across all power states.
- Confirm existing SilverLeaf controls with bridge on/off.
- Confirm rollback and firmware-update recovery.
- Record final configuration, hashes, service status, screenshots, and known
  limitations.
