import unittest

from foretravel_rvc.victron import (
    GENERATOR_SOURCE,
    GRID_SOURCE,
    GeneratorSourceLabelHeuristic,
    VictronAcObserver,
    VictronCurrentLimitWriter,
    VictronInputModeController,
    VictronSourceLabelWriter,
)


SYSTEM = "com.victronenergy.system"
VEBUS = "com.victronenergy.vebus.ttyS4"
SETTINGS = "com.victronenergy.settings"


class VictronAcObserverTests(unittest.TestCase):
    def observer(self, values):
        return VictronAcObserver(lambda service, path: values[(service, path)])

    def values(self):
        return {
            (SYSTEM, "/Ac/ActiveIn/Source"): 1,
            (SYSTEM, "/Ac/In/0/Connected"): 1,
            (SYSTEM, "/VebusService"): VEBUS,
            (VEBUS, "/Ac/ActiveIn/L1/V"): 119.2,
            (VEBUS, "/Ac/ActiveIn/L2/V"): 118.0,
            (VEBUS, "/Ac/ActiveIn/L1/I"): 2.3,
            (VEBUS, "/Ac/ActiveIn/L2/I"): -0.7,
            (VEBUS, "/Ac/ActiveIn/CurrentLimit"): 30.0,
        }

    def test_split_phase_input_uses_direct_vebus_values(self):
        state = self.observer(self.values()).read()
        self.assertTrue(state.fresh)
        self.assertTrue(state.accepting_ac)
        self.assertEqual(state.l1_voltage, 119.2)
        self.assertEqual(state.l2_voltage, 118.0)
        self.assertAlmostEqual(state.active_input_total_current, 3.0)
        self.assertEqual(state.reported_source, "grid")
        self.assertTrue(state.both_legs_valid())

    def test_inverting_is_not_accepted_ac(self):
        values = self.values()
        values[(SYSTEM, "/Ac/ActiveIn/Source")] = 240
        values[(SYSTEM, "/Ac/In/0/Connected")] = 0
        state = self.observer(values).read()
        self.assertFalse(state.accepting_ac)
        self.assertEqual(state.reported_source, "inverting")

    def test_dbus_failure_is_explicitly_stale(self):
        state = VictronAcObserver(
            lambda service, path: (_ for _ in ()).throw(RuntimeError("down"))
        ).read()
        self.assertFalse(state.fresh)
        self.assertFalse(state.accepting_ac)
        self.assertIn("down", state.error)


class GeneratorSourceLabelHeuristicTests(unittest.TestCase):
    def state(self, *, valid=True):
        values = VictronAcObserverTests().values()
        if not valid:
            values[(VEBUS, "/Ac/ActiveIn/L2/V")] = 0.0
        return VictronAcObserverTests().observer(values).read()

    def test_requires_sixty_seconds_and_two_stable_legs_for_50_amp(self):
        heuristic = GeneratorSourceLabelHeuristic(
            delay_seconds=60.0,
            stable_seconds=5.0,
            status_stale_seconds=90.0,
        )
        first = heuristic.update(
            now=100.0,
            generator_status_raw=3,
            generator_status_seen=100.0,
            ac_state=self.state(),
        )
        self.assertEqual(first.target, GRID_SOURCE)
        confirmed = heuristic.update(
            now=160.0,
            generator_status_raw=3,
            generator_status_seen=160.0,
            ac_state=self.state(),
        )
        self.assertEqual(confirmed.target, GENERATOR_SOURCE)
        self.assertTrue(confirmed.allow_50_amp_current_limit)

    def test_generator_status_stale_fails_back_to_grid(self):
        heuristic = GeneratorSourceLabelHeuristic()
        decision = heuristic.update(
            now=200.0,
            generator_status_raw=3,
            generator_status_seen=100.0,
            ac_state=self.state(),
        )
        self.assertEqual(decision.target, GRID_SOURCE)


class WriterTests(unittest.TestCase):
    def test_input_mode_orders_generator_label_before_50_amp(self):
        values = {
            (SETTINGS, "/Settings/SystemSetup/AcInput1"): GRID_SOURCE,
            (SYSTEM, "/VebusService"): VEBUS,
            (VEBUS, "/Ac/ActiveIn/CurrentLimit"): 30.0,
        }
        writes = []

        def getter(service, path):
            return values[(service, path)]

        def setter(service, path, value):
            writes.append((service, path, value))
            values[(service, path)] = value
            return 0

        source = VictronSourceLabelWriter(getter, setter)
        current = VictronCurrentLimitWriter(getter, setter)
        controller = VictronInputModeController(source, current)
        ac_state = VictronAcObserverTests().observer(
            VictronAcObserverTests().values()
        ).read()
        decision = GeneratorSourceLabelHeuristic(
            delay_seconds=60.0,
            stable_seconds=5.0,
        )
        decision.update(
            now=100.0,
            generator_status_raw=3,
            generator_status_seen=100.0,
            ac_state=ac_state,
        )
        confirmed = decision.update(
            now=160.0,
            generator_status_raw=3,
            generator_status_seen=160.0,
            ac_state=ac_state,
        )
        controller.apply(confirmed, ac_state)
        self.assertEqual(writes[0][1], "/Settings/SystemSetup/AcInput1")
        self.assertEqual(writes[1][1], "/Ac/ActiveIn/CurrentLimit")
        self.assertEqual(writes[1][2], 50.0)


if __name__ == "__main__":
    unittest.main()
