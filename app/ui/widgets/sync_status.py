"""Widget de statut de synchronisation (placeholder pour future API)."""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from app.services import settings_service, sync_service, transaction_service


class SyncStatusWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.connection_label = QLabel("● Hors ligne")
        self.connection_label.setObjectName("sync_offline")

        self.pending_label = QLabel("En attente : 0")
        self.pending_label.setObjectName("sync_pending")

        self.synced_label = QLabel("Synchronisés : 0")
        self.synced_label.setObjectName("sync_synced")

        layout.addWidget(self.connection_label)
        layout.addWidget(QLabel(" | "))
        layout.addWidget(self.pending_label)
        layout.addWidget(QLabel(" | "))
        layout.addWidget(self.synced_label)
        layout.addStretch()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(5000)
        self.refresh()

    def refresh(self) -> None:
        try:
            counts = transaction_service.sync_status_counts()
        except Exception:
            counts = {}
        try:
            pending = sync_service.pending_total()
        except Exception:
            pending = counts.get("pending", 0)
        self.pending_label.setText(f"En attente : {pending}")
        self.synced_label.setText(f"Synchronisés : {counts.get('synced', 0)}")
        errors = counts.get("error", 0) + counts.get("conflict", 0)
        if errors > 0:
            self.connection_label.setText(f"● {errors} anomalie(s) sync")
            self.connection_label.setObjectName("sync_error")
        elif settings_service.is_sync_configured():
            self.connection_label.setText("● Synchronisation configurée")
            self.connection_label.setObjectName("sync_synced")
        else:
            self.connection_label.setText("● Hors ligne (local)")
            self.connection_label.setObjectName("sync_offline")
        self.connection_label.style().unpolish(self.connection_label)
        self.connection_label.style().polish(self.connection_label)
