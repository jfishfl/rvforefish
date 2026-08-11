# 0.5.0-rc2 commissioning regression audit

## Live finding

The first attended cooperative demand was accepted by the TM-102:

- Cerbo source `0xE2`, CAN priority 6.
- Demand payload `01FCFFFFFFFFFFFF`.
- TM-102 network demand true, aggregate demand true, manual override false.
- Generator started and both VE.Bus legs transferred.

Before the TM-102 reported Running, it repeated its prior Stopped state.  rc1
treated that repeat as an aborted start and sent its bounded Release sequence.
The releases were accepted, the TM-102 completed its minimum cycle, stopped,
reported demand false, and the persistent cleanup marker cleared.  Grid/30 A
was restored.

## Correction

While the bridge owns demand and remains in the bounded Starting phase, a
Stopped repeat is treated as preheat/crank progression rather than an aborted
start.  Demand remains asserted until one of three authoritative outcomes:

- Running -> enter Running phase.
- Fault -> release demand and fault.
- 120-second start deadline -> release demand and fault.

A Stopped report after Running or outside the bounded Starting phase retains
the existing fail-safe release behavior.

## Verification

- Regression sequence Stopped -> demand -> Stopped repeat -> Running: pass.
- Complete offline unit/replay/safety suite: **139 tests pass**.
- Python compilation: pass.
- Normal deployed configuration remains TX-disarmed.

## Second attended result

- A pre-start passive survey found `0xE2` newly active, so commissioning moved
  to a verified-silent `0xE3`; the runtime collision refusal remained active.
- The TM-102 accepted the second network demand without manual override.
- rc2 retained demand through the repeated pre-crank Stopped state and entered
  Running normally.
- Both VE.Bus legs transferred, then the guarded shortcut selected Generator
  and 50 A.
- Both legs remained below 5 A for 30 continuous seconds, followed by the full
  300-second unloaded cooldown.
- Release was acknowledged, the generator stopped, ownership and cleanup
  markers cleared, and Grid/30 A was restored.
- The persistent installation was returned to rc2 monitor-only with generator
  TX disabled.

The remaining live gate is intentional controller process loss while its
generator demand is active, followed by startup no-demand cleanup.  That fault
injection was not performed during this run and normal generator control
remains gated.
