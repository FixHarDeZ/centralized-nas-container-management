import sys

from app.shop_api import create_app
from fastapi.testclient import TestClient


def test_shop_empty_page_and_navigation(tmp_path):
    client = TestClient(create_app(tmp_path))
    response = client.get('/shop')
    assert response.status_code == 200
    assert 'เริ่มคลิปสินค้า' in response.text
    assert '/static/shop.js' in response.text
    assert 'id="new-product"' in response.text


def test_workspace_escapes_user_fields_and_has_scene_actions(tmp_path):
    app = create_app(tmp_path)
    job = app.state.store.create_job({'name': '<script>alert(1)</script>', 'brief': 'ทดสอบ'})
    response = TestClient(app).get('/shop/' + job['id'])
    assert response.status_code == 200
    assert '<script>alert(1)</script>' not in response.text
    assert '&lt;script&gt;' in response.text
    assert 'id="product-form"' in response.text
    assert 'id="scenes"' in response.text
    assert 'id="final-render"' in response.text
    assert 'id="shop-state"' in response.text


def test_missing_shop_job_is_not_found(tmp_path):
    response = TestClient(create_app(tmp_path)).get('/shop/missing')
    assert response.status_code == 404


def test_shop_api_does_not_load_drawing_libraries_in_fresh_process(tmp_path):
    import os
    import subprocess

    result = subprocess.run([sys.executable, '-c',
        'from pathlib import Path; from app.shop_api import create_app; '
        f'create_app(Path({str(tmp_path)!r})); '
        'import sys; assert "PIL" not in sys.modules; assert "edge_tts" not in sys.modules'],
        env={**os.environ, 'PYTHONPATH': 'shorts-factory'}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
