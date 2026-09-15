from app.config import settings


def test_alpha_root_is_publicly_reachable_but_not_indexable(client):
    response = client.get("/")
    assert response.status_code == 200
    assert '<meta name="robots" content="noindex,nofollow">' in response.text
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
    assert "MECORRESPONDE | Comprueba si te corresponde reclamar" in response.text
    assert '<meta name="description"' in response.text
    assert "default-src 'self'" in response.headers["content-security-policy"]

    robots = client.get("/robots.txt")
    assert robots.status_code == 200
    assert "User-agent: *" in robots.text
    assert "Allow: /" in robots.text
    assert "Sitemap:" not in robots.text

    sitemap = client.get("/sitemap.xml")
    assert sitemap.status_code == 404


def test_indexing_flag_alone_cannot_index_without_https_base_url(client, monkeypatch):
    monkeypatch.setattr(settings, "public_indexing_enabled", True)
    monkeypatch.setattr(settings, "public_base_url", "http://mecorresponde.invalid")

    response = client.get("/")
    assert response.status_code == 200
    assert '<meta name="robots" content="noindex,nofollow">' in response.text
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
    assert client.get("/sitemap.xml").status_code == 404


def test_https_public_configuration_enables_canonical_and_sitemap(client, monkeypatch):
    monkeypatch.setattr(settings, "public_indexing_enabled", True)
    monkeypatch.setattr(settings, "public_base_url", "https://www.mecorresponde.es")

    response = client.get("/")
    assert response.status_code == 200
    assert '<meta name="robots" content="index,follow">' in response.text
    assert "x-robots-tag" not in response.headers
    assert '<link rel="canonical" href="https://www.mecorresponde.es/">' in response.text
    assert 'property="og:title"' in response.text
    assert 'type="application/ld+json"' in response.text

    robots = client.get("/robots.txt")
    assert "Sitemap: https://www.mecorresponde.es/sitemap.xml" in robots.text

    sitemap = client.get("/sitemap.xml")
    assert sitemap.status_code == 200
    assert sitemap.headers["content-type"].startswith("application/xml")
    assert "<loc>https://www.mecorresponde.es/</loc>" in sitemap.text


def test_internal_surfaces_are_always_noindex(client, monkeypatch):
    monkeypatch.setattr(settings, "public_indexing_enabled", True)
    monkeypatch.setattr(settings, "public_base_url", "https://www.mecorresponde.es")

    health = client.get("/health")
    assert health.status_code == 200
    assert health.headers["x-robots-tag"] == "noindex, nofollow"

    demo = client.get("/demo/")
    assert demo.status_code == 200
    assert demo.headers["x-robots-tag"] == "noindex, nofollow"
