"""Money helpers use integers and Decimal, never binary floats."""

from __future__ import annotations

import unittest
from decimal import Decimal

from letro.money import (
    MoneyError,
    convert_minor,
    currency_decimals,
    format_minor,
    from_minor,
    inverse_rate,
    parse_decimal,
    to_minor,
)


class MoneyTests(unittest.TestCase):
    def test_currency_decimals(self):
        self.assertEqual(currency_decimals("KZT"), 2)
        self.assertEqual(currency_decimals("jpy"), 0)
        with self.assertRaises(MoneyError):
            currency_decimals("BTC")

    def test_to_minor_rounds_half_up(self):
        self.assertEqual(to_minor("1.005", "USD"), 101)
        self.assertEqual(to_minor("1.004", "USD"), 100)
        self.assertEqual(to_minor("250", "JPY"), 250)
        self.assertEqual(to_minor("-2.50", "EUR"), -250)

    def test_from_minor_and_format(self):
        self.assertEqual(from_minor(1234, "USD"), Decimal("12.34"))
        self.assertEqual(from_minor(7, "JPY"), Decimal("7"))
        self.assertEqual(format_minor(1234, "USD"), "12.34")

    def test_convert_minor_is_exact_decimal(self):
        self.assertEqual(convert_minor(10_000, "0.002117", "KZT", "USD"), 21)
        self.assertEqual(convert_minor(100, "1", "USD", "USD"), 100)

    def test_inverse_rate(self):
        self.assertEqual(inverse_rate("2"), Decimal("0.5"))
        with self.assertRaises(MoneyError):
            inverse_rate("0")

    def test_invalid_values(self):
        for value in (None, True, "nan", "inf", "not money", ""):
            with self.assertRaises(MoneyError):
                parse_decimal(value)
        with self.assertRaises(MoneyError):
            convert_minor(100, "-1", "USD", "EUR")
        with self.assertRaises(MoneyError):
            from_minor(1.5, "USD")


if __name__ == "__main__":
    unittest.main()
