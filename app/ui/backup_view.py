"""Administration : sauvegardes, restauration, vérification, réinitialisation."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.config import BACKUP_DIR, DB_PATH
from app.models.user import User
from app.services import (
    backup_service,
    settings_service,
    sync_service,
    transaction_service,
    user_service,
)
from app.ui.widgets.dialogs import access_denied, confirm, error, info


class BackupView(QWidget):
    def __init__(self, current_user: User, on_data_changed: Optional[Callable] = None) -> None:
        super().__init__()
        self.current_user = current_user
        self.on_data_changed = on_data_changed
        self._build_ui()

    def _build_ui(self) -> None:
        if not self.current_user.is_admin():
            layout = QVBoxLayout(self)
            lbl = QLabel("Accès refusé. Fonction réservée aux administrateurs.")
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("color: #dc2626; font-size: 16px; font-weight: 700;")
            layout.addWidget(lbl)
            return

        # Scroll area : la page Administration est longue (plusieurs cartes)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title = QLabel("Administration de la base")
        title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        layout.addWidget(title)

        # --- System check card ------------------------------------------
        sys_card = QFrame()
        sys_card.setProperty("class", "card")
        sl = QVBoxLayout(sys_card)
        sl.setContentsMargins(16, 12, 16, 12)
        sl.addWidget(self._h2("Vérification système"))
        self.system_info = QTextEdit()
        self.system_info.setReadOnly(True)
        self.system_info.setMaximumHeight(140)
        sl.addWidget(self.system_info)
        check_btn = QPushButton("Lancer la vérification")
        check_btn.setProperty("class", "secondary")
        check_btn.clicked.connect(self._refresh_system_check)
        sl.addWidget(check_btn, alignment=Qt.AlignLeft)
        layout.addWidget(sys_card)

        # --- Backup card ------------------------------------------------
        b_card = QFrame()
        b_card.setProperty("class", "card")
        bl = QVBoxLayout(b_card)
        bl.setContentsMargins(16, 12, 16, 12)
        bl.addWidget(self._h2("Sauvegardes"))

        b_actions = QHBoxLayout()
        create_btn = QPushButton("Créer une sauvegarde maintenant")
        create_btn.setProperty("class", "success")
        create_btn.clicked.connect(self._create_backup)
        restore_btn = QPushButton("Restaurer depuis un fichier")
        restore_btn.setProperty("class", "secondary")
        restore_btn.clicked.connect(self._restore_backup)
        export_btn = QPushButton("Exporter la base (copie)")
        export_btn.setProperty("class", "secondary")
        export_btn.clicked.connect(self._export_db)
        b_actions.addWidget(create_btn)
        b_actions.addWidget(restore_btn)
        b_actions.addWidget(export_btn)
        b_actions.addStretch()
        bl.addLayout(b_actions)

        # --- Sauvegarde planifiée (automatique) ------------------------
        auto_cfg = settings_service.get_auto_backup_config()
        auto_row = QHBoxLayout()
        self.auto_enabled_cb = QCheckBox("Sauvegarde automatique au démarrage")
        self.auto_enabled_cb.setChecked(auto_cfg["enabled"])
        self.auto_interval_spin = QSpinBox()
        self.auto_interval_spin.setRange(1, 365)
        self.auto_interval_spin.setValue(auto_cfg["interval_days"])
        self.auto_interval_spin.setSuffix(" j")
        self.auto_keep_spin = QSpinBox()
        self.auto_keep_spin.setRange(1, 200)
        self.auto_keep_spin.setValue(auto_cfg["keep"])
        save_auto_btn = QPushButton("Enregistrer")
        save_auto_btn.setProperty("class", "secondary")
        save_auto_btn.clicked.connect(self._save_auto_backup)
        auto_row.addWidget(self.auto_enabled_cb)
        auto_row.addWidget(QLabel("Tous les"))
        auto_row.addWidget(self.auto_interval_spin)
        auto_row.addWidget(QLabel("Conserver"))
        auto_row.addWidget(self.auto_keep_spin)
        auto_row.addWidget(save_auto_btn)
        auto_row.addStretch()
        bl.addLayout(auto_row)

        self.auto_status_label = QLabel("")
        self.auto_status_label.setStyleSheet("color: #6b7280;")
        bl.addWidget(self.auto_status_label)

        self.backup_table = QTableWidget(0, 4)
        self.backup_table.setHorizontalHeaderLabels(["Date", "Type", "Taille", "Fichier"])
        self.backup_table.verticalHeader().setVisible(False)
        self.backup_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.backup_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.backup_table.horizontalHeader().setStretchLastSection(True)
        self.backup_table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        bl.addWidget(self.backup_table, 1)
        layout.addWidget(b_card, 1)

        # --- Sync card --------------------------------------------------
        s_card = QFrame()
        s_card.setProperty("class", "card")
        s_card.setStyleSheet(s_card.styleSheet() + "QFrame { border-left: 4px solid #2563eb; }")
        scl = QVBoxLayout(s_card)
        scl.setContentsMargins(16, 12, 16, 12)
        scl.addWidget(self._h2("Synchronisation en ligne (envoi vers le serveur)"))

        cfg = settings_service.get_sync_config()
        form = QFormLayout()
        self.sync_url_edit = QLineEdit(cfg["server_url"])
        self.sync_url_edit.setPlaceholderText("https://votre-app.onrender.com")
        self.sync_token_edit = QLineEdit(cfg["device_token"])
        self.sync_token_edit.setPlaceholderText("Jeton fourni par le serveur (createdevice)")
        self.sync_token_edit.setEchoMode(QLineEdit.Password)
        self.sync_name_edit = QLineEdit(cfg["device_name"])
        self.sync_name_edit.setPlaceholderText("ex : Caisse principale")
        form.addRow("URL du serveur", self.sync_url_edit)
        form.addRow("Jeton du poste", self.sync_token_edit)
        form.addRow("Nom du poste", self.sync_name_edit)
        scl.addLayout(form)

        s_actions = QHBoxLayout()
        save_cfg_btn = QPushButton("Enregistrer la configuration")
        save_cfg_btn.setProperty("class", "secondary")
        save_cfg_btn.clicked.connect(self._save_sync_config)
        test_btn = QPushButton("Tester la connexion")
        test_btn.setProperty("class", "secondary")
        test_btn.clicked.connect(self._test_sync)
        sync_now_btn = QPushButton("Synchroniser maintenant")
        sync_now_btn.setProperty("class", "success")
        sync_now_btn.clicked.connect(self._sync_now)
        s_actions.addWidget(save_cfg_btn)
        s_actions.addWidget(test_btn)
        s_actions.addWidget(sync_now_btn)
        s_actions.addStretch()
        scl.addLayout(s_actions)

        self.sync_status_label = QLabel("")
        self.sync_status_label.setStyleSheet("color: #6b7280;")
        scl.addWidget(self.sync_status_label)

        # --- Sync automatique périodique --------------------------------
        auto_sync_cfg = settings_service.get_auto_sync_config()
        scl.addWidget(self._h2("Synchronisation automatique"))
        auto_row = QHBoxLayout()
        self.auto_sync_cb = QCheckBox("Activer la sync auto (push + pull en arrière-plan)")
        self.auto_sync_cb.setChecked(auto_sync_cfg["enabled"])
        self.auto_sync_interval_spin = QSpinBox()
        self.auto_sync_interval_spin.setRange(15, 3600)
        self.auto_sync_interval_spin.setSingleStep(15)
        self.auto_sync_interval_spin.setSuffix(" s")
        self.auto_sync_interval_spin.setValue(auto_sync_cfg["interval_seconds"])
        save_auto_sync_btn = QPushButton("Enregistrer")
        save_auto_sync_btn.setProperty("class", "secondary")
        save_auto_sync_btn.clicked.connect(self._save_auto_sync)
        auto_row.addWidget(self.auto_sync_cb)
        auto_row.addWidget(QLabel("Toutes les"))
        auto_row.addWidget(self.auto_sync_interval_spin)
        auto_row.addWidget(save_auto_sync_btn)
        auto_row.addStretch()
        scl.addLayout(auto_row)
        info_lbl = QLabel(
            "Recommandé : 30 à 120 s. Les opérations financières (dépôts/retraits/ventes) "
            "saisies localement sont poussées au serveur ; les modifs du catalogue, des "
            "clients, des comptes et les dépôts saisis depuis le web sont rapatriés."
        )
        info_lbl.setStyleSheet("color: #6b7280; font-size: 11px;")
        info_lbl.setWordWrap(True)
        scl.addWidget(info_lbl)

        layout.addWidget(s_card)

        # --- Danger zone ------------------------------------------------
        d_card = QFrame()
        d_card.setProperty("class", "card")
        d_card.setStyleSheet(d_card.styleSheet() + "QFrame { border-left: 4px solid #dc2626; }")
        dl = QVBoxLayout(d_card)
        dl.setContentsMargins(16, 12, 16, 12)
        dl.addWidget(self._h2("Zone sensible"))
        warn = QLabel(
            "Les actions ci-dessous sont irréversibles. Une sauvegarde automatique est créée avant exécution."
        )
        warn.setStyleSheet("color: #6b7280;")
        dl.addWidget(warn)

        d_actions = QHBoxLayout()
        wipe_btn = QPushButton("Réinitialiser les transactions")
        wipe_btn.setProperty("class", "danger")
        wipe_btn.clicked.connect(self._wipe)
        d_actions.addWidget(wipe_btn)
        d_actions.addStretch()
        dl.addLayout(d_actions)
        layout.addWidget(d_card)

        self.refresh()

    def _h2(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setProperty("class", "h2")
        lbl.setFont(QFont("Segoe UI", 13, QFont.Bold))
        return lbl

    # ---------------------------------------------------------------- data
    def refresh(self) -> None:
        if not self.current_user.is_admin():
            return
        self._refresh_system_check()
        self._refresh_backups()
        self._refresh_sync_status()
        self._refresh_auto_status()

    def _refresh_auto_status(self) -> None:
        if not hasattr(self, "auto_status_label"):
            return
        cfg = settings_service.get_auto_backup_config()
        if not cfg["enabled"]:
            self.auto_status_label.setText("Sauvegarde automatique désactivée.")
            return
        last = cfg["last_at"] or "jamais"
        self.auto_status_label.setText(
            f"Active — tous les {cfg['interval_days']} jour(s), "
            f"{cfg['keep']} conservée(s). Dernière : {last}."
        )

    def _save_auto_backup(self) -> None:
        settings_service.set_auto_backup_config(
            enabled=self.auto_enabled_cb.isChecked(),
            interval_days=self.auto_interval_spin.value(),
            keep=self.auto_keep_spin.value(),
        )
        info(self, "Sauvegarde automatique", "Préférences enregistrées.")
        self._refresh_auto_status()

    def _refresh_sync_status(self) -> None:
        if not hasattr(self, "sync_status_label"):
            return
        pending = sync_service.pending_total()
        if settings_service.is_sync_configured():
            self.sync_status_label.setText(
                f"Configuré. En attente d'envoi : {pending} enregistrement(s)."
            )
        else:
            self.sync_status_label.setText(
                f"Non configuré. {pending} enregistrement(s) en attente (envoi désactivé)."
            )

    # ----------------------------------------------------------- sync actions
    def _save_sync_config(self) -> None:
        settings_service.set_sync_config(
            server_url=self.sync_url_edit.text(),
            device_token=self.sync_token_edit.text(),
            device_name=self.sync_name_edit.text(),
        )
        info(self, "Synchronisation", "Configuration enregistrée.")
        self._refresh_sync_status()
        self._reload_auto_sync_if_any()

    def _save_auto_sync(self) -> None:
        settings_service.set_auto_sync_config(
            enabled=self.auto_sync_cb.isChecked(),
            interval_seconds=int(self.auto_sync_interval_spin.value()),
        )
        info(
            self,
            "Synchronisation automatique",
            "Paramètres enregistrés. "
            + ("Sync auto activée." if self.auto_sync_cb.isChecked() else "Sync auto désactivée."),
        )
        self._reload_auto_sync_if_any()

    def _reload_auto_sync_if_any(self) -> None:
        """Notifie le contrôleur de sync auto de relire la configuration."""
        win = self.window()
        controller = getattr(win, "auto_sync", None)
        if controller is not None:
            controller.reload_config()

    def _test_sync(self) -> None:
        try:
            sync_service.test_connection(
                server_url=self.sync_url_edit.text().strip(),
                token=self.sync_token_edit.text().strip(),
            )
        except sync_service.SyncError as e:
            error(self, "Connexion", str(e))
            return
        info(self, "Connexion", "Connexion réussie : le serveur a accepté le jeton.")

    def _sync_now(self) -> None:
        # On s'assure que la config saisie est enregistrée avant l'envoi.
        self._save_sync_config_silent()
        if not settings_service.is_sync_configured():
            error(self, "Synchronisation", "Configurez l'URL du serveur et le jeton du poste.")
            return
        try:
            result = sync_service.sync_all(
                progress=lambda msg: self.sync_status_label.setText(msg)
            )
        except sync_service.SyncError as e:
            error(self, "Synchronisation", str(e))
            self._refresh_sync_status()
            return
        pushed = result.get("pushed", {})
        pulled = result.get("pulled", {})
        total_push = sum(pushed.values()) if pushed else 0
        total_pull_in = sum(
            (t.get("inserted", 0) + t.get("updated", 0)) for t in pulled.values()
        ) if pulled else 0

        push_detail = ", ".join(f"{k}={v}" for k, v in pushed.items() if v) if pushed else ""
        pull_detail_parts = []
        for table, tally in pulled.items():
            ins = tally.get("inserted", 0)
            upd = tally.get("updated", 0)
            if ins or upd:
                pull_detail_parts.append(f"{table}: +{ins} ~{upd}")
        pull_detail = " · ".join(pull_detail_parts)

        msg = (
            f"Envoyé : {total_push} · Reçu : {total_pull_in}"
            + (f"\nPush — {push_detail}" if push_detail else "")
            + (f"\nPull — {pull_detail}" if pull_detail else "")
        )
        info(self, "Synchronisation", msg)
        self._refresh_sync_status()
        if self.on_data_changed:
            self.on_data_changed()

    def _save_sync_config_silent(self) -> None:
        settings_service.set_sync_config(
            server_url=self.sync_url_edit.text(),
            device_token=self.sync_token_edit.text(),
            device_name=self.sync_name_edit.text(),
        )

    def _refresh_system_check(self) -> None:
        nb_users = len(user_service.list_users())
        depots, retraits, nb_tx, nb_matricules = transaction_service.totals()
        solde = transaction_service.get_global_balance()
        sync = transaction_service.sync_status_counts()
        db_size = DB_PATH.stat().st_size if DB_PATH.exists() else 0
        sync_desc = ", ".join(f"{k}={v}" for k, v in sync.items()) if sync else "aucune"
        info_text = (
            f"Base de données : {DB_PATH}\n"
            f"Taille : {db_size / 1024:.1f} Ko\n"
            f"Utilisateurs : {nb_users}\n"
            f"Transactions : {nb_tx} ({nb_matricules} matricules distincts)\n"
            f"Total dépôts : {depots:,.0f}\n"
            f"Total retraits : {retraits:,.0f}\n"
            f"Solde global : {solde:,.0f}\n"
            f"Statut sync : {sync_desc}"
        )
        self.system_info.setPlainText(info_text)

    def _refresh_backups(self) -> None:
        backups = backup_service.list_backups()
        self.backup_table.setRowCount(0)
        for b in backups:
            row = self.backup_table.rowCount()
            self.backup_table.insertRow(row)
            size_kb = (b.get("size_bytes") or 0) / 1024
            cells = [
                b.get("created_at", ""),
                b.get("kind", ""),
                f"{size_kb:.1f} Ko",
                b.get("file_path", ""),
            ]
            for col, val in enumerate(cells):
                self.backup_table.setItem(row, col, QTableWidgetItem(str(val)))

    # ------------------------------------------------------------- actions
    def _create_backup(self) -> None:
        try:
            path = backup_service.create_backup(kind="manual")
        except Exception as e:
            error(self, "Erreur", str(e))
            return
        info(self, "Sauvegarde", f"Sauvegarde créée :\n{path}")
        self._refresh_backups()

    def _restore_backup(self) -> None:
        if not self.current_user.is_super_admin():
            access_denied(self)
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Sélectionner une sauvegarde", str(BACKUP_DIR), "SQLite (*.db)"
        )
        if not path:
            return
        if not confirm(
            self,
            "Restauration",
            "La base actuelle sera remplacée. Une sauvegarde de sécurité sera créée. Continuer ?",
        ):
            return
        try:
            backup_service.restore_backup(Path(path))
        except Exception as e:
            error(self, "Erreur", str(e))
            return
        info(self, "Restauration", "Base restaurée. Veuillez redémarrer l'application.")
        if self.on_data_changed:
            self.on_data_changed()

    def _export_db(self) -> None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default = str(BACKUP_DIR / f"export_{ts}.db")
        path, _ = QFileDialog.getSaveFileName(self, "Exporter la base", default, "SQLite (*.db)")
        if not path:
            return
        try:
            backup_service.create_backup(kind="manual", note="Export manuel")
            import shutil
            shutil.copy2(str(DB_PATH), path)
        except Exception as e:
            error(self, "Erreur", str(e))
            return
        info(self, "Export", f"Copie de la base enregistrée :\n{path}")

    def _wipe(self) -> None:
        if not self.current_user.is_super_admin():
            access_denied(self)
            return
        if not confirm(
            self,
            "Réinitialisation",
            "Toutes les transactions et les journaux seront supprimés.\n"
            "Les utilisateurs sont conservés. Une sauvegarde sera créée. Continuer ?",
        ):
            return
        try:
            backup_service.create_backup(kind="auto", note="Avant réinitialisation")
            backup_service.wipe_data()
        except Exception as e:
            error(self, "Erreur", str(e))
            return
        info(self, "Réinitialisation", "Données supprimées.")
        self.refresh()
        if self.on_data_changed:
            self.on_data_changed()
