"""Réveil immédiat de la boucle de réplication (console web locale).

Permet à une vue web de demander une synchronisation TOUT DE SUITE après une
modification (ex. création d'un client), au lieu d'attendre le prochain cycle
périodique. La boucle de réplication (console_web._replication_loop) attend sur
cet évènement avec un délai maximal égal à l'intervalle configuré ; dès qu'une
vue appelle `request_sync()`, la boucle se réveille et pousse aussitôt les
changements vers le serveur en ligne.

Sûr partout : sur le serveur en ligne (Render), aucune boucle n'attend cet
évènement — `request_sync()` y est donc un simple no-op sans effet.
"""
from __future__ import annotations

import threading

_wakeup = threading.Event()


def request_sync() -> None:
    """Demande une synchronisation immédiate (réveille la boucle de réplication)."""
    _wakeup.set()


def wait_for_sync(timeout: float) -> bool:
    """Attend jusqu'à `timeout` secondes, ou revient immédiatement si une
    synchronisation a été demandée entre-temps.

    Retourne True si réveillé par une demande (sinon False = simple délai écoulé).
    """
    triggered = _wakeup.wait(timeout)
    _wakeup.clear()
    return triggered
