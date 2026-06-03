"""Worker thread Qt pour la synchronisation périodique non bloquante.

Architecture : un QObject (`SyncWorker`) tourne dans un QThread dédié. Le contrôleur
(`AutoSyncController`) déclenche `run()` via un QTimer périodique tant que la sync
auto est activée. Tout le réseau s'exécute hors du thread UI ; les résultats
remontent par signaux (thread-safe via Qt.QueuedConnection).
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from app.services import settings_service, sync_service


class SyncWorker(QObject):
    """Exécute une sync complète (push + pull) sur son thread Qt dédié."""

    finished = Signal(dict)
    failed = Signal(str)
    progress = Signal(str)

    @Slot()
    def run(self) -> None:
        if not settings_service.is_sync_configured():
            self.failed.emit("Synchronisation non configurée.")
            return
        try:
            result = sync_service.sync_all(
                progress=lambda msg: self.progress.emit(msg)
            )
            self.finished.emit(result)
        except sync_service.SyncError as e:
            self.failed.emit(str(e))
        except Exception as e:  # pragma: no cover - garde-fou
            self.failed.emit(f"Erreur inattendue : {e}")


class AutoSyncController(QObject):
    """Pilote la sync automatique : lit la config, planifie, déclenche le worker.

    Émet `tick_started/tick_finished/tick_failed` pour que l'IHM puisse réagir
    (rafraîchir la vue courante, mettre à jour l'indicateur sync).
    """

    tick_started = Signal()
    tick_finished = Signal(dict)
    tick_failed = Signal(str)
    progress = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setSingleShot(False)
        self._timer.timeout.connect(self._on_tick)
        self._busy = False
        self._thread: QThread | None = None
        self._worker: SyncWorker | None = None

    # -- API publique ---------------------------------------------------------

    def reload_config(self) -> None:
        """À appeler quand l'utilisateur change l'intervalle ou l'activation."""
        cfg = settings_service.get_auto_sync_config()
        if cfg["enabled"] and settings_service.is_sync_configured():
            interval_ms = max(15, int(cfg["interval_seconds"])) * 1000
            self._timer.start(interval_ms)
        else:
            self._timer.stop()

    def stop(self) -> None:
        self._timer.stop()
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(2000)
            self._thread = None
            self._worker = None

    def trigger_now(self) -> bool:
        """Force un tick immédiat. Renvoie False si déjà en cours."""
        return self._launch_worker()

    @property
    def is_busy(self) -> bool:
        return self._busy

    # -- Interne --------------------------------------------------------------

    def _on_tick(self) -> None:
        self._launch_worker()

    def _launch_worker(self) -> bool:
        if self._busy:
            return False
        if not settings_service.is_sync_configured():
            return False
        self._busy = True
        self.tick_started.emit()

        self._thread = QThread(self)
        self._worker = SyncWorker()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.progress)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.failed.connect(self._on_worker_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_thread)
        self._thread.start()
        return True

    @Slot(dict)
    def _on_worker_finished(self, result: dict) -> None:
        self._busy = False
        self.tick_finished.emit(result)

    @Slot(str)
    def _on_worker_failed(self, msg: str) -> None:
        self._busy = False
        self.tick_failed.emit(msg)

    @Slot()
    def _cleanup_thread(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None
