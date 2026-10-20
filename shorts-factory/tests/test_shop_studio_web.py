"""Creator Studio jobs made as a Storyboard Studio pack (docs/adr/0018, phase 2)."""
import asyncio
import io
import json
import subprocess

import pytest
from app import shop_render, shop_studio, shop_worker
from app.shop_store import Invalid, Store
from PIL import Image

LOCK = "the same 25-year-old Thai woman with a long ponytail"


def sample_pitch():
    line = 'สินค้าน่าใช้ค่ะ'
    return {'title': 'สินค้า', 'caption': 'สินค้าน่าใช้ค่ะ', 'hashtags': ['#สินค้า'],
            'price': '299', 'old_price': '399', 'end_badge': 'ดูสินค้า',
            'end_narration': 'ดูสินค้าได้เลยค่ะ', 'end_spoken': 'ดูสินค้าได้เลยค่ะ',
            'beats': [{'badge': 'สินค้า', 'narration': line, 'spoken': line, 'lines': [line], 'photo': 1}
                      for _ in range(3)]}


def board(n):
    return {'overview': {'title': 't', 'title_en': 'Handy Thing', 'product_en': 'a desk lamp',
                         'master_character': {'locked_prompt_tag': LOCK}},
            'scenes': [{'image_gen_prompt': f'{LOCK} holds @Product, 9:16, no text', 'motion': 'Static camera',
                        'sound_verbatim': 'สินค้าน่าใช้ค่ะ', 'card': i} for i in range(n)]}


def run(worker):
    return asyncio.run(worker.run_once())


def drain(worker):
    while run(worker):
        pass


@pytest.fixture
def studio_job(tmp_path, monkeypatch):
    store = Store(tmp_path)
    job = store.create_job({'name': 'โคมไฟ', 'brief': 'โคมไฟตั้งโต๊ะ 299 399', 'current_price': '299',
                            'old_price': '399', 'mode': 'studio'})
    data = io.BytesIO()
    Image.new('RGB', (80, 80)).save(data, 'PNG')
    data.seek(0)
    store.add_asset(job['id'], job['revision'], 'reference', 'ref.png', data)
    worker = shop_worker.Worker(store)
    drain(worker)

    async def generate(*args, **kwargs):
        return sample_pitch()

    async def measure(script, workdir):
        return [3.0] * len(script['cards'])

    async def plan(script, product, choice, character='', fixed_tag=''):
        data = board(len(script['cards']))
        return shop_studio._finish(script)(data)

    monkeypatch.setattr(shop_worker.shop, 'generate', generate)
    monkeypatch.setattr(shop_studio, 'measure', measure)
    monkeypatch.setattr(shop_studio, 'plan', plan)
    job = store.get_job(job['id'])
    store.request_plan(job['id'], job['revision'])
    drain(worker)
    return store, worker, store.get_job(job['id'])


def test_a_studio_job_plans_one_speaking_flow_shot_per_line_plus_the_closing(studio_job):
    _, _, job = studio_job
    plan = job['plan']
    assert job['mode'] == 'studio' and job['plan_error'] is None
    assert job['validated_plan_version'] == job['plan_version']
    assert len(plan['scenes']) == 4 and {s['source'] for s in plan['scenes']} == {'flow'}
    assert plan['scenes'][-1]['narration'] == plan['end_narration'] == shop_worker.CTA['shopee'] + 'ได้เลยค่ะ'
    assert all(s['seconds'] == 8.0 and s['flow_prompt'].startswith('Speaks in Thai:') for s in plan['scenes'])
    pack = plan['studio']
    assert pack['length'] == 32.0 and pack['credits'] == 48 and pack['tag'] == '@Lead'
    assert 'Products:\n@Product is a desk lamp' in pack['markdown'] and pack['markdown'].count('Scene ') == 4


def test_a_studio_plan_edit_may_retitle_but_never_change_what_is_said(studio_job):
    store, _, job = studio_job
    edited = json.loads(json.dumps(job['plan']))
    edited['scenes'][0]['narration'] = 'อื่นค่ะ'
    with pytest.raises(Invalid, match='Studio'):
        store.save_plan(job['id'], job['revision'], edited)
    retitled = {**job['plan'], 'title': 'ชื่อใหม่', 'studio': {'markdown': 'forged'}}
    saved = store.save_plan(job['id'], job['revision'], retitled)
    assert saved['plan']['title'] == 'ชื่อใหม่' and saved['plan']['studio'] == job['plan']['studio']


def export_file(path, seconds):
    subprocess.run(['ffmpeg', '-y', '-f', 'lavfi', '-i', f'testsrc=size=360x640:rate=12:duration={seconds}',
                    '-f', 'lavfi', '-i', f'sine=frequency=300:duration={seconds}', '-shortest',
                    '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac', str(path)],
                   check=True, capture_output=True)
    return io.BytesIO(path.read_bytes())


def approved(store, worker, job):
    drain(worker)
    job = store.get_job(job['id'])
    return store.approve_plan(job['id'], job['revision'])


def test_one_export_is_cut_into_every_scene_with_its_voice_and_renders(studio_job, tmp_path, monkeypatch):
    store, worker, job = studio_job
    job = approved(store, worker, job)
    with pytest.raises(Invalid, match='one export'):
        store.add_asset(job['id'], job['revision'], 'scene', 'x.mp4', io.BytesIO(b'v'), scene_id='scene-1')
    store.add_asset(job['id'], job['revision'], 'export', 'flow.mp4', export_file(tmp_path / 'e.mp4', 32))
    drain(worker)
    job = store.get_job(job['id'])
    assert job['export']['status'] == 'cut'
    kinds = {a['id']: a['kind'] for a in store.list_assets(job['id'])}
    assert all(kinds[s['media_id']] == 'scene' and kinds[s['voice_id']] == 'voice' for s in job['plan']['scenes'])
    for scene in job['plan']['scenes']:
        job = store.accept_scene(job['id'], job['revision'], scene['id'], reference_matches=True)
    render = store.request_render(job['id'], job['revision'])
    assert {s['voice_id'] for s in job['plan']['scenes']} <= set(render['snapshot']['assets'])
    monkeypatch.setattr(shop_studio.render, 'pick_music', lambda: None)
    snapshot = {**render['snapshot'], 'plan': shop_render.canonical_plan(render['snapshot'])}
    clip, details = asyncio.run(shop_render.build_snapshot(snapshot, store.media_root, tmp_path / 'work'))
    assert clip.is_file() and details['mode'] == 'studio' and len(details['shots']) == 4


def test_an_export_of_the_wrong_length_waits_for_cut_evenly(studio_job, tmp_path):
    store, worker, job = studio_job
    job = approved(store, worker, job)
    store.add_asset(job['id'], job['revision'], 'export', 'flow.mp4', export_file(tmp_path / 'e.mp4', 28))
    drain(worker)
    job = store.get_job(job['id'])
    assert job['export']['status'] == 'uneven' and job['export']['expected'] == 32.0
    assert not any(s.get('media_id') for s in job['plan']['scenes'])
    store.request_even_cut(job['id'], job['revision'])
    drain(worker)
    job = store.get_job(job['id'])
    assert job['export']['status'] == 'cut' and all(s.get('voice_id') for s in job['plan']['scenes'])


def test_a_scenes_job_takes_no_export_and_switching_mode_drops_the_plan(tmp_path):
    store = Store(tmp_path)
    job = store.create_job({'name': 'x'})
    with pytest.raises(Invalid, match='Studio'):
        store.add_asset(job['id'], job['revision'], 'export', 'e.mp4', io.BytesIO(b'v'))
    with store._tx() as db:
        job.update(plan={'title': 'old', 'scenes': []})
        store._save(db, 'jobs', job)
    job = store.update_job(job['id'], job['revision'], {'mode': 'studio', 'character': 'kim'})
    assert job['plan'] is None and job['mode'] == 'studio' and job['character'] == 'kim'
    with pytest.raises(Invalid):
        store.update_job(job['id'], job['revision'], {'mode': 'reels'})
