import asyncio
import io
import time

import pytest
from app.shop_store import Store
from PIL import Image


def reference(store, job):
    data = io.BytesIO()
    Image.new('RGB', (80, 80)).save(data, 'PNG')
    data.seek(0)
    asset = store.add_asset(job['id'], job['revision'], 'reference', 'ref.png', data)
    return asset


def test_probe_command_and_unique_claim_owners(tmp_path):
    from app.shop_worker import Worker
    store = Store(tmp_path)
    job = store.create_job({'name': 'Product'})
    asset = reference(store, job)
    worker = Worker(store)
    assert asyncio.run(worker.run_once()) is True
    assert store.get_asset(asset['id'])['validation'] == 'valid'
    assert asyncio.run(worker.run_once()) is False


def test_heartbeat_continues_during_blocking_work_and_stale_result_rejected(tmp_path):
    from app.shop_worker import Worker
    store = Store(tmp_path)
    job = store.create_job({'name': 'Product'})
    asset = reference(store, job)
    worker = Worker(store, lease_seconds=1, heartbeat_seconds=.05)
    original = worker.probe_asset
    def slow(command, owner):
        time.sleep(1.3)
        return original(command, owner)
    worker.probe_asset = slow
    assert asyncio.run(worker.run_once())
    assert store.get_asset(asset['id'])['validation'] == 'valid'
    with store._tx() as db:
        command = store._get(db, 'commands', next(db.execute('SELECT id FROM commands'))[0])
    assert command['status'] == 'done'
    assert command['heartbeat_at'] > command['created_at'] + .5


def test_generation_error_preserves_old_plan_validation(tmp_path, monkeypatch):
    from app import shop_worker
    store = Store(tmp_path)
    job = store.create_job({'name': 'Product'})
    reference(store, job)
    job = store.get_job(job['id'])
    # The old successful content survives a provider failure.
    with store._tx() as db:
        job.update(plan={'title': 'old'}, plan_version=1, validated_plan_version=1)
        store._save(db, 'jobs', job)
    store.request_plan(job['id'], job['revision'])
    async def fail(*args, **kwargs):
        raise RuntimeError('provider unavailable')
    monkeypatch.setattr(shop_worker.shop, 'generate', fail)
    worker = shop_worker.Worker(store)
    asyncio.run(worker.run_once())  # probe
    asyncio.run(worker.run_once())  # generation
    saved = store.get_job(job['id'])
    assert saved['plan']['title'] == 'old'
    assert saved['validated_plan_version'] == 1
    assert 'provider unavailable' in saved['generation_error']


def test_notification_has_three_attempt_ceiling(tmp_path):
    from app.shop_worker import Worker
    store = Store(tmp_path)
    job = store.create_job({'name': 'Product'})
    store.notify(job['id'], 'plan_ready', 'test')
    async def fail(text):
        raise RuntimeError('offline')
    worker = Worker(store, send=fail, notification_backoff=0)
    for _ in range(4):
        asyncio.run(worker.run_once())
    with store._tx() as db:
        command = store._get(db, 'commands', next(db.execute('SELECT id FROM commands'))[0])
    assert command['attempts'] == 3
    assert command['status'] == 'failed'
    assert store.get_job(job['id'])['notification_error'] == 'offline'


def sample_pitch():
    narration = 'สินค้าน่าใช้ค่ะ'
    return {'title': 'สินค้า', 'caption': 'สินค้าน่าใช้ค่ะ', 'hashtags': ['#สินค้า'],
            'price': '299', 'old_price': '399', 'end_badge': 'ดูสินค้า',
            'end_narration': 'ดูสินค้าได้เลยค่ะ', 'end_spoken': 'ดูสินค้าได้เลยค่ะ',
            'beats': [{'badge': 'สินค้า', 'narration': narration, 'spoken': narration,
                       'lines': [narration], 'photo': 1} for _ in range(3)]}


def test_generated_plan_preserves_full_pitch_and_validates_destination(tmp_path, monkeypatch):
    from app import shop_worker
    store = Store(tmp_path)
    job = store.create_job({'name': 'สินค้า', 'brief': 'สินค้า 299 399', 'current_price': '299', 'old_price': '399', 'destination': 'youtube'})
    reference(store, job)
    worker = shop_worker.Worker(store)
    asyncio.run(worker.run_once())
    job = store.get_job(job['id'])
    store.request_plan(job['id'], job['revision'])
    async def generate(*args, **kwargs):
        return sample_pitch()
    monkeypatch.setattr(shop_worker.shop, 'generate', generate)
    asyncio.run(worker.run_once())
    generated = store.get_job(job['id'])
    assert generated['plan']['end_badge'] == 'ดูสินค้า'
    assert generated['plan']['price'] == '299'
    assert generated['plan']['caption'] == 'สินค้าน่าใช้ค่ะ'
    assert generated['plan']['cta'] == shop_worker.CTA['youtube']
    assert 'โปรไฟล์' in generated['plan']['end_narration']
    assert 'ตะกร้า' not in generated['plan']['end_narration']
    assert all('user-provided' in scene['flow_prompt'] for scene in generated['plan']['scenes'])
    asyncio.run(worker.run_once())
    validated = store.get_job(job['id'])
    assert validated['plan_error'] is None
    assert validated['validated_plan_version'] == validated['plan_version']


def test_reclaimed_probe_cannot_publish_even_with_same_worker(tmp_path):
    from app.shop_store import Conflict
    from app.shop_worker import Worker
    store = Store(tmp_path)
    job = store.create_job({'name': 'Product'})
    asset = reference(store, job)
    old = store.claim_command('old', lease_seconds=1, now=time.time() - 3)
    new = store.claim_command('new')
    assert old['id'] == new['id']
    with pytest.raises(Conflict):
        Worker(store).probe_asset(old, 'old')
    assert store.get_asset(asset['id'])['validation'] == 'pending'


def test_render_publishes_frozen_snapshot_caption_and_unique_atomic_paths(tmp_path, monkeypatch):
    from app import shop_worker
    store = Store(tmp_path / 'db', tmp_path / 'media')
    job = store.create_job({'name': 'สินค้า', 'brief': 'สินค้า 299 399', 'affiliate_link': 'https://example.test/buy'})
    photo = reference(store, job)
    store.validate_asset(photo['id'], {'type': 'image', 'width': 80, 'height': 80}, valid=True)
    job = store.get_job(job['id'])
    pitch = sample_pitch()
    pitch.update(title=' สินค้า ', price='฿299', old_price='฿399')
    pitch['beats'][0]['lines'] = ['', ' สินค้าน่าใช้ค่ะ ', '   ']
    scenes = [{**beat, 'id': str(i), 'source': 'real', 'reference_id': photo['id'], 'fit': 'contain'} for i, beat in enumerate(pitch['beats'])]
    job = store.save_plan(job['id'], job['revision'], {**pitch, 'scenes': scenes})
    store.validate_plan(job['id'], job['plan_version'], valid=True)
    job = store.approve_plan(job['id'], job['revision'])
    for scene in scenes:
        clip = store.add_asset(job['id'], job['revision'], 'scene', 'source.mp4', io.BytesIO(b'stub'), scene_id=scene['id'])
        store.validate_asset(clip['id'], {'type': 'video', 'duration': 3}, valid=True)
        job = store.get_job(job['id'])
        job = store.accept_scene(job['id'], job['revision'], scene['id'], reference_matches=True)
    attempt = store.request_render(job['id'], job['revision'])
    store.start_render(attempt['id'], attempt['revision'], 'render-test')
    # The job may change while the already-dispatched immutable attempt renders.
    store.update_job(job['id'], job['revision'], {'affiliate_link': 'https://example.test/changed'})
    captured = []
    async def build(snapshot, media_root, workdir):
        captured.append(snapshot)
        workdir.mkdir(parents=True)
        clip = workdir / 'clip.mp4'
        clip.write_bytes(b'generated video')
        return clip, {'seconds': 1}
    monkeypatch.setattr(shop_worker.shop_render, 'build_snapshot', build)
    monkeypatch.setenv('OUTPUT_DIR', str(tmp_path))
    worker = shop_worker.Worker(store)
    # Claim render directly so intentionally queued old probes/validation cannot alter fixtures.
    command = store.claim_command('owner-token', kinds=['render'])
    worker.render(command, 'owner-token')
    rendered = store.get_render(attempt['id'])
    assert rendered['status'] == 'ready'
    assert captured[0]['affiliate_link'] == 'https://example.test/buy'
    assert captured[0]['plan']['price'] == '299'
    assert captured[0]['plan']['scenes'][0]['lines'] == ['สินค้าน่าใช้ค่ะ']
    assert 'owner-token' in rendered['outputs']['video']
    assert (store.media_root / rendered['outputs']['video']).read_bytes() == b'generated video'
    caption = (store.media_root / rendered['outputs']['caption']).read_text()
    assert shop_worker.shop.DISCLOSURE in caption
    assert 'https://example.test/buy' in caption
    assert 'https://example.test/changed' not in caption
    assert not list((store.media_root / 'renders').rglob('*.tmp'))


def test_crashed_third_notification_is_not_sent_a_fourth_time(tmp_path):
    from app.shop_worker import Worker
    store = Store(tmp_path)
    job = store.create_job({'name': 'Product'})
    command = store.notify(job['id'], 'plan_ready', 'test')
    with store._tx() as db:
        command.update(status='running', attempts=3, owner='crashed', lease_until=time.time() - 1)
        store._save(db, 'commands', command)
    sent = []
    async def send(text):
        sent.append(text)
    asyncio.run(Worker(store, send=send).run_once())
    assert sent == []
    with store._tx() as db:
        saved = store._get(db, 'commands', command['id'])
    assert saved['status'] == 'failed'


def test_legacy_and_worker_share_the_same_render_lock(tmp_path, monkeypatch):
    from app.render_lock import render_slot, render_slot_sync
    monkeypatch.setenv('OUTPUT_DIR', str(tmp_path))
    acquired = []
    async def scenario():
        async with render_slot():
            def enter():
                with render_slot_sync():
                    acquired.append(True)
            waiting = asyncio.create_task(asyncio.to_thread(enter))
            await asyncio.sleep(.05)
            assert acquired == []
        await asyncio.wait_for(waiting, 1)
    asyncio.run(scenario())
    assert acquired == [True]


def test_flow_prompts_vary_product_motion_and_preserve_reference_labels():
    from app.shop_worker import flow_prompt
    job = {'name': 'สินค้า', 'brief': 'สินค้า', 'current_price': '', 'old_price': ''}
    prompts = [flow_prompt(job, {'id': f'scene-{i}', 'narration': 'สินค้า'}) for i in range(1, 4)]
    assert len(set(prompts)) == 3
    assert any('turntable' in prompt for prompt in prompts)
    assert any('moving soft light' in prompt for prompt in prompts)
    assert all('preserve all existing text and logos' in prompt for prompt in prompts)


def test_obsolete_command_is_finished_instead_of_reclaimed_forever(tmp_path):
    from app.shop_worker import Worker
    store = Store(tmp_path)
    job = store.create_job({'name': 'Product'})
    reference(store, job)
    worker = Worker(store)
    asyncio.run(worker.run_once())
    job = store.get_job(job['id'])
    command = store.request_plan(job['id'], job['revision'])
    store.update_job(job['id'], job['revision'], {'name': 'Changed'})
    asyncio.run(worker.run_once())
    with store._tx() as db:
        saved = store._get(db, 'commands', command['id'])
    assert saved['status'] == 'failed'
    assert asyncio.run(worker.run_once()) is False


def test_edited_youtube_closing_must_agree_with_profile_cta(tmp_path):
    from app.shop_worker import CTA, Worker
    store = Store(tmp_path)
    job = store.create_job({'name': 'สินค้า', 'brief': 'สินค้า 299 399', 'current_price': '299', 'old_price': '399', 'destination': 'youtube'})
    photo = reference(store, job)
    worker = Worker(store)
    asyncio.run(worker.run_once())
    job = store.get_job(job['id'])
    pitch = sample_pitch()
    pitch.update(cta=CTA['youtube'], end_narration='กดลิงก์ในคำอธิบายได้เลยค่ะ', end_spoken='กดลิงก์ในคำอธิบายได้เลยค่ะ')
    scenes = [{**beat, 'id': str(i), 'source': 'real', 'reference_id': photo['id']} for i, beat in enumerate(pitch['beats'])]
    store.save_plan(job['id'], job['revision'], {**pitch, 'scenes': scenes})
    asyncio.run(worker.run_once())
    validated = store.get_job(job['id'])
    assert validated['validated_plan_version'] is None
    assert 'closing' in validated['plan_error']
