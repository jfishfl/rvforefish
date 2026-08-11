# 0.5.0-rc3 orphan-demand recovery audit

## Live process-loss finding

The attended rc2 fault injection started the generator cooperatively from
source `0xE3`, verified Running, Network Demand, bridge ownership, and the
persistent marker, then froze and killed only the verified controller child.
The child was gone while the marker remained.  Restart recovered the marker
without transmitting a new Start and conservatively entered the existing
two-leg unload/cooldown state machine.

The recovered controller correctly retained demand while measured generator
input was 20.85 A (L1 1.91 A, L2 18.94 A), above the 5 A stop threshold.  It
selected Generator/50 A but did not bypass the 30-second unloaded confirmation
or 300-second cooldown.

The Cerbo then rebooted during the recovery run.  The marker survived, but the
temporary `/service` link did not.  After restoring the generator-only recovery
service, the TM-102 reported:

- generator stopped;
- Overall Demand false;
- Network Demand true.

rc2 cleared its marker from Overall Demand alone.  The Network Demand bit
remained true until one explicit source-`0xE3` Release
`00FCFFFFFFFFFFFF` was transmitted while the generator was stopped.

## Root cause and correction

Overall Demand is not proof that a network-demand source has released.  The
TM-102 can report Overall Demand false while Network Demand remains true.
Conversely, an unrelated internal/manual demand can keep Overall Demand true
after this bridge's network category has cleared.

rc3 therefore uses Network Demand false as the authoritative cleanup proof:

- Overall false + Network true retains the marker and, when stopped/faulted,
  transmits the source-specific Release.
- Network false clears the marker even if an unrelated non-network demand
  keeps Overall Demand true.
- Running + Network true still resumes ownership and requires the ordinary
  measured unload and full cooldown before Release.

## Verification

- New stopped-recovery regression with Overall false + Network true: pass.
- New unrelated-demand regression with Overall true + Network false: pass.
- Existing marker, retry, start-timeout, unload, cooldown, and start-race
  regressions: pass.
- Complete offline unit/replay/safety suite: **141 tests pass**.
- Live rc2 lingering Network Demand was cleared with one stopped-generator
  source-specific Release; final Overall and Network Demand were both false.

The rc2 fault injection is evidence for the failure mode, not a release-gate
pass for rc3.  Persistent generator transmission remains disabled until rc3
repeats the attended process-loss recovery and proves Network Demand false,
marker absent, generator stopped, and Grid/30 A restored.
