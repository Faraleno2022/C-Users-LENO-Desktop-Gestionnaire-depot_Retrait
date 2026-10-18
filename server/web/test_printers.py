"""Impression directe des tickets de la console locale (ESC/POS) : détection,
octets produits, endpoint d'envoi et repli sur le navigateur."""
import os
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from sync.models import RemoteUser
from web import printers


class PrinterDetectionTests(SimpleTestCase):
    NAMES = ["Microsoft Print to PDF", "HP LaserJet", "EPSON TM-T20III Ticket"]

    def test_epson_is_detected_and_virtual_printers_are_ignored(self):
        pick = printers.pick_receipt_printer
        self.assertEqual(pick("Microsoft Print to PDF", self.NAMES), "EPSON TM-T20III Ticket")
        self.assertEqual(pick("HP LaserJet", self.NAMES), "EPSON TM-T20III Ticket")
        self.assertEqual(pick("HP LaserJet", ["HP LaserJet", "Microsoft Print to PDF"]), "")

    def test_requested_name_wins_but_unknown_name_falls_back(self):
        pick = printers.pick_receipt_printer
        names = self.NAMES + ["POZER TP150"]
        self.assertEqual(pick("EPSON TM-T20III Ticket", names, "pozer tp150"), "POZER TP150")
        self.assertEqual(pick("HP LaserJet", self.NAMES, "Inconnue"), "EPSON TM-T20III Ticket")

    def test_office_printer_only_with_browser_fallback(self):
        names = ["HP LaserJet"]
        self.assertEqual(printers.pick_receipt_printer("HP LaserJet", names), "")
        self.assertEqual(printers.pick_receipt_printer("HP LaserJet", names, fallback=True), "HP LaserJet")

    def test_environment_variable_beats_configured_name(self):
        with patch.dict(os.environ, {"EMAB_RECEIPT_PRINTER": "env-printer"}):
            self.assertEqual(printers.requested_printer("fichier"), "env-printer")
        with patch.dict(os.environ, {"EMAB_RECEIPT_PRINTER": ""}):
            self.assertEqual(printers.requested_printer("fichier"), "fichier")


class EscPosBytesTests(SimpleTestCase):
    def build(self, width="80", **kw):
        args = dict(
            company={"name": "EMAB-SKS", "address": "Conakry", "phone": "+224 600"},
            title="REÇU DE DÉPÔT", number="N° 12", date="2026-10-18 09:00:00",
            info_rows=[("Matricule", "M-001"), ("Tél.", ""), ("Agent", "Admin")],
            items=[], balance_before="1 000 GNF", action_label="DÉPÔT",
            action_value="+5 000 GNF", balance_after="6 000 GNF",
            footer=["Merci de votre confiance", "EMAB-SKS"], paper_width=width)
        args.update(kw)
        return printers.build_ticket(**args)

    def test_stream_has_init_codepage_accents_and_cut(self):
        data = self.build()
        self.assertTrue(data.startswith(b"\x1b@\x1bt\x13"))
        self.assertIn(b"\x1dV\x42\x03", data)
        self.assertIn("DÉPÔT".encode("cp858"), data)
        self.assertIn(b"Merci de votre confiance", data)
        self.assertNotIn(b"T\x82l.", data, "une ligne vide ne doit pas être imprimée")

    def test_rows_are_aligned_on_paper_width(self):
        for width, cols in (("80", 48), ("58", 32)):
            line = next(l for l in self.build(width).split(b"\n") if b"M-001" in l)
            self.assertEqual(len(line[line.index(b"Matricule"):]), cols)

    def test_sale_lines_are_printed(self):
        data = self.build(items=[{"name": "Riz 50kg", "detail": "2 x 10 000 GNF", "total": "20 000 GNF"}])
        self.assertIn(b"Riz 50kg", data)
        self.assertIn(b"20 000 GNF", data)


class EscPosEndpointTests(TestCase):
    def setUp(self):
        self.remote = RemoteUser.objects.create(uuid=str(uuid.uuid4()), identifiant="t", nom_complet="Caissier",
                                                role="super_admin", created_at="now", updated_at="now")
        self.client.force_login(get_user_model().objects.create_user(username="t"))
        session = self.client.session
        session["remote_user"] = {"id": self.remote.id, "uuid": self.remote.uuid, "role": "super_admin"}
        session["last_deposit"] = {"id": 7, "matricule": "M-001", "telephone": "", "montant": 5000,
                                   "solde_apres": 6000, "created_at": "2026-10-18 09:00:00", "agent_nom": "Admin"}
        session.save()
        self.url = reverse("web:print_ticket_escpos")

    def test_refused_on_online_server(self):
        with patch.dict(os.environ, {"EMAB_LOCAL_CONSOLE": "0"}):
            response = self.client.post(self.url, {"kind": "depot"})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()["ok"])

    def test_get_is_not_allowed(self):
        with patch.dict(os.environ, {"EMAB_LOCAL_CONSOLE": "1"}):
            self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_local_console_sends_ticket_to_the_thermal_printer(self):
        sent = {}
        env = {"EMAB_LOCAL_CONSOLE": "1", "EMAB_RECEIPT_PRINTER": ""}
        with patch.dict(os.environ, env), \
             patch.object(printers, "windows_printers", return_value=("HP LaserJet", ["HP LaserJet", "EPSON TM-T20III Ticket"])), \
             patch.object(printers, "send_raw", side_effect=lambda name, data, *a, **k: sent.update(name=name, data=data)):
            response = self.client.post(self.url, {"kind": "depot", "w": "58"})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json(), {"ok": True, "printer": "EPSON TM-T20III Ticket"})
        self.assertEqual(sent["name"], "EPSON TM-T20III Ticket")
        data = sent["data"]
        self.assertIn(b"M-001", data)
        self.assertIn(b"+5 000 GNF", data)
        self.assertIn(b"6 000 GNF", data)
        self.assertIn("DÉPÔT".encode("cp858"), data)

    def test_no_thermal_printer_returns_error_so_page_falls_back(self):
        env = {"EMAB_LOCAL_CONSOLE": "1", "EMAB_RECEIPT_PRINTER": ""}
        with patch.dict(os.environ, env), \
             patch.object(printers, "windows_printers", return_value=("HP LaserJet", ["HP LaserJet"])):
            response = self.client.post(self.url, {"kind": "depot"})
        self.assertEqual(response.status_code, 502)
        self.assertFalse(response.json()["ok"])

    def test_nothing_to_print(self):
        session = self.client.session
        session.pop("last_withdrawal", None)
        session.save()
        with patch.dict(os.environ, {"EMAB_LOCAL_CONSOLE": "1"}):
            self.assertEqual(self.client.post(self.url, {"kind": "retrait"}).status_code, 404)

    def test_ticket_page_uses_direct_printing_only_with_a_thermal_printer(self):
        page = reverse("web:print_ticket")
        env = {"EMAB_LOCAL_CONSOLE": "1", "EMAB_RECEIPT_PRINTER": ""}
        with patch.dict(os.environ, env), \
             patch.object(printers, "windows_printers", return_value=("", ["EPSON TM-T20III Ticket"])):
            self.assertIn("var ESCPOS = true", self.client.get(page, {"kind": "depot"}).content.decode())
        with patch.dict(os.environ, env), \
             patch.object(printers, "windows_printers", return_value=("", ["HP LaserJet"])):
            self.assertIn("var ESCPOS = false", self.client.get(page, {"kind": "depot"}).content.decode())
        with patch.dict(os.environ, {"EMAB_LOCAL_CONSOLE": "0"}):
            self.assertIn("var ESCPOS = false", self.client.get(page, {"kind": "depot"}).content.decode())
