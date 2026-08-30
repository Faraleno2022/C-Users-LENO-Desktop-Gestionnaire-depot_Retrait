import os
import unittest
from unittest.mock import patch

from server import console_web


class ReceiptPrinterSelectionTests(unittest.TestCase):
    def test_windows_default_replaces_old_thermal_driver(self):
        printers = ("POZER TP150", ["XP-80C", "POZER TP150"])
        with (
            patch.object(console_web, "_windows_printers", return_value=printers),
            patch.dict(os.environ, {"EMAB_RECEIPT_PRINTER": ""}),
        ):
            self.assertEqual(console_web._pick_receipt_printer(), "POZER TP150")

    def test_pozer_is_detected_when_default_is_virtual(self):
        printers = (
            "Microsoft Print to PDF",
            ["Microsoft Print to PDF", "POZER TP150"],
        )
        with (
            patch.object(console_web, "_windows_printers", return_value=printers),
            patch.dict(os.environ, {"EMAB_RECEIPT_PRINTER": ""}),
        ):
            self.assertEqual(console_web._pick_receipt_printer(), "POZER TP150")

    def test_explicit_printer_can_override_windows_default(self):
        printers = ("Office Laser", ["Office Laser", "POZER TP150"])
        with (
            patch.object(console_web, "_windows_printers", return_value=printers),
            patch.dict(os.environ, {"EMAB_RECEIPT_PRINTER": "pozer tp150"}),
        ):
            self.assertEqual(console_web._pick_receipt_printer(), "POZER TP150")

    def test_thermal_printer_beats_default_office_printer(self):
        printers = ("Office Laser", ["Office Laser", "POZER TP150"])
        with (
            patch.object(console_web, "_windows_printers", return_value=printers),
            patch.dict(os.environ, {"EMAB_RECEIPT_PRINTER": ""}),
        ):
            self.assertEqual(console_web._pick_receipt_printer(), "POZER TP150")

    def test_virtual_printers_are_not_selected(self):
        printers = (
            "Microsoft Print to PDF",
            ["Microsoft Print to PDF", "Fax", "OneNote"],
        )
        with (
            patch.object(console_web, "_windows_printers", return_value=printers),
            patch.dict(os.environ, {"EMAB_RECEIPT_PRINTER": ""}),
        ):
            self.assertEqual(console_web._pick_receipt_printer(), "")


if __name__ == "__main__":
    unittest.main()
