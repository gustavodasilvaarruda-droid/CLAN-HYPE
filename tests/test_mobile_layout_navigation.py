"""Regressoes estaticas da camada de menu e do dashboard HYPE em celulares.

Esses testes nao substituem a verificacao visual real em Android/iOS.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_menu_backdrop_no_mesmo_contexto_de_empilhamento():
    script = (ROOT / "static" / "mobile_v36.js").read_text(encoding="utf-8")
    assert "sidebar?.closest('.hgb-app') || document.body" in script
    assert "host.appendChild(backdrop)" in script
    assert "document.body.appendChild(backdrop)" not in script


def test_dashboard_nao_forca_coluna_de_410_px_no_celular():
    css = (ROOT / "static" / "mobile_v36.css").read_text(encoding="utf-8")
    assert ".hype-dashboard-page .hype-v6-profile-grid" in css
    assert "grid-template-columns: minmax(0,1fr) !important" in css
    assert ".hype-dashboard-page .member2-columns" in css
    assert "@media (max-width: 420px)" in css


def test_menu_mobile_tem_posicao_e_largura_responsivas():
    css = (ROOT / "static" / "mobile_v36.css").read_text(encoding="utf-8")
    assert ".hype-core-sidebar.open" in css
    assert "height: calc(100dvh - 58px) !important" in css
    assert ".hype-core-app" in css


def test_base_html_carrega_assets_revisados():
    base = (ROOT / "templates" / "hype_app_base.html").read_text(encoding="utf-8")
    assert "mobile_v36.css')}}?v=3611" in base
    assert "mobile_v36.js')}}?v=3611" in base
