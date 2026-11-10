def test_health(client):
    response = client.get("/health/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_csrf_failure_is_json_with_reason(db):
    from rest_framework.test import APIClient

    client = APIClient(enforce_csrf_checks=True)
    r = client.post("/api/console/auth/login/", {"username": "a", "password": "b"})
    assert r.status_code == 403
    assert "CSRF verification failed" in r.json()["detail"]
    assert "cookie" in r.json()["detail"].lower()  # the actual reason is surfaced


def test_non_api_csrf_failure_keeps_django_page(db):
    from django.test import Client

    r = Client(enforce_csrf_checks=True).post("/admin/login/", {"username": "a"})
    assert r.status_code == 403 and b"CSRF" in r.content
