from django.contrib import admin

from sync.models import (
    Device,
    Product,
    RemoteUser,
    Sale,
    StockMovement,
    Transaction,
)


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ("name", "active", "created_at", "last_seen")
    readonly_fields = ("token", "created_at", "last_seen")
    search_fields = ("name",)


@admin.register(RemoteUser)
class RemoteUserAdmin(admin.ModelAdmin):
    list_display = ("identifiant", "nom_complet", "role", "actif", "received_at")
    search_fields = ("identifiant", "nom_complet", "matricule")
    list_filter = ("role", "actif")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("nom", "reference", "prix_unitaire", "quantite_stock", "actif", "received_at")
    search_fields = ("nom", "reference")


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("product_nom", "type", "quantite", "stock_apres", "created_at", "received_at")
    list_filter = ("type",)
    search_fields = ("product_nom",)


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("matricule", "type", "montant", "solde_apres", "agent_nom", "created_at", "deleted")
    list_filter = ("type", "deleted")
    search_fields = ("matricule", "agent_nom")


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ("matricule", "product_nom", "quantite", "montant_total", "agent_nom", "created_at", "deleted")
    list_filter = ("deleted",)
    search_fields = ("matricule", "product_nom", "agent_nom")
