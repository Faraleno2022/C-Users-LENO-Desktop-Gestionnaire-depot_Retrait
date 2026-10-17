"""Test de l'import de `sync_config.json` (fichier de configuration de la sync).

Vérifie que le fichier est lu, appliqué dans app_settings (mêmes clés que
l'écran Administration → Synchronisation), puis renommé pour ne pas être
réimporté ; et que les fichiers invalides sont rejetés proprement.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path


def main() -> int:
    import app.config as cfg
    tmp = Path(tempfile.mkdtemp(prefix="gest_sync_cfg_test_"))
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

    from app.services import settings_service, sync_config_file

    # 1. Aucun fichier → rien ne se passe.
    assert sync_config_file.apply_sync_config_file_if_present([tmp / "absent.json"]) is None
    assert not settings_service.is_sync_configured()

    # 2. Fichier valide → appliqué et renommé.
    path = tmp / "sync_config.json"
    path.write_text(json.dumps({
        "server_url": "https://exemple.onrender.com/",
        "device_token": "abc123",
        "device_name": "Caisse test",
        "auto_sync": False,
        "auto_sync_interval_seconds": 45,
    }), encoding="utf-8")
    applied = sync_config_file.apply_sync_config_file_if_present([path])
    assert applied == path, applied
    assert not path.exists(), "le fichier doit être renommé après import"
    assert (tmp / "sync_config.applied.json").exists()

    sync_cfg = settings_service.get_sync_config()
    assert sync_cfg["server_url"] == "https://exemple.onrender.com", sync_cfg
    assert sync_cfg["device_token"] == "abc123"
    assert sync_cfg["device_name"] == "Caisse test"
    assert settings_service.is_sync_configured()
    auto = settings_service.get_auto_sync_config()
    assert auto["enabled"] is False and auto["interval_seconds"] == 45, auto

    # 3. Synonymes et valeurs texte acceptés ; auto_sync absent → inchangé.
    path.write_text(json.dumps({
        "url": "http://192.168.1.10:8000",
        "jeton": "tok2",
        "poste": "Caisse 2",
    }), encoding="utf-8")
    sync_config_file.apply_sync_config_file_if_present([path])
    sync_cfg = settings_service.get_sync_config()
    assert sync_cfg["server_url"] == "http://192.168.1.10:8000"
    assert sync_cfg["device_token"] == "tok2"
    auto = settings_service.get_auto_sync_config()
    assert auto["enabled"] is False and auto["interval_seconds"] == 45, "ne doit pas changer"

    # 4. Fichiers invalides → erreur explicite, configuration intacte.
    for bad in ("{pas du json", json.dumps({"server_url": "https://x"}),
                json.dumps({"server_url": "ftp://x", "device_token": "t"})):
        path.write_text(bad, encoding="utf-8")
        try:
            sync_config_file.apply_sync_config_file_if_present([path])
        except sync_config_file.SyncConfigFileError:
            pass
        else:
            raise AssertionError(f"fichier invalide accepté : {bad!r}")
        assert path.exists(), "un fichier invalide ne doit pas être renommé"
    assert settings_service.get_sync_config()["device_token"] == "tok2"

    # 5. L'outil cliquable écrit les mêmes clés (mode --apply, sans Tk).
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "configurer_sync", Path(__file__).resolve().parent / "tools" / "configurer_sync.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    tool_db = tmp / "outil.db"
    path.write_text(json.dumps({
        "server_url": "https://outil.example",
        "device_token": "tok3",
        "device_name": "Outil",
        "auto_sync": True,
        "auto_sync_interval_seconds": 5,  # sous le minimum → relevé à 15
    }), encoding="utf-8")
    assert tool.apply_from_file(tool_db, path) == 0
    conn = tool.open_db(tool_db)
    try:
        stored = tool.read_config(conn)
    finally:
        conn.close()
    assert stored["server_url"] == "https://outil.example", stored
    assert stored["device_token"] == "tok3"
    assert stored["auto_sync"] is True and stored["auto_sync_interval_seconds"] == 15, stored
    assert tool.apply_from_file(tool_db, tmp / "inexistant.json") == 2

    print("sync_config_file_test: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
