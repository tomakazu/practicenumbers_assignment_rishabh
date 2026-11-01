from datetime import date

from django.test import TestCase

from .services import decide_outcome
from .validators import expiry_valid, luhn_valid


class ValidatorTests(TestCase):
    def test_luhn(self):
        self.assertTrue(luhn_valid("4242424242424242"))
        self.assertFalse(luhn_valid("4242424242424241"))

    def test_expiry_is_valid_through_the_end_of_the_month(self):
        today = date(2026, 10, 31)
        self.assertTrue(expiry_valid(10, 2026, today))
        self.assertFalse(expiry_valid(9, 2026, today))


class TokenizeEndpointTests(TestCase):
    def tokenize(self, **body):
        return self.client.post("/processor/tokenize", body, content_type="application/json")

    def test_valid_card_returns_token_and_last4_only(self):
        response = self.tokenize(method="card", number="4242 4242 4242 4242", exp_month=12, exp_year=2030, cvv="123")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(set(response.json()), {"token", "method", "last4", "brand_or_bank_type"})
        self.assertEqual(response.json()["last4"], "4242")

    def test_error_codes(self):
        cases = [
            ({"method": "card", "number": "4242424242424241", "exp_month": 12, "exp_year": 2030, "cvv": "123"}, "invalid_number"),
            ({"method": "card", "number": "4242424242424242", "exp_month": 1, "exp_year": 2020, "cvv": "123"}, "invalid_expiry"),
            ({"method": "bank", "account_number": "000123456789", "routing_number": "12345"}, "invalid_routing_number"),
        ]
        for body, code in cases:
            with self.subTest(code=code):
                response = self.tokenize(**body)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"], code)


class OutcomeTableTests(TestCase):
    def test_brief_test_values(self):
        self.assertEqual(decide_outcome("card", "0002"), ("failed", "card_declined", 0))
        self.assertEqual(decide_outcome("bank", "0002"), ("failed", "insufficient_funds", 0))
        self.assertEqual(decide_outcome("card", "0119"), ("failed", "processor_error", 0))
        self.assertEqual(decide_outcome("card", "0341"), ("succeeded", None, 15))
        self.assertEqual(decide_outcome("card", "4242"), ("succeeded", None, 0))
