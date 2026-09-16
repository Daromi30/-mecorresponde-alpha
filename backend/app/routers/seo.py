from __future__ import annotations

import json
from html import escape

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..family_manifest import FAMILY_MANIFEST
from ..models import LegalRuleVersion, LegalSource
from ..seo_pages import SEO_BY_PATH, SEO_PROBLEM_PAGES


router = APIRouter(tags=["public-seo"])


def _public_base_url() -> str:
    return settings.public_base_url.strip().rstrip("/")


def _legal_sources(db: Session, family: str) -> list[dict[str, str]]:
    manifest = FAMILY_MANIFEST.get(family)
    if manifest is None:
        return []

    rows = db.scalars(
        select(LegalRuleVersion)
        .where(
            LegalRuleVersion.rule_id.in_(manifest.rule_ids),
            LegalRuleVersion.review_status == "approved",
        )
        .order_by(LegalRuleVersion.rule_id.asc(), LegalRuleVersion.version.desc())
    ).all()

    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for row in rows:
        if row.rule_id in seen:
            continue
        source = db.get(LegalSource, row.source_id)
        if source is None or source.status != "active":
            continue
        seen.add(row.rule_id)
        result.append(
            {
                "authority": source.authority,
                "title": source.title,
                "article": row.article,
                "official_url": source.official_url,
            }
        )
    return result


def _problem_links(current_family: str) -> str:
    related = [page for page in SEO_PROBLEM_PAGES if page.family != current_family][:6]
    return "".join(
        f'<li><a href="{escape(page.path, quote=True)}">{escape(page.title)}</a></li>'
        for page in related
    )


def _render_problem_page(page, sources: list[dict[str, str]]) -> str:
    indexing = settings.public_indexing_ready
    robots = "index,follow" if indexing else "noindex,nofollow"
    canonical = f"{_public_base_url()}{page.path}" if indexing else ""
    canonical_tag = f'<link rel="canonical" href="{escape(canonical, quote=True)}">' if canonical else ""
    source_items = "".join(
        "<li>"
        f'<a rel="nofollow" href="{escape(item["official_url"], quote=True)}">'
        f'{escape(item["authority"])} — {escape(item["title"])}</a>'
        f' <span class="muted">(art. {escape(item["article"])})</span>'
        "</li>"
        for item in sources
    )
    if not source_items:
        source_items = "<li>Las fuentes aplicables se mostrarán cuando estén verificadas en el catálogo jurídico del Motor.</li>"

    evidence_items = "".join(f"<li>{escape(item)}</li>" for item in page.evidence_examples)
    breadcrumb = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "MECORRESPONDE", "item": f"{_public_base_url()}/" if indexing else "/"},
            {"@type": "ListItem", "position": 2, "name": "Problemas", "item": f"{_public_base_url()}/reclamar" if indexing else "/reclamar"},
            {"@type": "ListItem", "position": 3, "name": page.title, "item": canonical if indexing else page.path},
        ],
    }
    webpage = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": page.title,
        "description": page.description,
        "url": canonical if indexing else page.path,
        "isPartOf": {"@type": "WebSite", "name": "MECORRESPONDE"},
    }

    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="{robots}">
<title>{escape(page.title)} | MECORRESPONDE</title>
<meta name="description" content="{escape(page.description, quote=True)}">
{canonical_tag}
<script type="application/ld+json">{json.dumps(webpage, ensure_ascii=False).replace('<', '\\u003c')}</script>
<script type="application/ld+json">{json.dumps(breadcrumb, ensure_ascii=False).replace('<', '\\u003c')}</script>
<style>
:root{{font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#17202a;background:#f6f7f8}}
*{{box-sizing:border-box}}body{{margin:0}}a{{color:inherit}}.wrap{{max-width:920px;margin:auto;padding:28px 20px 60px}}
.brand{{font-weight:800;letter-spacing:-.02em;text-decoration:none}}.crumb{{font-size:.9rem;color:#59636e;margin:24px 0}}
.hero,.card{{background:#fff;border:1px solid #e5e8eb;border-radius:18px;padding:28px;margin-bottom:18px}}
h1{{font-size:clamp(2rem,5vw,3.4rem);line-height:1.02;letter-spacing:-.04em;margin:8px 0 18px}}h2{{margin-top:0}}
p,li{{line-height:1.6}}.muted{{color:#66717c}}.cta{{display:inline-block;background:#17202a;color:#fff;text-decoration:none;padding:13px 18px;border-radius:12px;font-weight:700}}
.notice{{border-left:4px solid #17202a;padding-left:16px}}ul{{padding-left:22px}}footer{{margin-top:30px;color:#66717c;font-size:.9rem}}
</style>
</head>
<body>
<main class="wrap">
<a class="brand" href="/">MECORRESPONDE</a>
<div class="crumb"><a href="/">Inicio</a> · {escape(page.title)}</div>
<section class="hero">
<p class="muted">Motor de Resolución · {escape(page.family)}</p>
<h1>{escape(page.title)}</h1>
<p>{escape(page.intro)}</p>
<a class="cta" href="/demo/">Analizar mi caso</a>
</section>
<section class="card">
<h2>Qué conviene tener a mano</h2>
<ul>{evidence_items}</ul>
<p class="muted">No necesitas tenerlo todo para empezar. El Motor debe distinguir entre lo que afirmas, lo que está confirmado y lo que todavía falta acreditar.</p>
</section>
<section class="card">
<h2>Cómo lo trabaja MECORRESPONDE</h2>
<p>El recorrido no termina en redactar una carta: problema → si te corresponde → cuánto hay en juego → si compensa → documentación → acción → respuesta → análisis → escalado → resolución.</p>
<p class="notice"><strong>Importante:</strong> esta página no decide por sí sola tu caso. Las conclusiones dependen de los hechos, las pruebas y las fuentes aplicables. Cuando el Motor no puede concluir de forma segura, debe detener la automatización y pedir revisión humana.</p>
</section>
<section class="card">
<h2>Fuentes oficiales conectadas a esta familia</h2>
<ul>{source_items}</ul>
<p class="muted">MECORRESPONDE muestra únicamente referencias enlazadas al catálogo jurídico revisado. La existencia de una fuente no significa que su consecuencia se aplique automáticamente a tu caso.</p>
</section>
<section class="card">
<h2>Otros problemas que estamos estructurando</h2>
<ul>{_problem_links(page.family)}</ul>
</section>
<footer>MECORRESPONDE · Orientación automatizada con escalado a revisión profesional cuando existe incertidumbre relevante.</footer>
</main>
</body>
</html>"""


@router.get("/reclamar/{vertical_slug}/{problem_slug}", response_class=HTMLResponse, include_in_schema=False)
def problem_page(vertical_slug: str, problem_slug: str, db: Session = Depends(get_db)):
    page = SEO_BY_PATH.get((vertical_slug, problem_slug))
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found")
    return HTMLResponse(_render_problem_page(page, _legal_sources(db, page.family)))
