from django.db import migrations, models


def repair(apps, schema_editor):
    """Débloque la réplication des comptages d'inventaire sans écart.

    Un inventaire dont le comptage confirme le stock théorique produit un
    mouvement de quantité nulle. L'API d'envoi n'accepte une quantité nulle que
    si la quantité comptée (`stock_compte`) est renseignée ; les consoles
    antérieures ne la posaient pas. Le serveur refusait alors le lot entier, le
    curseur d'envoi n'avançait plus et TOUTE la réplication restait bloquée sur
    ces quelques lignes.

    La quantité comptée d'un mouvement sans écart est, par définition, le stock
    après mouvement : on la renseigne, ce qui rend la ligne acceptable sans rien
    inventer.
    """
    StockMovement = apps.get_model("sync", "StockMovement")
    StockMovement.objects.filter(quantite=0, stock_compte__isnull=True).update(
        stock_compte=models.F("stock_apres")
    )


class Migration(migrations.Migration):

    dependencies = [
        ("sync", "0018_product_suivi_stock"),
    ]

    operations = [
        # Réparation de données seule : rien à annuler côté schéma.
        migrations.RunPython(repair, migrations.RunPython.noop),
    ]
