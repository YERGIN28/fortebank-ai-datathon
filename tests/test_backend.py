from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import main


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "API_KEY", "test-key")
    with TestClient(main.app) as instance:
        yield instance


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}, {"X-API-Key": ""}])
def test_auth_returns_same_401(client, headers):
    for response in (
        client.get("/api/v1/jobs/missing", headers=headers),
        client.post("/api/v1/analyze", headers=headers, files={"file": ("video.mov", b"video")}),
    ):
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid API key"}


def test_unconfigured_key_never_authenticates(client, monkeypatch):
    monkeypatch.setattr(main, "API_KEY", None)
    assert client.get("/api/v1/jobs/missing").status_code == 401


def test_invalid_extension_and_unknown_job(client):
    headers = {"X-API-Key": "test-key"}
    assert client.get("/api/v1/jobs/missing", headers=headers).status_code == 404
    for route in ("/api/v1/analyze", "/ui/analyze"):
        assert client.post(route, headers=headers, files={"file": ("video.mp4", b"video")}).status_code == 400


def test_public_schema_and_ui(client):
    assert set(client.get("/openapi.json").json()["paths"]) == {
        "/api/v1/analyze", "/api/v1/jobs/{job_id}",
    }
    html = client.get("/").text
    assert "X-API-Key" not in html
    assert "data:image/jpeg;base64," in html
    assert "/ui/analyze" in html


@pytest.mark.parametrize("name", ["../../test.mov", r"C:\incoming\test.mov", "test.mov"])
def test_safe_upload_name(name):
    assert main.safe_upload_name(name) == "test.mov"


@pytest.mark.parametrize("name", [None, "", "test.mp4", "bad:name.mov", "bad\x00.mov"])
def test_invalid_upload_name(name):
    with pytest.raises(main.HTTPException) as exc:
        main.safe_upload_name(name)
    assert exc.value.status_code == 400
