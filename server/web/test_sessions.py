import uuid
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from sync.models import RemoteUser
from web.middleware import password_version


class SessionRegressionTests(TestCase):
    def setUp(self):
        self.remote = RemoteUser.objects.create(uuid=str(uuid.uuid4()), identifiant="admin-test",
            nom_complet="Test", role="admin", password_hash="old", created_at="now", updated_at="now")
        self.client.force_login(get_user_model().objects.create_user(username="admin-test"))
        session = self.client.session
        session["remote_user"] = {"id": self.remote.pk, "uuid": self.remote.uuid, "role": "admin",
                                  "auth_version": password_version("old")}
        session.save()

    def test_disabled_user_session_is_revoked(self):
        self.remote.actif = False
        self.remote.save()
        self.assertEqual(self.client.get(reverse("web:dashboard")).status_code, 302)

    def test_demoted_user_loses_admin_access_immediately(self):
        self.remote.role = "caissier"
        self.remote.save()
        self.assertEqual(self.client.get(reverse("web:users")).status_code, 403)

    def test_password_change_revokes_existing_session(self):
        self.remote.password_hash = "new"
        self.remote.save()
        self.assertEqual(self.client.get(reverse("web:dashboard")).status_code, 302)


    def test_second_login_does_not_revoke_first_browser_session(self):
        import bcrypt
        from django.test import Client
        self.remote.password_hash = bcrypt.hashpw(b"password", bcrypt.gensalt(rounds=4)).decode()
        self.remote.save()
        first, second = Client(), Client()
        for browser in (first, second):
            self.assertEqual(browser.post(reverse("web:login"), {
                "identifiant": self.remote.identifiant, "password": "password",
            }).status_code, 302)
        self.assertEqual(first.get(reverse("web:dashboard")).status_code, 200)
        self.assertEqual(second.get(reverse("web:dashboard")).status_code, 200)
