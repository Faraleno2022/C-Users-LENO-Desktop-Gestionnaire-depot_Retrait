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
