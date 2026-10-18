"""Test de l'impression des tickets (ESC/POS, détection d'imprimante, réglages).

Aucune imprimante n'est nécessaire : l'envoi au spouleur est remplacé par une
fonction qui capture les octets.
"""
from __future__ import annotations

import tempfile
from pathlib import Path


def main() -> int:
    import app.config as cfg
    tmp = Path(tempfile.mkdtemp(prefix="gest_print_test_"))
    cfg.DATA_DIR = tmp
    cfg.BACKUP_DIR = tmp / "backups"
    cfg.DB_PATH = tmp / "test.db"
    cfg.EXPORT_DIR = tmp / "exports"
    cfg.LOG_DIR = tmp / "logs"
    cfg.ensure_directories()

    from app.db import database as db
    db._local.conn = None
    from app.db.database import init_database
    init_database()

    from app.services import settings_service
    from app.utils import receipt_printer as rp

    # 1. Détection : l'Epson TM-T20III est reconnue, les virtuelles écartées.
    names = ["Microsoft Print to PDF", "HP LaserJet", "EPSON TM-T20III Receipt"]
    assert rp.pick_receipt_printer("Microsoft Print to PDF", names) == "EPSON TM-T20III Receipt"
    assert rp.pick_receipt_printer("HP LaserJet", names) == "EPSON TM-T20III Receipt"
    assert rp.pick_receipt_printer("HP LaserJet", ["HP LaserJet", "Microsoft Print to PDF"]) == ""
    # Nom imposé (insensible à la casse) prioritaire sur la détection.
    assert rp.pick_receipt_printer("EPSON TM-T20III Receipt", names + ["POZER TP150"],
                                   requested="pozer tp150") == "POZER TP150"
    # Un nom imposé introuvable retombe sur la détection.
    assert rp.pick_receipt_printer("HP LaserJet", names, requested="Inconnue") == "EPSON TM-T20III Receipt"
    # Pilote générique nommé par l'utilisateur sans mot-clé : utilisable via le réglage.
    assert rp.pick_receipt_printer("Generic / Text Only", ["Generic / Text Only"]) == ""
    assert rp.pick_receipt_printer("Generic / Text Only", ["Generic / Text Only"],
                                   requested="Generic / Text Only") == "Generic / Text Only"

    # 2. Flux ESC/POS : initialisation, page de code, texte accentué, coupe.
    receipt = rp.Receipt(
        title="REÇU D'OPÉRATION", number="N° 12", date="2026-10-18 09:00:00",
        highlight_label="DÉPÔT", highlight_value="150 000 GNF",
        rows=[("Matricule", "M-001"), ("Nouveau solde", "1 250 000 GNF"),
              ("Un libellé vraiment très long qui dépasse la largeur", "valeur")],
        reference="abcd-1234",
    )
    company = {"name": "EMAB GROUP", "address": "Conakry", "phone": "+224 600 00 00 00",
               "email": "", "footer": "Merci de votre visite"}
    data = rp.build_escpos(receipt, company, paper_width="80")
    assert data.startswith(b"\x1b@\x1bt\x13"), data[:6]
    assert b"\x1dV\x42\x03" in data, "coupe papier absente"
    assert "DÉPÔT".encode("cp858") in data
    assert b"EMAB GROUP" in data and b"Merci de votre visite" in data
    assert b"\x1bp\x00\x19\xfa" not in data
    assert b"\x1bp\x00\x19\xfa" in rp.build_escpos(receipt, company, open_drawer=True)
    # Ligne libellé/valeur alignée sur 48 colonnes.
    lines = [l for l in data.split(b"\n") if b"M-001" in l]
    row = lines[0][lines[0].index(b"Matricule"):]   # ignore la commande d'alignement
    assert len(row) == 48, row
    # 58 mm → 32 colonnes.
    data58 = rp.build_escpos(receipt, company, paper_width="58")
    lines58 = [l for l in data58.split(b"\n") if b"M-001" in l]
    row58 = lines58[0][lines58[0].index(b"Matricule"):]
    assert len(row58) == 32, row58

    # 3. print_receipt : utilise la détection + l'expéditeur fourni.
    sent = {}

    def fake_sender(name, payload):
        sent["name"], sent["data"] = name, payload

    rp.windows_printers = lambda: ("HP LaserJet", names)  # type: ignore
    used = rp.print_receipt(receipt, company, sender=fake_sender)
    assert used == "EPSON TM-T20III Receipt" and sent["name"] == used
    assert sent["data"] == data

    rp.windows_printers = lambda: ("HP LaserJet", ["HP LaserJet"])  # type: ignore
    try:
        rp.print_receipt(receipt, company, sender=fake_sender)
    except rp.NoReceiptPrinter:
        pass
    else:
        raise AssertionError("NoReceiptPrinter attendu sans imprimante thermique")

    # 4. HTML : aperçu écran coloré, version impression en noir.
    html_screen = rp.render_html(receipt, company)
    html_print = rp.render_html(receipt, company, for_print=True)
    assert "REÇU D&#x27;OPÉRATION" in html_screen and "EMAB GROUP" in html_screen
    assert receipt.highlight_color in html_screen and receipt.highlight_color not in html_print

    # 5. Réglages persistés : valeurs par défaut puis modification.
    pc = settings_service.get_print_config()
    assert pc == {"printer": "", "paper_width": "80", "auto_print": True, "open_drawer": False}, pc
    settings_service.set_print_config(printer="EPSON TM-T20III Receipt", paper_width="58",
                                      auto_print=False, open_drawer=True)
    pc = settings_service.get_print_config()
    assert pc["printer"] == "EPSON TM-T20III Receipt" and pc["paper_width"] == "58"
    assert pc["auto_print"] is False and pc["open_drawer"] is True
    settings_service.set_print_config(paper_width="A4")  # valeur invalide → 80
    assert settings_service.get_print_config()["paper_width"] == "80"

    print("receipt_printer_test: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
