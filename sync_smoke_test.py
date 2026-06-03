"""Test fumée de la synchronisation côté poste (HTTP simulé).

Vérifie que sync_service collecte les enregistrements 'pending', construit les
bons lots, et marque les lignes 'synced' après une réponse 200 du serveur —
sans serveur réel (la couche requests est remplacée par un faux).
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _FakeRequests:
    """Capture les appels POST et renvoie toujours 200."""

    class RequestException(Exception):
        pass

    def __init__(self):
        self.posts = []

    def get(self, url, headers=None, timeout=None):
        return _FakeResponse(200, {"ok": True, "device": "fake"})

    def post(self, url, json=None, headers=None, timeout=None):
        self.posts.append({"url": url, "json": json, "headers": headers})
        return _FakeResponse(200, {"created": len(json.get("records", [])), "updated": 0})


def main() -> int:
    import app.config as cfg
    tmp = Path(tempfile.mkdtemp(prefix="gest_sync_test_"))
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

    # Données : admin, caissier, transactions, produit, vente
    user_service.ensure_super_admin()
    auth_service.login("admin", "admin123")
    cais = user_service.create_user("c1", "p", "Caissier Test", "caissier")
    transaction_service.create_transaction("MAT-1", "700", "depot", 5000, cais)
    transaction_service.create_transaction("MAT-1", "700", "retrait", 1000, cais)
    prod = product_service.create_product("Ciment", 2000, quantite_initiale=10)
    sale_service.create_sale("MAT-1", prod.id, 1, cais)

    pending_before = sync_service.pending_total()
    assert pending_before > 0
    print(f"OK pending avant sync : {pending_before}")

    # Config + injection du faux requests
    settings_service.set_sync_config("https://example.test", "tok-123", "Poste 1")
    assert settings_service.is_sync_configured()
    fake = _FakeRequests()
    sync_service.requests = fake  # type: ignore[attr-defined]

    # Test connexion
    assert sync_service.test_connection() is True
    print("OK test_connection (simulé)")

    # Push
    summary = sync_service.push_all()
    print(f"OK push : {summary}")
    assert summary["transactions"] == 2, summary
    assert summary["sales"] == 1, summary
    assert summary["products"] == 1, summary
    assert summary["users"] >= 2, summary  # admin + caissier

    # Vérifie en-têtes d'auth et structure de payload
    assert all(p["headers"]["Authorization"] == "Device tok-123" for p in fake.posts)
    assert all(p["url"].endswith("/api/sync/push/") for p in fake.posts)
    tx_posts = [p for p in fake.posts if p["json"]["table"] == "transactions"]
    assert tx_posts and "uuid" in tx_posts[0]["json"]["records"][0]
    # Les hash de mot de passe ne doivent pas être envoyés
    user_posts = [p for p in fake.posts if p["json"]["table"] == "users"]
    assert all("password_hash" not in r for p in user_posts for r in p["json"]["records"])
    print("OK en-têtes, URL et payload conformes (pas de password_hash)")

    pending_after = sync_service.pending_total()
    assert pending_after == 0, f"reste {pending_after} en attente"
    print("OK toutes les lignes marquées 'synced'")

    # Idempotence : un second push n'envoie plus rien
    fake.posts.clear()
    summary2 = sync_service.push_all()
    assert sum(summary2.values()) == 0 and not fake.posts
    print("OK second push : rien à envoyer")

    print("\nTest sync (poste) OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
