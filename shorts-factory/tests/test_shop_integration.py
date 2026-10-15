"""HTTP -> durable worker -> real FFmpeg -> download. No provider/network calls."""
import asyncio
import io
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from app import render, shop_worker
from app.shop_api import create_app
from app.shop_media import probe
from fastapi.testclient import TestClient
from PIL import Image, features

from .test_shop_worker import sample_pitch


@pytest.mark.skipif(not features.check('raqm') or not Path(render.THAI_BOLD).exists(), reason='production Thai font/Raqm required')
def test_http_job_survives_restart_and_exports_real_video(tmp_path, monkeypatch):
    monkeypatch.setenv('SHOP_AUTOMATION_TOKEN', 'test-only')
    monkeypatch.setenv('OUTPUT_DIR', str(tmp_path / 'output'))
    monkeypatch.delenv('SHOP_MEDIA_ROOT', raising=False)
    app = create_app(tmp_path / 'store')
    client = TestClient(app)
    token = client.get('/shop/api/session').json()['csrf_token']
    headers = {'Origin': 'http://testserver', 'X-CSRF-Token': token}
    notices = []

    async def generate(*args, **kwargs):
        return sample_pitch()

    async def narration(cards, workdir, **kwargs):
        audio = workdir / 'tts.wav'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                        'anullsrc=r=44100:cl=mono', '-t', '0.8', str(audio)], check=True)
        return audio, [0, .2, .4, .6]

    async def send(text):
        notices.append(text)

    monkeypatch.setattr(shop_worker.shop, 'generate', generate)
    monkeypatch.setattr(render, '_narration_track', narration)
    monkeypatch.setattr(render, 'TAIL_PAD', 0)
    monkeypatch.setattr(render, 'pick_music', lambda: None)
    worker = shop_worker.Worker(app.state.store, send=send)

    def drain():
        async def run():
            for _ in range(20):
                if not await worker.run_once():
                    return
            raise AssertionError('queue did not drain')
        asyncio.run(run())

    response = client.post('/shop/api/jobs', headers=headers,
        json={'name': 'สินค้าทดสอบ', 'brief': 'สินค้าน่าใช้ค่ะ ราคา 299 จาก 399', 'destination': 'shopee',
                                 'affiliate_link': 'https://example.test/affiliate'})
    assert response.status_code == 201, response.text
    job = response.json()
    base = '/shop/api/jobs/' + job['id']

    def current():
        return client.get(base).json()

    def post(suffix, **data):
        result = client.post(base + suffix, headers=headers,
                             json={'revision': current()['revision'], **data})
        assert result.status_code in (200, 202), result.text
        return result.json()

    picture = io.BytesIO()
    Image.new('RGB', (200, 240), 'orange').save(picture, format='PNG')
    response = client.post(base + '/references', headers=headers,
                           data={'revision': current()['revision']},
                           files={'file': ('product.png', picture.getvalue(), 'image/png')})
    assert response.status_code == 201, response.text
    drain()
    post('/plan/request')
    drain()
    assert current()['validated_plan_version'] == current()['plan_version']
    post('/plan/approve')
    source = tmp_path / 'motion.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=s=160x120:d=0.5',
                    '-c:v', 'libx264', '-threads', '2', str(source)], check=True)
    for scene in current()['plan']['scenes']:
        response = client.post(base + '/scenes/' + scene['id'] + '/media', headers=headers,
                               data={'revision': current()['revision']},
                               files={'file': ('scene.mp4', source.read_bytes(), 'video/mp4')})
        assert response.status_code == 201, response.text
        drain()
        post('/scenes/' + scene['id'] + '/accept', reference_matches=True)
    pending = post('/renders')
    automation = {'X-Shop-Token': 'test-only'}
    body = {'revision': pending['revision'], 'idempotency_key': 'integration-' + pending['id']}
    url = '/shop/automation/renders/' + pending['id'] + '/start'
    first = client.post(url, headers=automation, json=body)
    again = client.post(url, headers=automation, json=body)
    assert first.status_code == again.status_code == 200
    assert first.json()['id'] == again.json()['id']
    assert 'snapshot' not in first.json()
    drain()
    restarted = TestClient(create_app(tmp_path / 'store'))
    final = restarted.get(base + '/renders/' + pending['id']).json()
    assert final['status'] == 'ready', final.get('error')
    response = restarted.get(base + '/renders/' + pending['id'] + '/media/video')
    assert response.status_code == 200
    clip = tmp_path / 'download.mp4'
    clip.write_bytes(response.content)
    info = probe(clip)
    assert (info['width'], info['height'], info['has_audio']) == (1080, 1920, True)
    caption = restarted.get(base + '/renders/' + pending['id'] + '/media/caption').text
    assert '#ad' in caption and 'https://example.test/affiliate' in caption
    assert notices
    post('/renders/' + pending['id'] + '/approve')
    assert current()['final_approved_render_id'] == pending['id']
    if destination := os.environ.get('SHOP_TEST_ARTIFACT_DIR'):
        Path(destination).mkdir(parents=True, exist_ok=True)
        shutil.copy2(clip, Path(destination) / 'shop-flow-synthetic.mp4')
