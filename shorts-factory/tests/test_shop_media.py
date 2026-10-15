import subprocess

import pytest
from PIL import Image


def test_probe_rejects_corrupt_and_oversized_images(tmp_path):
    from app.shop_media import MediaError, probe
    broken = tmp_path / 'broken.png'
    broken.write_bytes(b'not an image')
    with pytest.raises(MediaError):
        probe(broken, reference=True)
    wide = tmp_path / 'wide.png'
    Image.new('RGB', (9000, 64)).save(wide)
    with pytest.raises(MediaError, match='dimensions'):
        probe(wide, reference=True)


def test_video_probe_decodes_and_rejects_video_reference(tmp_path):
    from app.shop_media import MediaError, probe
    clip = tmp_path / 'source.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=red:s=160x120:d=0.5', '-c:v', 'libx264', '-threads', '2', str(clip)], check=True)
    info = probe(clip)
    assert info['type'] == 'video'
    assert info['width'] == 160
    assert 0.4 < info['duration'] < 0.7
    with pytest.raises(MediaError):
        probe(clip, reference=True)


def test_video_segment_rejects_short_source_and_strips_audio(tmp_path, monkeypatch):
    from app import shop_render
    from app.shop_media import MediaError, probe
    source = tmp_path / 'source.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=red:s=160x120:d=0.5', '-f', 'lavfi', '-i', 'sine=frequency=800:duration=0.5', '-c:v', 'libx264', '-threads', '2', '-c:a', 'aac', str(source)], check=True)
    overlay = tmp_path / 'text.png'
    Image.new('RGBA', (180, 320)).save(overlay)
    monkeypatch.setattr(shop_render, 'W', 180)
    monkeypatch.setattr(shop_render, 'H', 320)
    with pytest.raises(MediaError, match=r'scene one.*short'):
        shop_render.video_segment(source, overlay, 1, tmp_path / 'bad.mp4', fit='crop', scene_id='one')
    for fit in ('crop', 'contain'):
        out = tmp_path / f'{fit}.mp4'
        shop_render.video_segment(source, overlay, .4, out, fit=fit, scene_id='one')
        info = probe(out)
        assert [info['width'], info['height']] == [180, 320]
        assert info['has_audio'] is False


def test_frozen_snapshot_renders_real_video_with_measured_narration(tmp_path, monkeypatch):
    import asyncio
    from pathlib import Path

    from app import render, shop_render
    from PIL import features
    if not features.check('raqm'):
        pytest.skip('Raqm unavailable; full render runs in the production image')
    from app.shop_media import probe
    font = Path('/System/Library/Fonts/Supplemental/Arial Unicode.ttf')
    if font.exists():
        monkeypatch.setattr(render, 'THAI_BOLD', str(font))
    elif not Path(render.THAI_BOLD).exists():
        pytest.skip('Thai rendering font unavailable')
    root = tmp_path / 'media'
    assets = root / 'assets'
    assets.mkdir(parents=True)
    photo = assets / 'reference.png'
    Image.new('RGB', (160, 200), 'blue').save(photo)
    video = assets / 'source.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=red:s=160x120:d=0.5', '-c:v', 'libx264', '-threads', '2', str(video)], check=True)
    async def narration(cards, workdir, **kwargs):
        audio = workdir / 'tts.wav'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=mono', '-t', '0.8', str(audio)], check=True)
        return audio, [0, .2, .4, .6]
    monkeypatch.setattr(render, '_narration_track', narration)
    monkeypatch.setattr(render, 'TAIL_PAD', 0)
    monkeypatch.setattr(render, 'pick_music', lambda: None)
    scene = {'narration': 'สินค้า', 'spoken': 'สินค้า', 'lines': ['สินค้า'], 'badge': 'สินค้า',
             'source': 'real', 'reference_id': 'photo', 'media_id': 'video', 'fit': 'contain'}
    snapshot = {'name': 'สินค้า', 'brief': 'สินค้า 299', 'current_price': '299', 'old_price': '',
                'references': ['photo'], 'plan': {'title': 'สินค้า', 'caption': 'สินค้า', 'hashtags': ['#สินค้า'],
                          'scenes': [{**scene, 'id': str(i)} for i in range(3)],
                          'end_badge': 'ดูสินค้า', 'end_narration': 'ดูสินค้า', 'end_spoken': 'ดูสินค้า',
                          'price': '299', 'old_price': '', 'cta': 'กดลิงก์ในคำอธิบาย'},
                'assets': {'photo': {'key': 'reference.png', 'validation': 'valid'},
                           'video': {'key': 'source.mp4', 'validation': 'valid'}}}
    clip, details = asyncio.run(shop_render.build_snapshot(snapshot, root, tmp_path / 'work'))
    info = probe(clip)
    assert [info['width'], info['height']] == [1080, 1920]
    assert info['has_audio']
    assert .7 <= info['duration'] <= 1
    assert len(details['scenes']) == 3


@pytest.mark.parametrize(('width', 'height', 'duration', 'valid'), [
    (3840, 2160, 60, True), (2160, 3840, 60, True),
    (3842, 2160, 1, False), (3000, 2700, 1, False), (160, 120, 60.1, False),
])
def test_video_limits_match_approved_dimensions_and_duration(tmp_path, monkeypatch, width, height, duration, valid):
    import json

    from app import shop_media
    path = tmp_path / 'source.mp4'
    path.write_bytes(b'video')
    metadata = {'streams': [{'codec_type': 'video', 'codec_name': 'h264', 'width': width, 'height': height,
                             'duration': duration, 'avg_frame_rate': '30/1'}], 'format': {'format_name': 'mov,mp4'}}
    monkeypatch.setattr(shop_media, 'run', lambda args, **kwargs: json.dumps(metadata))
    if valid:
        assert shop_media.probe(path)['duration'] == duration
    else:
        with pytest.raises(shop_media.MediaError):
            shop_media.probe(path)


def test_renderer_rejects_narration_over_sixty_seconds_before_encoding(tmp_path, monkeypatch):
    import asyncio

    from app import render, shop_render
    from app.shop_media import MediaError
    async def narration(*args, **kwargs):
        return tmp_path / 'tts.wav', [0, 25, 50, 75]
    monkeypatch.setattr(render, '_narration_track', narration)
    monkeypatch.setattr(render, 'audio_seconds', lambda path: 100)
    monkeypatch.setattr(shop_render, 'canonical_plan', lambda snapshot: snapshot['plan'])
    snapshot = {'plan': {'scenes': [{'source': 'real', 'narration': 'สินค้า'} for _ in range(3)],
                          'end_narration': 'สินค้า'}, 'assets': {}}
    with pytest.raises(MediaError, match=r'narration.*60'):
        asyncio.run(shop_render.build_snapshot(snapshot, tmp_path, tmp_path / 'work'))


def test_all_legacy_render_subprocess_stages_are_bounded(monkeypatch, tmp_path):
    from app import render
    calls = []
    def hung(args, **kwargs):
        calls.append((args, kwargs))
        assert kwargs.get('timeout') in {30, 1800}
        raise subprocess.TimeoutExpired(args, kwargs['timeout'])
    monkeypatch.setattr(render.subprocess, 'run', hung)
    with pytest.raises(RuntimeError, match='timed out'):
        render._run(['ffmpeg', '-version'])
    with pytest.raises(RuntimeError, match='timed out'):
        render.audio_seconds(tmp_path / 'audio.wav')
    assert [kwargs['timeout'] for args, kwargs in calls] == [1800, 30]


def test_canonical_plan_normalizes_render_text_prices_and_preserves_media_mapping():
    from app import shop_render
    narration = 'สินค้าน่าใช้ค่ะ'
    scene = {'id': 'stable', 'source': 'real', 'media_id': 'clip', 'reference_id': 'photo', 'fit': 'contain',
             'badge': ' สินค้า ', 'narration': f' {narration} ', 'spoken': f' {narration} ',
             'lines': ['', f' {narration} ', '   ']}
    job = {'name': 'สินค้า', 'brief': 'สินค้า 299 399', 'current_price': '299', 'old_price': '399', 'references': ['photo'],
           'plan': {'title': ' สินค้า ', 'caption': ' สินค้า ', 'hashtags': ['#สินค้า'], 'price': '฿299', 'old_price': '฿399',
                    'end_badge': ' ดูสินค้า ', 'end_narration': ' ดูสินค้าได้เลยค่ะ ', 'end_spoken': ' ดูสินค้าได้เลยค่ะ ',
                    'cta': 'custom metadata', 'scenes': [{**scene, 'id': str(i)} for i in range(3)]}}
    canonical = shop_render.canonical_plan(job)
    assert canonical['price'] == '299'
    assert canonical['old_price'] == '399'
    assert canonical['title'] == 'สินค้า'
    assert canonical['cta'] == 'custom metadata'
    for i, cleaned in enumerate(canonical['scenes']):
        assert cleaned['lines'] == [narration]
        assert cleaned['narration'] == narration
        assert cleaned['badge'] == 'สินค้า'
        assert cleaned['id'] == str(i)
        assert cleaned['media_id'] == 'clip'
        assert cleaned['reference_id'] == 'photo'
        assert cleaned['fit'] == 'contain'
    assert job['plan']['scenes'][0]['lines'][0] == ''  # Frozen input stays immutable.


def test_snapshot_pipeline_uses_validated_values_for_speech_overlays_and_price(tmp_path, monkeypatch):
    import asyncio

    from app import render, shop_render
    narration = 'สินค้าน่าใช้ค่ะ'
    scene = {'source': 'real', 'media_id': 'video', 'reference_id': 'photo', 'fit': 'contain',
             'badge': ' สินค้า ', 'narration': f' {narration} ', 'spoken': f' {narration} ',
             'lines': ['', f' {narration} ', '   ']}
    snapshot = {'name': 'สินค้า', 'brief': 'สินค้า 299', 'current_price': '299', 'old_price': '', 'references': ['photo'],
                'plan': {'title': 'สินค้า', 'caption': 'สินค้า', 'hashtags': ['#สินค้า'], 'price': '฿299', 'old_price': '',
                         'end_badge': ' ดูสินค้า ', 'end_narration': ' ดูสินค้าได้เลยค่ะ ', 'end_spoken': ' ดูสินค้าได้เลยค่ะ ',
                         'scenes': [{**scene, 'id': str(i)} for i in range(3)]},
                'assets': {'photo': {'validation': 'valid', 'key': 'ref.png'}, 'video': {'validation': 'valid', 'key': 'clip.mp4'}}}
    spoken, overlays, endings = [], [], []
    async def narration_track(cards, workdir, **kwargs):
        spoken.extend(cards)
        return workdir / 'audio.wav', [0, .2, .4, .6]
    def text_layer(beat, out):
        overlays.append(beat)
        return out
    def end_layer(plan, out):
        endings.append(plan)
        return out
    from app import shop_media
    monkeypatch.setattr(shop_media, 'probe', lambda path: {'type': 'video'})
    monkeypatch.setattr(render, '_narration_track', narration_track)
    monkeypatch.setattr(render, 'audio_seconds', lambda path: .8)
    monkeypatch.setattr(render, 'TAIL_PAD', 0)
    monkeypatch.setattr(render, 'pick_music', lambda: None)
    monkeypatch.setattr(render, 'concat', lambda segments, out: out)
    monkeypatch.setattr(render, 'mux', lambda video, audio, out, music: out)
    monkeypatch.setattr(shop_render, 'photo_layer', lambda source, out, *args: out)
    monkeypatch.setattr(shop_render, 'text_layer', text_layer)
    monkeypatch.setattr(shop_render, 'end_layer', end_layer)
    monkeypatch.setattr(shop_render, 'video_segment', lambda source, text, seconds, out, **kwargs: out)
    monkeypatch.setattr(shop_render, 'segment', lambda source, text, seconds, out, **kwargs: out)
    asyncio.run(shop_render.build_snapshot(snapshot, tmp_path, tmp_path / 'work'))
    assert spoken[0] == {'narration': narration, 'spoken': narration}
    assert overlays[0] == {'badge': 'สินค้า', 'lines': [narration]}
    assert endings[0]['price'] == '299'
    assert endings[0]['end_badge'] == 'ดูสินค้า'
    assert [scene['id'] for scene in endings[0]['scenes']] == ['0', '1', '2']
