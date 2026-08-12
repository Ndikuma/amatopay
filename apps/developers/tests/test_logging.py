from django.test import SimpleTestCase

from apps.developers.logging import REDACTED, parse_json_body, redact


class RequestLogRedactionTests(SimpleTestCase):
    def test_redacts_sensitive_fields_recursively(self):
        payload = {
            "client_secret": "checkout-secret",
            "nested": {"password": "password", "safe": "value"},
            "items": [{"access_token": "token"}],
        }

        self.assertEqual(
            redact(payload),
            {
                "client_secret": REDACTED,
                "nested": {"password": REDACTED, "safe": "value"},
                "items": [{"access_token": REDACTED}],
            },
        )

    def test_invalid_or_non_object_json_is_not_logged(self):
        self.assertEqual(parse_json_body(b"not-json"), {})
        self.assertEqual(parse_json_body(b'"secret string"'), {})
