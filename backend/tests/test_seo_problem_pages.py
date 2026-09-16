from app.config import settings
from app.family_manifest import FAMILY_MANIFEST
from app.seo_pages import SEO_PROBLEM_PAGES


def test_problem_page_registry_covers_every_supported_family_once():
    families = [page.family for page in SEO_PROBLEM_PAGES]
    paths = [page.path for page in SEO_PROBLEM_PAGES]

    assert set(families) == set(FAMILY_MANIFEST)
    assert len(families) == len(set(families))
    assert len(paths) == len(set(paths))
    assert any(page.vertical == "electricity" for page in SEO_PROBLEM_PAGES)
    assert any(page.vertical == "purchases" for page in SEO_PROBLEM_PAGES)


def test_alpha_problem_page_is_reachable_but_not_indexable(client):
    response = client.get("/reclamar/luz/mantenimiento-despues-cambiar-compania-luz")

    assert response.status_code == 200
    assert '<meta name="robots" content="noindex,nofollow">' in response.text
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
    assert "Mantenimiento cobrado después de cambiar de compañía de luz" in response.text
    assert "no decide por sí sola tu caso" in response.text
    assert "Motor de Resolución" in response.text
    assert "https://www.boe.es/" in response.text
    assert "default-src 'self'" in response.headers["content-security-policy"]


def test_unknown_problem_page_returns_404(client):
    response = client.get("/reclamar/luz/problema-inventado")
    assert response.status_code == 404


def test_public_indexing_enables_canonical_problem_pages_and_complete_sitemap(client, monkeypatch):
    monkeypatch.setattr(settings, "public_indexing_enabled", True)
    monkeypatch.setattr(settings, "public_base_url", "https://www.mecorresponde.es")

    page = next(item for item in SEO_PROBLEM_PAGES if item.family == "C04")
    response = client.get(page.path)

    assert response.status_code == 200
    assert '<meta name="robots" content="index,follow">' in response.text
    assert "x-robots-tag" not in response.headers
    assert f'<link rel="canonical" href="https://www.mecorresponde.es{page.path}">' in response.text
    assert 'type="application/ld+json"' in response.text

    sitemap = client.get("/sitemap.xml")
    assert sitemap.status_code == 200
    assert sitemap.text.count("<url><loc>") == len(SEO_PROBLEM_PAGES) + 1
    assert "<loc>https://www.mecorresponde.es/</loc>" in sitemap.text
    for registered in SEO_PROBLEM_PAGES:
        assert f"<loc>https://www.mecorresponde.es{registered.path}</loc>" in sitemap.text


def test_homepage_links_to_problem_library_for_internal_discovery(client):
    response = client.get("/")
    assert response.status_code == 200
    assert 'id="problem-library"' in response.text
    assert "/reclamar/luz/" in response.text
    assert "/reclamar/compras/" in response.text
    for page in SEO_PROBLEM_PAGES:
        assert f'href="{page.path}"' in response.text
