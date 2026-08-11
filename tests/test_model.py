import unittest

from foretravel_rvc.model import SourceClass, classify_ac_source


class SourceClassificationTests(unittest.TestCase):
    def classify(self, **overrides):
        values = {
            "ve_bus_accepting_ac": False,
            "active_input_voltage": None,
            "generator_voltage": None,
            "generator_frequency": None,
            "ats_source": None,
            "generator_demand": False,
            "ats_fresh": False,
            "generator_ac_fresh": False,
        }
        values.update(overrides)
        return classify_ac_source(**values)

    def test_inverting(self):
        result = self.classify()
        self.assertEqual(result.source, SourceClass.INVERTING)
        self.assertTrue(result.safe_to_write_victron_label)

    def test_generator_starting_is_not_generator_supply(self):
        result = self.classify(generator_demand=True)
        self.assertEqual(result.source, SourceClass.GENERATOR_STARTING)
        self.assertFalse(result.safe_to_write_victron_label)

    def test_generator_supply_requires_three_way_agreement(self):
        result = self.classify(
            ve_bus_accepting_ac=True,
            active_input_voltage=120.0,
            generator_voltage=121.0,
            generator_frequency=60.0,
            ats_source="generator",
            ats_fresh=True,
            generator_ac_fresh=True,
        )
        self.assertEqual(result.source, SourceClass.GENERATOR)
        self.assertTrue(result.safe_to_write_victron_label)

    def test_generator_available_but_not_accepted_is_fault_state(self):
        result = self.classify(
            generator_voltage=120.0,
            generator_frequency=60.0,
            ats_source="generator",
            ats_fresh=True,
            generator_ac_fresh=True,
        )
        self.assertEqual(result.source, SourceClass.GENERATOR_NOT_ACCEPTED)
        self.assertFalse(result.safe_to_write_victron_label)

    def test_shore_requires_fresh_ats(self):
        result = self.classify(
            ve_bus_accepting_ac=True,
            active_input_voltage=119.0,
            ats_source="shore",
            ats_fresh=True,
        )
        self.assertEqual(result.source, SourceClass.SHORE)
        self.assertTrue(result.safe_to_write_victron_label)

    def test_stale_ats_never_guesses_shore(self):
        result = self.classify(
            ve_bus_accepting_ac=True,
            active_input_voltage=119.0,
            ats_source="shore",
            ats_fresh=False,
        )
        self.assertEqual(result.source, SourceClass.AC_UNKNOWN)
        self.assertFalse(result.safe_to_write_victron_label)

    def test_stale_generator_ac_never_claims_generator(self):
        result = self.classify(
            ve_bus_accepting_ac=True,
            active_input_voltage=120.0,
            generator_voltage=120.0,
            generator_frequency=60.0,
            ats_source="generator",
            ats_fresh=True,
            generator_ac_fresh=False,
        )
        self.assertEqual(result.source, SourceClass.AC_UNKNOWN)

    def test_failed_vebus_observation_never_guesses_inverting(self):
        result = self.classify(ve_bus_state_fresh=False)
        self.assertEqual(result.source, SourceClass.AC_UNKNOWN)
        self.assertFalse(result.safe_to_write_victron_label)


if __name__ == "__main__":
    unittest.main()
