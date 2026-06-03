"""Fenêtre principale avec navigation par menu latéral."""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QAction, QFont, QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.config import APP_NAME, APP_VERSION, ROLE_LABELS
from app.models.user import User
from app.services import auth_service
from app.services.sync_worker import AutoSyncController
from app.ui.dashboard import DashboardView
from app.ui.transactions_view import TransactionsView
from app.ui.history_view import HistoryView
from app.ui.products_view import ProductsView
from app.ui.sales_view import SalesView
from app.ui.clients_view import ClientsView
from app.ui.users_view import UsersView
from app.ui.admins_view import AdminsView
from app.ui.reports_view import ReportsView
from app.ui.backup_view import BackupView
from app.ui.widgets.sync_status import SyncStatusWidget


NAV_ITEMS = [
    ("dashboard", "Tableau de bord", None),
    ("transactions", "Dépôt / Retrait", None),
    ("sales", "Vente produit", None),
    ("products", "Produits & Stock", None),
    ("clients", "Clients", None),
    ("history", "Historique", None),
    ("users", "Utilisateurs", ("admin", "super_admin")),
    ("admins", "Administrateurs", ("super_admin",)),
    ("reports", "Rapports", None),
    ("backup", "Administration", ("admin", "super_admin")),
]


SIDEBAR_WIDTH = 220
SIDEBAR_COLLAPSE_THRESHOLD = 900  # En dessous, on replie la barre latérale automatiquement


class MainWindow(QMainWindow):
    def __init__(self, user: User) -> None:
        super().__init__()
        self.user = user
        self.setWindowTitle(f"{APP_NAME} — v{APP_VERSION}")
        # Tailles min/initiales : la fenêtre peut descendre jusqu'à 720x520
        self.setMinimumSize(720, 520)
        self.resize(1280, 800)
        self._sidebar_user_visible = True  # état souhaité par l'utilisateur (toggle)
        self._sidebar_auto_collapsed = False
        self._build_ui()

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("central")
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- Sidebar -----------------------------------------------------
        self.sidebar = QWidget()
        self.sidebar.setFixedWidth(SIDEBAR_WIDTH)
        self.sidebar.setStyleSheet("background: #111827;")
        sb_layout = QVBoxLayout(self.sidebar)
        sb_layout.setContentsMargins(0, 0, 0, 0)
        sb_layout.setSpacing(0)

        header = QLabel(APP_NAME)
        header.setStyleSheet(
            "color: white; padding: 18px 16px; font-weight: 700; font-size: 14px;"
            " background: #0b1220; border-bottom: 1px solid #1f2937;"
        )
        header.setWordWrap(True)
        sb_layout.addWidget(header)

        self.nav = QListWidget()
        self.nav.setFocusPolicy(Qt.NoFocus)
        sb_layout.addWidget(self.nav, 1)

        user_box = QLabel(
            f"<div style='color:#9ca3af;font-size:11px;'>Connecté en tant que</div>"
            f"<div style='color:white;font-weight:600;'>{self.user.nom_complet}</div>"
            f"<div style='color:#60a5fa;font-size:11px;'>{ROLE_LABELS.get(self.user.role, self.user.role)}</div>"
        )
        user_box.setStyleSheet("padding: 14px 16px; background: #0b1220;")
        user_box.setTextFormat(Qt.RichText)
        sb_layout.addWidget(user_box)

        root.addWidget(self.sidebar)

        # --- Stack of views ---------------------------------------------
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        top_bar = QWidget()
        top_bar.setStyleSheet("background: white; border-bottom: 1px solid #e5e7eb;")
        tb_layout = QHBoxLayout(top_bar)
        tb_layout.setContentsMargins(12, 8, 16, 8)

        # Bouton hamburger pour replier/déplier la barre latérale
        self.toggle_sidebar_btn = QToolButton()
        self.toggle_sidebar_btn.setText("☰")  # ≡
        self.toggle_sidebar_btn.setToolTip("Afficher / masquer le menu")
        self.toggle_sidebar_btn.setAutoRaise(True)
        self.toggle_sidebar_btn.setStyleSheet(
            "QToolButton { font-size: 18px; padding: 4px 10px; border: none; color: #1f2937; }"
            "QToolButton:hover { background: #f3f4f6; border-radius: 6px; }"
        )
        self.toggle_sidebar_btn.clicked.connect(self._toggle_sidebar)
        tb_layout.addWidget(self.toggle_sidebar_btn)

        self.page_title = QLabel("Tableau de bord")
        self.page_title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        tb_layout.addWidget(self.page_title)
        tb_layout.addStretch()
        self.sync_widget = SyncStatusWidget()
        tb_layout.addWidget(self.sync_widget)
        right_layout.addWidget(top_bar)

        self.stack = QStackedWidget()
        right_layout.addWidget(self.stack, 1)

        root.addWidget(right, 1)
        self.setCentralWidget(central)

        # --- Views ------------------------------------------------------
        self.views = {}
        self.dashboard = DashboardView()
        self.views["dashboard"] = self.dashboard
        self.views["transactions"] = TransactionsView(self.user, on_changed=self._on_data_changed)
        self.views["sales"] = SalesView(self.user, on_changed=self._on_data_changed)
        self.views["products"] = ProductsView(self.user, on_changed=self._on_data_changed)
        self.views["clients"] = ClientsView(self.user, on_changed=self._on_data_changed)
        self.views["history"] = HistoryView(self.user)
        self.views["users"] = UsersView(self.user)
        self.views["admins"] = AdminsView(self.user)
        self.views["reports"] = ReportsView(self.user)
        self.views["backup"] = BackupView(self.user, on_data_changed=self._on_data_changed)

        # --- Build nav based on role -----------------------------------
        self.nav_keys: list = []
        for key, label, roles in NAV_ITEMS:
            if roles is not None and self.user.role not in roles:
                continue
            item = QListWidgetItem(label)
            self.nav.addItem(item)
            self.stack.addWidget(self.views[key])
            self.nav_keys.append(key)

        # Logout entry
        logout_item = QListWidgetItem("Se déconnecter")
        self.nav.addItem(logout_item)
        self.nav_keys.append("__logout__")

        self.nav.currentRowChanged.connect(self._on_nav_changed)
        self.nav.setCurrentRow(0)

        # Status bar
        sb = QStatusBar()
        sb.showMessage(f"Bienvenue {self.user.nom_complet}")
        self.setStatusBar(sb)

        # --- Sync auto (push+pull périodique) ----------------------------
        self.auto_sync = AutoSyncController(self)
        self.auto_sync.tick_started.connect(self._on_auto_sync_started)
        self.auto_sync.tick_finished.connect(self._on_auto_sync_finished)
        self.auto_sync.tick_failed.connect(self._on_auto_sync_failed)
        self.auto_sync.progress.connect(
            lambda msg: self.statusBar().showMessage(f"Sync : {msg}", 4000)
        )
        # On lance la lecture de la config peu après le démarrage (laisser le temps
        # à init_database / settings de s'établir).
        QTimer.singleShot(1500, self.auto_sync.reload_config)

    def _on_nav_changed(self, row: int) -> None:
        if row < 0 or row >= len(self.nav_keys):
            return
        key = self.nav_keys[row]
        if key == "__logout__":
            self._logout()
            return
        view = self.views.get(key)
        if view is None:
            return
        idx = self.stack.indexOf(view)
        if idx >= 0:
            self.stack.setCurrentIndex(idx)
        self.page_title.setText(self.nav.currentItem().text())
        if hasattr(view, "refresh"):
            try:
                view.refresh()
            except Exception as e:
                QMessageBox.warning(self, "Erreur", f"Erreur lors du rafraîchissement : {e}")

    # ------------------------------------------------------------- auto-sync
    def _on_auto_sync_started(self) -> None:
        self.statusBar().showMessage("Synchronisation automatique en cours…", 2000)

    def _on_auto_sync_finished(self, result: dict) -> None:
        pushed = result.get("pushed", {}) or {}
        pulled = result.get("pulled", {}) or {}
        total_push = sum(pushed.values()) if pushed else 0
        total_pull_in = sum(
            (t.get("inserted", 0) + t.get("updated", 0)) for t in pulled.values()
        ) if pulled else 0
        if total_push or total_pull_in:
            self.statusBar().showMessage(
                f"Sync : envoyé {total_push} · reçu {total_pull_in}", 5000
            )
            # Rafraîchit la vue courante pour refléter les nouveautés.
            current = self.stack.currentWidget()
            if hasattr(current, "refresh"):
                try:
                    current.refresh()
                except Exception:
                    pass
        else:
            self.statusBar().showMessage("Sync à jour", 2000)
        self.sync_widget.refresh()

    def _on_auto_sync_failed(self, msg: str) -> None:
        # On reste silencieux pour ne pas spammer l'utilisateur ; on logge dans la status bar.
        self.statusBar().showMessage(f"Sync échouée : {msg}", 6000)

    def closeEvent(self, event) -> None:
        try:
            self.auto_sync.stop()
        except Exception:
            pass
        super().closeEvent(event)

    def _on_data_changed(self) -> None:
        """Appelé quand les données changent — rafraîchit la vue active."""
        current = self.stack.currentWidget()
        if hasattr(current, "refresh"):
            try:
                current.refresh()
            except Exception:
                pass
        self.sync_widget.refresh()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_responsive_layout()

    def _apply_responsive_layout(self) -> None:
        """Replie automatiquement la barre latérale sur fenêtre étroite."""
        width = self.width()
        if width < SIDEBAR_COLLAPSE_THRESHOLD:
            if self.sidebar.isVisible() and not self._sidebar_auto_collapsed:
                self.sidebar.setVisible(False)
                self._sidebar_auto_collapsed = True
        else:
            # On ne réaffiche automatiquement que si c'est nous qui avions replié
            if self._sidebar_auto_collapsed and self._sidebar_user_visible:
                self.sidebar.setVisible(True)
                self._sidebar_auto_collapsed = False

    def _toggle_sidebar(self) -> None:
        visible = not self.sidebar.isVisible()
        self.sidebar.setVisible(visible)
        self._sidebar_user_visible = visible
        # L'utilisateur reprend la main : on désactive l'auto-collapse tant qu'il ne redimensionne pas
        self._sidebar_auto_collapsed = False

    def _logout(self) -> None:
        from app.ui.widgets.dialogs import confirm

        if not confirm(self, "Déconnexion", "Voulez-vous vraiment vous déconnecter ?"):
            # On ré-affiche la page précédente
            for i, key in enumerate(self.nav_keys):
                if key == "dashboard":
                    self.nav.setCurrentRow(i)
                    break
            return
        auth_service.logout()
        self.close()
