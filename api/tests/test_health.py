from app.main import app


def test_health_says_ok(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_unexpected_errors_hide_internal_details(client):
    def crash():
        raise RuntimeError("password=1234 in /app/secret_file.py")

    app.add_api_route("/api/test-crash", crash)
    response = client.get("/api/test-crash")

    assert response.status_code == 500
    assert response.json() == {"detail": "Something went wrong. Please try again."}
    assert "password" not in response.text