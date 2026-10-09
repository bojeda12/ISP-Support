from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework.test import APIClient


class HealthTests(SimpleTestCase):
    def test_health_returns_ok_without_authentication_or_database(self):
        response = APIClient().get(reverse("api:health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(response.json(), {"status": "ok"})

    def test_health_rejects_post(self):
        self.assertEqual(APIClient().post(reverse("api:health")).status_code, 405)
