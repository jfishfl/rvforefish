# 0.5.0-rc4 TM-102 demand keepalive audit

## Corrected live finding

The attended rc3 process-loss retest passed the intended orphan controls:

- source `0xE3` asserted cooperative Network Demand with no manual override;
- the verified controller PID was frozen and killed while its persistent
  marker remained;
- restart required fresh Network Demand and active-engine status before
  recovering ownership;
- recovered demand was retained at about 20 A rather than released under load;
- when the engine later stopped, rc3 sent one source-specific Release, Network
  Demand became false, the marker cleared, and Grid/30 A was restored.

However, the engine stopped at the TM-102's configured five-minute
minimum-cycle boundary before rc3 transmitted Release.  The same ordering was
present in both prior rc2 runs: Overall Demand false, Generator Stopped, then
bridge Release.  No `REQUEST FOR DGN` asking this source to reassert
`GENERATOR_DEMAND_COMMAND` was observed.

The earlier statement that a bridge Release caused those generator stops is
therefore superseded.  Unload measurement and cooldown timing worked, but the
source-specific release-to-stop sequence was not yet proven.

## Specification and compatibility decision

RVIA section 6.35.3 defines cooperative Generator Demand as `As needed`,
requires demand sources to answer requests for the DGN, and permits an AGS to
poll demanders or maintain a demand list.  This older TM-102 does not poll the
bridge before its observed five-minute stop.  rc4 therefore sends a bounded
60-second keepalive while—and only while—the bridge owns demand.

The keepalive is the same priority-6 payload already accepted live:
`01FCFFFFFFFFFFFF`.  It does not assert Manual Override, Quiet Time Override,
Generator Lock, or either External Activity action.  An addressed/global
TM-102 request still receives an immediate response and resets the next
periodic deadline.

Keepalive behavior is fail-safe bounded:

- interval configuration is restricted to 10–120 seconds;
- marker-before-first-TX ordering is unchanged;
- process recovery transmits nothing until fresh Network Demand true and an
  active engine state prove ownership, then immediately reasserts demand;
- keepalive continues through source/current unload confirmation and the full
  300-second cooldown so the TM-102 cannot stop the hot generator early;
- the keepalive deadline is cleared before a source-specific Release;
- a fresh external/manual engine stop still causes immediate demand cleanup.

## Offline verification

- 60-second keepalive during unload/cooldown: pass.
- Immediate reassertion after fresh running-marker recovery: pass.
- Keepalive interval bounds and non-finite rejection: pass.
- Request-response, start timeout, source-specific cleanup, retry,
  marker-before-TX, load return, stop escalation and external-stop tests: pass.
- Complete unit/replay/safety suite: **144 tests pass**.

## Remaining live gate

Persistent generator transmission remains disabled.  One attended rc4 run must
prove all of the following in order:

1. cooperative demand is accepted and the engine transfers to Generator/50 A;
2. at least five periodic `01FC...` keepalives are transmitted and the engine
   remains running beyond the five-minute TM-102 boundary;
3. both input legs remain below 5 A for 30 continuous seconds;
4. the full 300-second unloaded cooldown completes while the engine remains
   running;
5. rc4 sends `00FC...` before Generator Stopped and Network Demand false;
6. the marker clears and Grid/30 A is restored.
