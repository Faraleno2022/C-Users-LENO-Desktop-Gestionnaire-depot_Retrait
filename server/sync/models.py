"""Modèles miroir des données poussées par les postes (push-only).

Chaque enregistrement est identifié par son `uuid` (unique) afin que les envois
répétés soient idempotents (upsert par uuid). On conserve aussi le poste source
et l'horodatage de réception côté serveur.
"""
from __future__ import annotations

import secrets

from django.db import models
from django.utils import timezone


def generate_token() -> str:
    return secrets.token_hex(24)


class Device(models.Model):
    """Un poste local autorisé à pousser des données."""

    name = models.CharField(max_length=120, unique=True)
    token = models.CharField(max_length=64, unique=True, default=generate_token, db_index=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    last_seen = models.DateTimeField(null=True, blank=True)

    def touch(self) -> None:
        self.last_seen = timezone.now()
        self.save(update_fields=["last_seen"])

    def __str__(self) -> str:
        return self.name


class SyncedModel(models.Model):
    """Base commune des enregistrements synchronisés.

    `received_at` est mis à jour à chaque save (auto_now) : il sert de filigrane
    aux postes pour le pull (récupérer les enregistrements modifiés côté serveur,
    qu'ils proviennent d'un push d'un autre poste ou d'une édition web).
    """

    uuid = models.CharField(max_length=36, unique=True, db_index=True)
    device = models.ForeignKey(Device, on_delete=models.SET_NULL, null=True, blank=True)
    received_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        abstract = True


class RemoteUser(SyncedModel):
    identifiant = models.CharField(max_length=120, db_index=True)
    nom_complet = models.CharField(max_length=200)
    matricule = models.CharField(max_length=60, blank=True, default="")
    telephone = models.CharField(max_length=40, blank=True, default="")
    role = models.CharField(max_length=20)
    actif = models.BooleanField(default=True)
    # Hash bcrypt envoyé par le poste pour permettre l'authentification web avec les
    # mêmes identifiants que sur le bureau. Optionnel : un poste peut ne pas le pousser.
    password_hash = models.CharField(max_length=255, blank=True, default="")
    # Permission propre à la console web (NON synchronisée depuis le poste) :
    # autorise la suppression d'opérations. Les super_admin / admin l'ont d'office ;
    # un admin peut l'accorder à un superviseur/caissier pour en faire un « responsable ».
    can_delete = models.BooleanField(default=False)
    created_at = models.CharField(max_length=32)
    updated_at = models.CharField(max_length=32)

    class Meta:
        verbose_name = "Utilisateur distant"
        verbose_name_plural = "Utilisateurs distants"

    def __str__(self) -> str:
        return f"{self.identifiant} ({self.nom_complet})"


class Product(SyncedModel):
    reference = models.CharField(max_length=80, blank=True, default="")
    nom = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    prix_unitaire = models.FloatField(default=0)
    quantite_stock = models.FloatField(default=0)
    seuil_alerte = models.FloatField(default=0)
    categorie = models.CharField(max_length=120, blank=True, default="")
    unite = models.CharField(max_length=40, blank=True, default="")
    prix_achat = models.FloatField(default=0)
    stock_max = models.FloatField(default=0)
    emplacement = models.CharField(max_length=120, blank=True, default="")
    actif = models.BooleanField(default=True)
    created_at = models.CharField(max_length=32)
    updated_at = models.CharField(max_length=32)

    class Meta:
        verbose_name = "Produit"

    def __str__(self) -> str:
        return self.nom


class StockMovement(SyncedModel):
    product_id = models.IntegerField()
    product_uuid = models.CharField(max_length=36, blank=True, default="", db_index=True)
    product_nom = models.CharField(max_length=200)
    type = models.CharField(max_length=10)
    quantite = models.FloatField()
    stock_apres = models.FloatField()
    motif = models.CharField(max_length=255, blank=True, default="")
    sale_id = models.IntegerField(null=True, blank=True)
    agent_id = models.IntegerField(null=True, blank=True)
    agent_uuid = models.CharField(max_length=36, blank=True, default="")
    agent_nom = models.CharField(max_length=200, blank=True, default="")
    created_at = models.CharField(max_length=32)
    deleted = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Mouvement de stock"

    def __str__(self) -> str:
        return f"{self.type} {self.quantite} — {self.product_nom}"


class Transaction(SyncedModel):
    matricule = models.CharField(max_length=80, db_index=True)
    telephone = models.CharField(max_length=40, blank=True, default="")
    type = models.CharField(max_length=10)
    montant = models.FloatField()
    solde_apres = models.FloatField()
    agent_id = models.IntegerField(null=True, blank=True)
    agent_uuid = models.CharField(max_length=36, blank=True, default="")
    agent_nom = models.CharField(max_length=200, blank=True, default="")
    note = models.CharField(max_length=255, blank=True, default="")
    created_at = models.CharField(max_length=32)
    deleted = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Transaction"

    def __str__(self) -> str:
        return f"{self.type} {self.montant} — {self.matricule}"


class Sale(SyncedModel):
    matricule = models.CharField(max_length=80, db_index=True)
    telephone = models.CharField(max_length=40, blank=True, default="")
    product_id = models.IntegerField()
    product_uuid = models.CharField(max_length=36, blank=True, default="", db_index=True)
    product_nom = models.CharField(max_length=200)
    quantite = models.FloatField()
    prix_unitaire = models.FloatField()
    montant_total = models.FloatField()
    solde_apres = models.FloatField()
    agent_id = models.IntegerField(null=True, blank=True)
    agent_uuid = models.CharField(max_length=36, blank=True, default="")
    agent_nom = models.CharField(max_length=200, blank=True, default="")
    note = models.CharField(max_length=255, blank=True, default="")
    created_at = models.CharField(max_length=32)
    deleted = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Vente"

    def __str__(self) -> str:
        return f"{self.product_nom} x{self.quantite} — {self.matricule}"


class AuditLog(SyncedModel):
    """Journal d'audit synchronisé poste ↔ serveur.

    Identique au schéma local : user_id local (best-effort), user_uuid canonique,
    user_identifiant pour affichage, action, target_type/id, details, created_at.
    """

    user_id = models.IntegerField(null=True, blank=True)
    user_uuid = models.CharField(max_length=36, blank=True, default="", db_index=True)
    user_identifiant = models.CharField(max_length=120, blank=True, default="")
    action = models.CharField(max_length=80, db_index=True)
    target_type = models.CharField(max_length=80, blank=True, default="")
    target_id = models.CharField(max_length=80, blank=True, default="")
    details = models.TextField(blank=True, default="")
    created_at = models.CharField(max_length=32, db_index=True)

    class Meta:
        verbose_name = "Entrée d'audit"
        verbose_name_plural = "Entrées d'audit"

    def __str__(self) -> str:
        return f"[{self.created_at}] {self.user_identifiant} : {self.action}"


class Client(SyncedModel):
    matricule = models.CharField(max_length=80, db_index=True)
    nom = models.CharField(max_length=200, blank=True, default="")
    telephone = models.CharField(max_length=40, blank=True, default="")
    note = models.CharField(max_length=255, blank=True, default="")
    actif = models.BooleanField(default=True)
    created_at = models.CharField(max_length=32)
    updated_at = models.CharField(max_length=32)

    class Meta:
        verbose_name = "Client"

    def __str__(self) -> str:
        return f"{self.matricule} ({self.nom})" if self.nom else self.matricule


class StockEntryRequest(SyncedModel):
    """Demande d'entrée de stock / de création de produit saisie par un agent,
    à valider par un admin.

    SYNCHRONISÉ (comme les autres tables) : la demande se réplique vers le
    serveur en ligne et les autres postes, afin qu'un administrateur — sur
    n'importe quelle machine ou sur le site en ligne — voie la demande de
    l'agent et puisse la valider. On n'utilise donc PAS de clé étrangère (les
    identifiants diffèrent d'une base à l'autre) mais `product_uuid`, et les
    dates sont stockées en texte ISO (sérialisables pour la sync).

    Tant que `statut = en_attente`, la demande n'affecte pas le stock réel. À la
    validation, un StockMovement (et, pour un nouveau produit, un Product) est
    créé ; ceux-là se répliquent normalement. Une demande rejetée ne modifie
    jamais le stock.
    """

    STATUT_CHOICES = [
        ("en_attente", "En attente"),
        ("valide", "Validée"),
        ("rejete", "Rejetée"),
    ]

    KIND_CHOICES = [
        ("entree", "Entrée sur produit existant"),
        ("nouveau_produit", "Création d'un nouveau produit"),
    ]

    # Type de demande : entrée sur un produit existant, ou création d'un
    # nouveau produit (dans ce cas product_uuid est vide tant que non validé).
    kind = models.CharField(
        max_length=16, choices=KIND_CHOICES, default="entree", db_index=True
    )
    # Produit concerné (entrée) référencé par son uuid — pas de FK, pour rester
    # synchronisable entre bases dont les identifiants numériques diffèrent.
    product_uuid = models.CharField(max_length=36, blank=True, default="", db_index=True)
    # Instantané du nom au moment de la demande (robustesse d'affichage).
    product_nom = models.CharField(max_length=200)
    quantite = models.FloatField()
    motif = models.CharField(max_length=255, blank=True, default="")
    # Caractéristiques du NOUVEAU produit proposé (kind="nouveau_produit").
    # Ignorées pour une entrée sur produit existant.
    new_reference = models.CharField(max_length=80, blank=True, default="")
    new_prix_unitaire = models.FloatField(default=0)
    new_seuil_alerte = models.FloatField(default=0)
    new_description = models.TextField(blank=True, default="")
    statut = models.CharField(
        max_length=12, choices=STATUT_CHOICES, default="en_attente", db_index=True
    )
    # Agent demandeur
    requested_by_identifiant = models.CharField(max_length=120, blank=True, default="")
    requested_by_nom = models.CharField(max_length=200, blank=True, default="")
    requested_by_uuid = models.CharField(max_length=36, blank=True, default="")
    created_at = models.CharField(max_length=32)
    # Décision admin
    validated_by_identifiant = models.CharField(max_length=120, blank=True, default="")
    validated_by_nom = models.CharField(max_length=200, blank=True, default="")
    validated_at = models.CharField(max_length=32, blank=True, default="")
    decision_motif = models.CharField(max_length=255, blank=True, default="")
    # uuid du StockMovement créé à la validation (traçabilité).
    resulting_movement_uuid = models.CharField(max_length=36, blank=True, default="")

    class Meta:
        verbose_name = "Demande d'entrée de stock"
        verbose_name_plural = "Demandes d'entrée de stock"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.product_nom} +{self.quantite:g} [{self.statut}]"


# Correspondance nom de table (poste) -> modèle serveur + champs acceptés.
TABLE_MODELS = {
    "users": (RemoteUser, [
        "identifiant", "nom_complet", "matricule", "telephone", "role", "actif",
        "password_hash", "created_at", "updated_at",
    ]),
    "products": (Product, [
        "reference", "nom", "description", "prix_unitaire", "quantite_stock",
        "seuil_alerte", "categorie", "unite", "prix_achat", "stock_max",
        "emplacement", "actif", "created_at", "updated_at",
    ]),
    "stock_movements": (StockMovement, [
        "product_id", "product_uuid", "product_nom", "type", "quantite",
        "stock_apres", "motif", "sale_id", "agent_id", "agent_uuid",
        "agent_nom", "created_at", "deleted",
    ]),
    "transactions": (Transaction, [
        "matricule", "telephone", "type", "montant", "solde_apres", "agent_id",
        "agent_uuid", "agent_nom", "note", "created_at", "deleted",
    ]),
    "sales": (Sale, [
        "matricule", "telephone", "product_id", "product_uuid", "product_nom",
        "quantite", "prix_unitaire", "montant_total", "solde_apres",
        "agent_id", "agent_uuid", "agent_nom", "note", "created_at", "deleted",
    ]),
    "clients": (Client, [
        "matricule", "nom", "telephone", "note", "actif", "created_at", "updated_at",
    ]),
    "audit_logs": (AuditLog, [
        "user_id", "user_uuid", "user_identifiant", "action", "target_type",
        "target_id", "details", "created_at",
    ]),
    "stock_entry_requests": (StockEntryRequest, [
        "kind", "product_uuid", "product_nom", "quantite", "motif",
        "new_reference", "new_prix_unitaire", "new_seuil_alerte", "new_description",
        "statut", "requested_by_identifiant", "requested_by_nom", "requested_by_uuid",
        "created_at", "validated_by_identifiant", "validated_by_nom", "validated_at",
        "decision_motif", "resulting_movement_uuid",
    ]),
}
