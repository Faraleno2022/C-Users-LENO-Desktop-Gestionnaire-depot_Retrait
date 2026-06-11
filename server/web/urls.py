from django.urls import path

from web import views

app_name = "web"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("", views.dashboard, name="dashboard"),
    path("transactions/", views.transactions, name="transactions"),
    path("transactions/<int:pk>/supprimer/", views.transaction_delete, name="transaction_delete"),
    path("transactions/<int:pk>/restaurer/", views.transaction_restore, name="transaction_restore"),
    path("ventes/<int:pk>/supprimer/", views.sale_delete, name="sale_delete"),
    path("ventes/<int:pk>/restaurer/", views.sale_restore, name="sale_restore"),
    path("corbeille/", views.trash, name="trash"),
    path("transactions/depot/", views.deposit_new, name="deposit_new"),
    path("transactions/retrait/", views.withdrawal_new, name="withdrawal_new"),
    path("transactions/retrait/facture/", views.withdrawal_invoice, name="withdrawal_invoice"),
    path("api/solde/", views.matricule_balance_api, name="matricule_balance_api"),
    path("ventes/nouvelle/", views.sale_new, name="sale_new"),
    path("ventes/", views.sales, name="sales"),
    path("produits/", views.products, name="products"),
    path("produits/nouveau/", views.product_new, name="product_new"),
    path("produits/<int:pk>/modifier/", views.product_edit, name="product_edit"),
    path("produits/<int:pk>/basculer/", views.product_toggle, name="product_toggle"),
    path("produits/<int:pk>/stock/", views.stock_adjust, name="stock_adjust"),
    path("inventaire/", views.inventory, name="inventory"),
    path("mouvements/", views.stock_movements, name="stock_movements"),
    path("clients/", views.clients, name="clients"),
    path("clients/nouveau/", views.client_new, name="client_new"),
    path("clients/<int:pk>/modifier/", views.client_edit, name="client_edit"),
    path("clients/<int:pk>/basculer/", views.client_toggle, name="client_toggle"),
    path("utilisateurs/", views.users_list, name="users"),
    path("utilisateurs/nouveau/", views.user_new, name="user_new"),
    path("utilisateurs/<int:pk>/modifier/", views.user_edit, name="user_edit"),
    path("utilisateurs/<int:pk>/basculer/", views.user_toggle, name="user_toggle"),
    path("journal/", views.audit_journal, name="journal"),
    path("rapports/", views.reports_view, name="reports"),
]
