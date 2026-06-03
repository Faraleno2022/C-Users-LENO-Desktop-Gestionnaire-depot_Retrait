"""Schéma SQL de la base locale."""

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uuid TEXT NOT NULL UNIQUE,
        identifiant TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        nom_complet TEXT NOT NULL,
        matricule TEXT,
        telephone TEXT,
        role TEXT NOT NULL CHECK (role IN ('super_admin','admin','superviseur','caissier')),
        actif INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        sync_status TEXT NOT NULL DEFAULT 'pending',
        last_synced_at TEXT
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);",
    "CREATE INDEX IF NOT EXISTS idx_users_matricule ON users(matricule);",
    """
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uuid TEXT NOT NULL UNIQUE,
        matricule TEXT NOT NULL,
        telephone TEXT,
        type TEXT NOT NULL CHECK (type IN ('depot','retrait')),
        montant REAL NOT NULL CHECK (montant > 0),
        solde_apres REAL NOT NULL,
        agent_id INTEGER NOT NULL,
        agent_uuid TEXT,
        agent_nom TEXT NOT NULL,
        note TEXT,
        created_at TEXT NOT NULL,
        sync_status TEXT NOT NULL DEFAULT 'pending',
        last_synced_at TEXT,
        deleted INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (agent_id) REFERENCES users(id)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_tx_matricule ON transactions(matricule);",
    "CREATE INDEX IF NOT EXISTS idx_tx_created_at ON transactions(created_at);",
    "CREATE INDEX IF NOT EXISTS idx_tx_type ON transactions(type);",
    "CREATE INDEX IF NOT EXISTS idx_tx_sync ON transactions(sync_status);",
    "CREATE INDEX IF NOT EXISTS idx_tx_agent ON transactions(agent_id);",
    """
    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uuid TEXT UNIQUE,
        user_id INTEGER,
        user_uuid TEXT,
        user_identifiant TEXT,
        action TEXT NOT NULL,
        target_type TEXT,
        target_id TEXT,
        details TEXT,
        created_at TEXT NOT NULL,
        sync_status TEXT NOT NULL DEFAULT 'pending',
        last_synced_at TEXT
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs(user_id);",
    "CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at);",
    """
    CREATE TABLE IF NOT EXISTS backups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_path TEXT NOT NULL,
        size_bytes INTEGER NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('auto','manual')),
        created_at TEXT NOT NULL,
        note TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uuid TEXT NOT NULL UNIQUE,
        reference TEXT,
        nom TEXT NOT NULL,
        description TEXT,
        prix_unitaire REAL NOT NULL CHECK (prix_unitaire >= 0),
        quantite_stock REAL NOT NULL DEFAULT 0,
        seuil_alerte REAL NOT NULL DEFAULT 0,
        actif INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        sync_status TEXT NOT NULL DEFAULT 'pending',
        last_synced_at TEXT
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_products_nom ON products(nom);",
    "CREATE INDEX IF NOT EXISTS idx_products_ref ON products(reference);",
    """
    CREATE TABLE IF NOT EXISTS stock_movements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uuid TEXT NOT NULL UNIQUE,
        product_id INTEGER NOT NULL,
        product_uuid TEXT,
        product_nom TEXT NOT NULL,
        type TEXT NOT NULL CHECK (type IN ('entree','sortie')),
        quantite REAL NOT NULL CHECK (quantite > 0),
        stock_apres REAL NOT NULL,
        motif TEXT,
        sale_id INTEGER,
        agent_id INTEGER NOT NULL,
        agent_uuid TEXT,
        agent_nom TEXT NOT NULL,
        created_at TEXT NOT NULL,
        sync_status TEXT NOT NULL DEFAULT 'pending',
        last_synced_at TEXT,
        FOREIGN KEY (product_id) REFERENCES products(id),
        FOREIGN KEY (agent_id) REFERENCES users(id)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_stock_product ON stock_movements(product_id);",
    "CREATE INDEX IF NOT EXISTS idx_stock_created ON stock_movements(created_at);",
    """
    CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uuid TEXT NOT NULL UNIQUE,
        matricule TEXT NOT NULL,
        telephone TEXT,
        product_id INTEGER NOT NULL,
        product_uuid TEXT,
        product_nom TEXT NOT NULL,
        quantite REAL NOT NULL CHECK (quantite > 0),
        prix_unitaire REAL NOT NULL,
        montant_total REAL NOT NULL,
        solde_apres REAL NOT NULL,
        agent_id INTEGER NOT NULL,
        agent_uuid TEXT,
        agent_nom TEXT NOT NULL,
        note TEXT,
        created_at TEXT NOT NULL,
        sync_status TEXT NOT NULL DEFAULT 'pending',
        last_synced_at TEXT,
        deleted INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (product_id) REFERENCES products(id),
        FOREIGN KEY (agent_id) REFERENCES users(id)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_sales_matricule ON sales(matricule);",
    "CREATE INDEX IF NOT EXISTS idx_sales_created ON sales(created_at);",
    "CREATE INDEX IF NOT EXISTS idx_sales_product ON sales(product_id);",
    """
    CREATE TABLE IF NOT EXISTS clients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uuid TEXT NOT NULL UNIQUE,
        matricule TEXT NOT NULL UNIQUE,
        nom TEXT,
        telephone TEXT,
        note TEXT,
        actif INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        sync_status TEXT NOT NULL DEFAULT 'pending',
        last_synced_at TEXT
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_clients_matricule ON clients(matricule);",
    "CREATE INDEX IF NOT EXISTS idx_clients_nom ON clients(nom);",
    "CREATE INDEX IF NOT EXISTS idx_clients_sync ON clients(sync_status);",
]
