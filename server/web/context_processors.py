"""Variables de contexte communes aux templates."""
from __future__ import annotations

import os


def local_console(request):
    """Expose `is_local_console` aux templates.

    Vrai uniquement quand l'app tourne via la console locale (console_web.py
    positionne EMAB_LOCAL_CONSOLE=1). Permet d'afficher le bouton « Quitter »
    seulement en local, jamais sur le serveur en ligne.
    """
    return {"is_local_console": os.environ.get("EMAB_LOCAL_CONSOLE") == "1"}


def pending_stock(request):
    """Expose `pending_stock_count` (entrées de stock à valider) aux admins.

    Sert à afficher un badge dans la navigation. Requête uniquement pour les
    rôles admin (les agents ne voient pas ce menu) et si l'utilisateur est
    connecté, pour ne pas peser sur la page de login.
    """
    r = (getattr(request, "session", None) or {}).get("remote_user") if hasattr(request, "session") else None
    if not r or r.get("role") not in ("super_admin", "admin"):
        return {"pending_stock_count": 0}
    try:
        from sync.models import StockEntryRequest
        count = StockEntryRequest.objects.filter(statut="en_attente").count()
    except Exception:
        count = 0
    return {"pending_stock_count": count}


def pending_update(request):
    """Expose `update_ready` / `update_version` aux templates (console locale).

    Vrai quand une nouvelle version de la console a été téléchargée et attend
    d'être installée : permet d'afficher un bandeau « Appliquer maintenant ».
    Toujours faux sur le serveur en ligne (Render).
    """
    if os.environ.get("EMAB_LOCAL_CONSOLE") != "1":
        return {"update_ready": False, "update_version": ""}
    data_dir = os.environ.get("EMAB_DATA_DIR")
    if not data_dir:
        return {"update_ready": False, "update_version": ""}
    try:
        from pathlib import Path
        from updater import pending_version
        version = pending_version(Path(data_dir))
    except Exception:
        version = None
    return {"update_ready": bool(version), "update_version": version or ""}
