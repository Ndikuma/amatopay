import os
from unittest.mock import patch

from django.test import SimpleTestCase

from config.env import env_bool, env_int, env_list


class EnvironmentHelperTests(SimpleTestCase):
    def test_boolean_values_are_explicit(self):
        with patch.dict(os.environ, {"FEATURE_FLAG": "yes"}):
            self.assertTrue(env_bool("FEATURE_FLAG"))
        with patch.dict(os.environ, {"FEATURE_FLAG": "off"}):
            self.assertFalse(env_bool("FEATURE_FLAG"))

    def test_invalid_boolean_raises_clear_error(self):
        with patch.dict(os.environ, {"FEATURE_FLAG": "sometimes"}):
            with self.assertRaisesMessage(
                ValueError, "FEATURE_FLAG must be a boolean value"
            ):
                env_bool("FEATURE_FLAG")

    def test_integer_and_list_parsing(self):
        with patch.dict(os.environ, {"COUNT": "12", "HOSTS": "one, two, ,three"}):
            self.assertEqual(env_int("COUNT", 1), 12)
            self.assertEqual(env_list("HOSTS"), ["one", "two", "three"])
