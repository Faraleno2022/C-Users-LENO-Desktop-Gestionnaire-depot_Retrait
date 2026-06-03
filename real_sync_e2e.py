"""Round-trip réel : pousse des données vers un serveur Django en cours d'exécution.

Usage : python real_sync_e2e.py <server_url> <device_token>
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: python real_sync_e2e.py <server_url> <device_token>")
        return 2
    server_url, token = sys.argv[1], sys.argv[2]

    import app.config as cfg
    tmp = Path(tempfile.mkdtemp(prefix="gest_e2e_"))
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

    from app.services import (
        auth_service, product_service, sale_service, settings_service,
        sync_service, transaction_service, user_service,
    )

    user_service.ensure_super_admin()
    auth_service.login("admin", "admin123")
    cais = user_service.create_user("c1", "p", "Caissier E2E", "caissier")
    transaction_service.create_transaction("MAT-1", "700", "depot", 5000, cais)
    transaction_service.create_transaction("MAT-1", "700", "retrait", 1000, cais)
    prod = product_service.create_product("Ciment E2E", 2000, quantite_initiale=10)
    sale_service.create_sale("MAT-1", prod.id, 2, cais)

    settings_service.set_sync_config(server_url, token, "Poste E2E")

    # Attendre que le serveur réponde (démarrage)
    for attempt in range(20):
        try:
            sync_service.test_connection()
            print(f"OK connexion au serveur ({server_url})")
            break
        except sync_service.SyncError as e:
            if attempt == 19:
                print(f"ECHEC connexion : {e}")
                return 1
            time.sleep(0.5)

    pending = sync_service.pending_total()
    print(f"Pending avant push : {pending}")
    summary = sync_service.push_all()
    print(f"Push : {summary}")
    after = sync_service.pending_total()
    assert after == 0, f"reste {after} en attente"
    print("OK toutes les lignes synchronisées (pending=0)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
