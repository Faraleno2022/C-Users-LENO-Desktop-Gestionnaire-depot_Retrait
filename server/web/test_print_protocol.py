"""Impression directe depuis le site en ligne : lien `emab-print:` (encodage,
validation stricte, gestionnaire du poste) et boutons du site."""
import base64
import json
import os
import tempfile
import uuid
import zlib
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from sync.models import RemoteUser
from web import print_protocol as pp
from web import printers


def sample_kwargs(**over):
    kw = {
        "company": {"name": "EMAB-SKS", "address": "Conakry", "phone": "+224 600"},
        "title": "REÇU DE DÉPÔT", "number": "N° 12", "date": "2026-10-18 09:00:00",
        "info_rows": [["Matricule", "M-001"], ["Tél.", ""], ["Agent", "Admin"]],
        "items": [], "balance_before": "1 000 GNF", "action_label": "DÉPÔT",
        "action_value": "+5 000 GNF", "balance_after": "6 000 GNF",
        "footer": ["Merci de votre confiance", "EMAB-SKS"], "paper_width": "80",
    }
    kw.update(over)
    return kw


def forge(obj) -> str:
    raw = json.dumps(obj).encode()
    return f"emab-print:v1.{base64.urlsafe_b64encode(zlib.compress(raw)).decode().rstrip('=')}"


class ProtocolTests(SimpleTestCase):
    def test_round_trip_keeps_the_ticket(self):
        url = pp.encode(sample_kwargs())
        self.assertTrue(url.startswith("emab-print:v1."))
        self.assertNotIn("/", url.split(":", 1)[1], "pas de // : Chrome ne doit pas toucher à la casse")
        decoded = pp.decode(url)
        self.assertEqual(decoded["title"], "REÇU DE DÉPÔT")
        self.assertEqual(decoded["info_rows"][0], ("Matricule", "M-001"))
        self.assertEqual(decoded["balance_after"], "6 000 GNF")

    def test_decode_tolerates_quotes_and_slashes_added_by_windows(self):
        url = pp.encode(sample_kwargs())
        for variant in (f'"{url}"', url.replace("emab-print:", "emab-print://") + "/", url.upper().replace(url.split(".", 1)[1].upper(), url.split(".", 1)[1])):
            self.assertEqual(pp.decode(variant)["number"], "N° 12", variant)

    def test_control_characters_cannot_inject_escpos_commands(self):
        evil = "A\x1bp\x00\x19\xfaB\x1dV\x00C\x07\n\rD"
        decoded = pp.decode(pp.encode(sample_kwargs(info_rows=[["Matricule", evil]], title=evil)))
        for text in (decoded["info_rows"][0][1], decoded["title"]):
            self.assertTrue(all(ch >= " " for ch in text), repr(text))
        bytes_out = printers.build_ticket(**decoded)
        self.assertNotIn(b"\x1bp\x00\x19\xfa", bytes_out, "ouverture de tiroir injectée")
        self.assertEqual(bytes_out.count(b"\x1dV"), 1, "une seule coupe, celle du ticket")

    def test_rejects_garbage_and_unknown_versions(self):
        for bad in ("", "http://x", "emab-print:", "emab-print:v1.", "emab-print:v1.!!!!", "emab-print:v2.abcd",
                    "emab-print:v1." + base64.urlsafe_b64encode(b"pas du zlib").decode(),
                    forge([1, 2, 3]), forge({"info_rows": [["un seul"]]}), forge({"items": ["x"]})):
            with self.assertRaises(pp.ProtocolError, msg=bad):
                pp.decode(bad)

    def test_decompression_bomb_is_refused(self):
        bomb = zlib.compress(b'{"title":"' + b"A" * 5_000_000 + b'"}', 9)
        url = "emab-print:v1." + base64.urlsafe_b64encode(bomb).decode().rstrip("=")
        with self.assertRaises(pp.ProtocolError):
            pp.decode(url)

    def test_limits_are_enforced(self):
        items = [{"name": f"Article {i}", "detail": "1 x 1 GNF", "total": "1 GNF"} for i in range(200)]
        decoded = pp.decode(forge(sample_kwargs(items=items, footer=["x"] * 30, title="T" * 500)))
        self.assertEqual(len(decoded["items"]), pp.MAX_ITEMS)
        self.assertEqual(len(decoded["footer"]), pp.MAX_FOOTER)
        self.assertLessEqual(len(decoded["title"]), 60)
        self.assertEqual(pp.decode(forge(sample_kwargs(paper_width="999")))["paper_width"], "80")

    def test_oversized_links_are_not_offered(self):
        items = [{"name": f"Produit numéro {i} très long {uuid.uuid4()}", "detail": "12 x 150 000 GNF", "total": "1 800 000 GNF"}
                 for i in range(40)]
        self.assertEqual(pp.encode_checked(sample_kwargs(items=items)), "")
        self.assertNotEqual(pp.encode_checked(sample_kwargs()), "")

    def test_typical_sale_fits_in_the_windows_limit(self):
        items = [{"name": f"Produit {i}", "detail": "2 x 10 000 GNF", "total": "20 000 GNF"} for i in range(8)]
        self.assertNotEqual(pp.encode_checked(sample_kwargs(items=items)), "")


class HandlerTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="emab_handler_")
        self.sent = {}
        self.env = patch.dict(os.environ, {"EMAB_DATA_DIR": self.tmp, "EMAB_RECEIPT_PRINTER": ""})
        self.env.start()
        self.win = patch.object(printers, "windows_printers",
                                return_value=("HP LaserJet", ["HP LaserJet", "EPSON TM-T20III Ticket"]))
        self.win.start()

    def tearDown(self):
        self.win.stop()
        self.env.stop()

    def sender(self, name, data):
        self.sent.update(name=name, data=data)

    def test_run_prints_to_the_thermal_printer_and_logs(self):
        code = pp.run(["x.exe", "--print-url", pp.encode(sample_kwargs())], sender=self.sender, show_errors=False)
        self.assertEqual(code, 0)
        self.assertEqual(self.sent["name"], "EPSON TM-T20III Ticket")
        self.assertIn(b"M-001", self.sent["data"])
        self.assertIn(b"+5 000 GNF", self.sent["data"])
        self.assertIn("envoyé", (Path(self.tmp) / "print_handler.log").read_text(encoding="utf-8"))

    def test_configured_printer_in_the_data_folder_is_used(self):
        (Path(self.tmp) / "printer_config.json").write_text(json.dumps({"printer": "POZER TP150"}), encoding="utf-8")
        with patch.object(printers, "windows_printers", return_value=("", ["EPSON TM-T20III Ticket", "POZER TP150"])):
            pp.run(["x.exe", "--print-url", pp.encode(sample_kwargs())], sender=self.sender, show_errors=False)
        self.assertEqual(self.sent["name"], "POZER TP150")

    def test_the_link_cannot_choose_the_printer(self):
        url = pp.encode(sample_kwargs() | {"printer": "HP LaserJet", "paper_width": "58"})
        pp.run(["x.exe", "--print-url", url], sender=self.sender, show_errors=False)
        self.assertEqual(self.sent["name"], "EPSON TM-T20III Ticket")

    def test_failures_return_an_error_code_without_printing(self):
        self.assertEqual(pp.run(["x.exe", "--print-url", "emab-print:v1.zzz"], sender=self.sender, show_errors=False), 1)
        self.assertEqual(pp.run(["x.exe"], sender=self.sender, show_errors=False), 2)
        with patch.object(printers, "windows_printers", return_value=("HP LaserJet", ["HP LaserJet"])):
            self.assertEqual(pp.run(["x.exe", "--print-url", pp.encode(sample_kwargs())], sender=self.sender, show_errors=False), 1)
        self.assertEqual(self.sent, {})
        log = (Path(self.tmp) / "print_handler.log").read_text(encoding="utf-8")
        self.assertIn("refusé", log)
        self.assertIn("Aucune imprimante", log)


class SitePagesTests(TestCase):
    def setUp(self):
        self.remote = RemoteUser.objects.create(uuid=str(uuid.uuid4()), identifiant="t", nom_complet="Caissier",
                                                role="super_admin", created_at="now", updated_at="now")
        self.client.force_login(get_user_model().objects.create_user(username="t"))
        session = self.client.session
        session["remote_user"] = {"id": self.remote.id, "uuid": self.remote.uuid, "role": "super_admin"}
        session["last_deposit"] = {"id": 7, "matricule": "M-001", "telephone": "", "montant": 5000,
                                   "solde_apres": 6000, "created_at": "2026-10-18 09:00:00", "agent_nom": "Admin"}
        session["last_withdrawal"] = {
            "id": 8, "matricule": "M-002", "telephone": "", "montant": 20000, "solde_avant": 50000,
            "solde_apres": 30000, "created_at": "2026-10-18 09:05:00", "agent_nom": "Admin", "is_sale": True,
            "lines": [{"product_nom": "Riz 50kg", "quantite": 2, "prix": 10000, "total": 20000}]}
        session.save()

    def link_in(self, html):
        start = html.index('href="emab-print:') + len('href="')
        return html[start: html.index('"', start)]

    def test_online_deposit_page_offers_a_decodable_direct_link(self):
        with patch.dict(os.environ, {"EMAB_LOCAL_CONSOLE": "0"}):
            html = self.client.get(reverse("web:deposit_new")).content.decode()
        self.assertIn("Imprimer (direct, poste équipé)", html)
        decoded = pp.decode(self.link_in(html))
        self.assertEqual(decoded["title"], "REÇU DE DÉPÔT")
        self.assertEqual(decoded["action_value"], "+5 000 GNF")
        self.assertEqual(decoded["info_rows"][0], ("Matricule", "M-001"))

    def test_online_withdrawal_page_link_contains_the_sale_lines(self):
        with patch.dict(os.environ, {"EMAB_LOCAL_CONSOLE": "0"}):
            html = self.client.get(reverse("web:withdrawal_new")).content.decode()
        decoded = pp.decode(self.link_in(html))
        self.assertEqual(decoded["action_label"], "VENTE")
        self.assertEqual(decoded["items"][0]["name"], "Riz 50kg")
        self.assertEqual(decoded["items"][0]["total"], "20 000 GNF")

    def test_ticket_page_and_settings_page_offer_the_link_online_only(self):
        with patch.dict(os.environ, {"EMAB_LOCAL_CONSOLE": "0"}):
            ticket = self.client.get(reverse("web:print_ticket"), {"kind": "depot"}).content.decode()
            settings = self.client.get(reverse("web:ticket_settings")).content.decode()
        self.assertIn("Impression directe", ticket)
        self.assertIn("emab-print:v1.", ticket)
        self.assertIn("Tester l'impression directe", settings)
        self.assertEqual(pp.decode(self.link_in(settings))["title"], "TICKET DE TEST")

    def test_local_console_has_no_emab_print_link(self):
        env = {"EMAB_LOCAL_CONSOLE": "1", "EMAB_RECEIPT_PRINTER": ""}
        with patch.dict(os.environ, env), \
             patch.object(printers, "windows_printers", return_value=("", ["EPSON TM-T20III Ticket"])):
            for page in (self.client.get(reverse("web:deposit_new")),
                         self.client.get(reverse("web:print_ticket"), {"kind": "depot"}),
                         self.client.get(reverse("web:ticket_settings"))):
                self.assertNotIn("emab-print:", page.content.decode())

    def test_nothing_to_print_means_no_link(self):
        session = self.client.session
        session.pop("last_deposit", None)
        session.save()
        with patch.dict(os.environ, {"EMAB_LOCAL_CONSOLE": "0"}):
            self.assertNotIn("emab-print:", self.client.get(reverse("web:deposit_new")).content.decode())
