"""Durable Shop command worker. No credentials or heavy work enter the web API."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
import uuid
from pathlib import Path

import httpx

from app import characters, shop, shop_render, shop_studio, storyboard, studio, telegram
from app.render_lock import render_slot_sync
from app.shop_affiliate import NO_CLICK_DAYS, Affiliate
from app.shop_media import MediaError, probe
from app.shop_store import Conflict, Store

logger = logging.getLogger(__name__)
CTA = {'shopee': 'กดดูสินค้าในตะกร้า', 'facebook': 'กดลิงก์ในคอมเมนต์', 'youtube': 'ดูลิงก์สินค้าที่หน้าโปรไฟล์'}
MILESTONES = {'plan_ready': 'แผนฉากพร้อมตรวจ', 'waiting': 'รอคลิปจาก Flow', 'ready': 'คลิปพร้อมตรวจ',
              'failed': 'ตัดต่อไม่สำเร็จ', 'no_clicks': f'ยังไม่มีคลิกหลังโพสต์ {NO_CLICK_DAYS} วัน',
              'campaign_ending': 'แคมเปญ affiliate ใกล้หมด'}
ALERT_SCAN_SECONDS = 3600


def factual_brief(job: dict) -> str:
    return shop_render.factual_brief(job)


def as_pitch(job: dict) -> dict:
    return shop_render.pitch_from_plan(job)


SHOT_ACTIONS = (
    ('rotating product display', 'Keep a static camera while a neutral turntable rotates the intact product slowly; do not articulate or open the product.'),
    ('lighting reveal', 'Keep the product and camera static while a moving soft light reveals the existing surface and silhouette, without changing its material or colour.'),
    ('side tracking shot', 'Track the camera gently sideways with shallow depth of field while the product remains motionless on a neutral surface.'),
    ('overhead display', 'Show a controlled overhead camera arc around the intact stationary product on a plain display surface.'),
    ('silhouette reveal', 'Keep the camera static as a neutral backdrop moves behind the stationary product, revealing its unchanged silhouette.'),
    ('context-free hero shot', 'Use a slow camera orbit around the stationary intact product, keeping all visible markings and geometry consistent.'),
)


def flow_prompt(job: dict, scene: dict) -> str:
    # These text-grounded display shots never imply the model inspected an image.
    identity = scene.get('id', 'scene-1').rsplit('-', 1)[-1]
    index = int(identity) - 1 if identity.isdigit() else sum(map(ord, identity))
    purpose, movement = SHOT_ACTIONS[index % len(SHOT_ACTIONS)]
    return ('Create a realistic vertical 9:16 product shot. Use the selected uploaded reference image '
            'as the visual source of truth for product identity, shape, colour, labels and proportions. '
            'No product appearance has been inferred from image analysis. '
            'Only the following user-provided product brief and scene instruction are factual inputs:\n'
            f"Product brief: {factual_brief(job)}\nScene narration (Thai): {scene['narration']}\n"
            f'Shot purpose: {purpose}. {movement} '
            'Use a simple neutral studio setting with soft consistent lighting; keep the entire product visible. '
            'Do not invent components, capabilities, before/after results, performance demonstrations, people or endorsements. '
            'Do not add or alter text or logos; preserve all existing text and logos exactly as in the reference. '
            'No generated subtitles, price tags, watermarks or audio. '
            'The human must confirm that the rendered product matches the selected reference.')


async def character_for(choice: str) -> tuple[str, str, str, dict]:
    """A Studio job's speaker: a library character, or one the model invents (a woman).

    The worker mounts /data read-only, so a translation it makes is used, not
    cached; the bot caches it the first time it plans with that character.
    """
    person = characters.get(choice) if choice and choice != 'auto' else None
    if not person:
        return storyboard.AUTO, '', '', {'choice': 'auto', 'id': '', 'tag': storyboard.AUTO_TAG,
                                         'flow_ready': False}
    english = characters.cached_english(person) or await storyboard.english_character(person['thai'])
    return storyboard.OWN, english, english, {
        'choice': person['id'], 'id': person['id'], 'tag': person['tag'], 'locked': english,
        'flow_ready': person['flow_ready'], 'portrait': storyboard.portrait_prompt(english)}


class Worker:
    def __init__(self, store: Store, *, send=None, lease_seconds=120, heartbeat_seconds=20, notification_backoff=1):
        self.store, self.send = store, send
        self.lease_seconds, self.heartbeat_seconds = lease_seconds, heartbeat_seconds
        self.notification_backoff = notification_backoff

    def _fence(self, command, owner):
        return {'command_id': command['id'], 'owner': owner}

    async def _heartbeat(self, command, owner):
        while True:
            await asyncio.sleep(self.heartbeat_seconds)
            await asyncio.to_thread(self.store.heartbeat, command['id'], owner, lease_seconds=self.lease_seconds)

    async def run_once(self) -> bool:
        # A new random token per claim fences even a restarted process with the same hostname/PID.
        owner = uuid.uuid4().hex
        command = await asyncio.to_thread(self.store.claim_command, owner, lease_seconds=self.lease_seconds)
        if command is None:
            return False
        heartbeat = asyncio.create_task(self._heartbeat(command, owner))
        error = None
        try:
            if command['kind'] == 'notify' and command['attempts'] > 3:
                raise RuntimeError('notification retry limit reached after interrupted delivery')
            handler = getattr(self, command['kind'])
            # ffmpeg, Pillow, filesystem publication and provider async helpers run
            # on a separate event loop in this thread; lease renewal stays responsive.
            await asyncio.to_thread(handler, command, owner)
        except Conflict as exc:
            logger.info('Discarded stale command result %s', command['id'])
            # A superseded revision still owned by us must terminate. If the
            # lease itself was lost, finish_command below will reject the write.
            error = str(exc)[:1500]
        except Exception as exc:
            error = str(exc)[:1500]
            logger.exception('Shop command %s failed', command['id'])
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError, Conflict):
                await heartbeat
        try:
            await asyncio.to_thread(self.store.finish_command, command['id'], owner, error=error,
                                    retry=bool(error and command['kind'] == 'notify' and command['attempts'] < 3))
        except Conflict:
            logger.info('Discarded stale command completion %s', command['id'])
        if error and command['kind'] == 'notify' and command['attempts'] < 3:
            await asyncio.sleep(min(4, self.notification_backoff * 2 ** (command['attempts'] - 1)))
        return True

    async def _studio_plan(self, job, pitch, command):
        """The Pitch as a Storyboard Studio pack (ADR 0018), measured and fitted."""
        script = shop_studio.script_for(pitch)
        work = self.store.media_root / 'work' / f"plan-{command['id']}"
        try:
            spans = await shop_studio.measure(script, work)
            try:
                spans, _ = await shop_studio.fit(script, spans, factual_brief(job), work)
            except Exception:
                # The long lines stand; the page shows each shot's span against its length.
                logger.exception('Studio fit failed; keeping the Pitch lines')
            choice, text, fixed, profile = await character_for(job.get('character') or '')
            board = await shop_studio.plan(script, {'text': factual_brief(job)}, choice,
                                           character=text, fixed_tag=fixed)
            if profile and not profile.get('id'):
                person = board['overview'].get('master_character') or {}
                profile.update(locked=person.get('locked_prompt_tag', ''),
                               portrait=storyboard.portrait_prompt(person.get('locked_prompt_tag', '')))
            return shop_studio.studio_plan(pitch, script, spans, board, profile['tag'], profile,
                                           job['references'])
        finally:
            import shutil
            shutil.rmtree(work, ignore_errors=True)

    def cut_export(self, command, owner):
        """One Storyboard Studio export → each scene's footage and voice, or a refusal."""
        payload = command['payload']
        job = self.store.get_job(payload['job_id'])
        fence = {'command_id': command['id'], 'owner': owner}
        asset = self.store.get_asset(payload['asset_id'], job['id'])
        scenes = (job.get('plan') or {}).get('scenes') or []
        owned = {i: float(scene.get('seconds') or studio.SHOT_SECONDS) for i, scene in enumerate(scenes)}
        expected = sum(owned.values())
        duration = float(asset['metadata'].get('duration') or 0)
        if not payload.get('even') and not studio.fits(duration, expected):
            self.store.set_export_result(job['id'], asset['id'], 'uneven', duration=duration,
                                         expected=expected, **fence)
            return
        work = self.store.media_root / 'work' / f"cut-{command['id']}"
        work.mkdir(parents=True, exist_ok=True)
        try:
            lengths = studio.lengths(list(owned), owned, duration, bool(payload.get('even')))
            pieces = [(lengths[i], work / f"{scene['id']}.mp4", work / f"{scene['id']}.wav")
                      for i, scene in enumerate(scenes)]
            with render_slot_sync():
                studio.cut_file(self.store.asset_path(asset['id']), pieces)
            cuts = [(scene['id'], (video, probe(video)), (voice, {'duration': lengths[i]}))
                    for i, (scene, (_, video, voice)) in enumerate(zip(scenes, pieces))]
            self.store.set_export_result(job['id'], asset['id'], 'cut', duration=duration,
                                         expected=expected, cuts=cuts, **fence)
        except (RuntimeError, MediaError) as exc:
            self.store.set_export_result(job['id'], asset['id'], 'failed', duration=duration,
                                         expected=expected, error=str(exc)[:500], **fence)
        finally:
            import shutil
            shutil.rmtree(work, ignore_errors=True)

    def probe_asset(self, command, owner):
        asset = self.store.get_asset(command['payload']['asset_id'])
        try:
            metadata = probe(self.store.asset_path(asset['id']), reference=asset['kind'] == 'reference')
        except MediaError as exc:
            self.store.validate_asset(asset['id'], {}, valid=False, error=str(exc), **self._fence(command, owner))
            return
        self.store.validate_asset(asset['id'], metadata, valid=True, **self._fence(command, owner))

    def generate_plan(self, command, owner):
        payload = command['payload']
        job = self.store.get_job(payload['job_id'])
        if job['revision'] != payload['revision']:
            raise Conflict('job changed before generation')
        refs = [self.store.get_asset(identity) for identity in job['references']]
        if not refs or any(asset['validation'] != 'valid' for asset in refs):
            raise MediaError('reference photos must pass validation before generation')
        pitch = asyncio.run(shop.generate(factual_brief(job), len(refs)))
        # Legacy generation uses a generic end card. The workspace targets one destination.
        cta = CTA[job['destination']]
        pitch.update(cta=cta, end_narration=cta + 'ได้เลยค่ะ', end_spoken=cta + 'ได้เลยค่ะ')
        if job.get('mode') == 'studio':
            plan = asyncio.run(self._studio_plan(job, pitch, command))
            self.store.save_plan(job['id'], payload['revision'], plan, **self._fence(command, owner))
            return
        scenes = []
        for i, beat in enumerate(pitch['beats'], 1):
            scene = {**beat, 'id': f'scene-{i}', 'source': 'flow', 'reference_id': job['references'][beat['photo'] - 1],
                     'fit': 'crop', 'required_duration': 0, 'purpose': SHOT_ACTIONS[(i - 1) % len(SHOT_ACTIONS)][0]}
            scene['flow_prompt'] = flow_prompt(job, scene)
            scenes.append(scene)
        self.store.save_plan(job['id'], payload['revision'], {**pitch, 'scenes': scenes}, **self._fence(command, owner))

    def validate_plan(self, command, owner):
        payload = command['payload']
        job = self.store.get_job(payload['job_id'])
        if job['plan_version'] != payload['plan_version']:
            raise Conflict('plan changed before validation')
        try:
            plan = shop_render.canonical_plan(job)
            expected = CTA[job['destination']]
            if plan.get('cta') != expected:
                raise shop.PitchError('CTA does not match destination')
            other_targets = {'shopee': 'ตะกร้า', 'facebook': 'คอมเมนต์', 'youtube': 'โปรไฟล์'}
            prohibited = ['คำอธิบาย', *[word for target, word in other_targets.items() if target != job['destination']]]
            for field in ('end_narration', 'end_spoken'):
                ending = plan[field]
                if expected not in ending or any(word in ending for word in prohibited):
                    raise shop.PitchError('spoken closing must match the destination CTA')
            for scene in plan['scenes']:
                if scene['source'] == 'flow' and (not isinstance(scene.get('flow_prompt'), str) or not scene['flow_prompt'].strip()):
                    raise shop.PitchError(f'scene {scene["id"]}: Flow prompt is required')
            valid, error = True, None
        except (ValueError, KeyError, TypeError) as exc:
            valid, error = False, str(exc)
        self.store.validate_plan(job['id'], payload['plan_version'], valid=valid, error=error, **self._fence(command, owner))
        if valid:
            self.store.notify(job['id'], 'plan_ready', f'plan-{payload["plan_version"]}', **self._fence(command, owner))

    def render(self, command, owner):
        render_id = command['payload']['render_id']
        frozen = self.store.get_render(render_id)
        # Recovery after success committed but before command completion.
        if frozen['status'] in {'ready', 'failed'}:
            return
        fence = self._fence(command, owner)
        self.store.set_render_result(render_id, 'running', **fence)
        try:
            with render_slot_sync():
                self.store.heartbeat(command['id'], owner, lease_seconds=self.lease_seconds)
                relative = Path('renders') / render_id / owner
                output = self.store.media_root / relative
                output.mkdir(parents=True, exist_ok=True)
                snapshot = {**frozen['snapshot'], 'plan': shop_render.canonical_plan(frozen['snapshot'])}
                video, details = asyncio.run(shop_render.build_snapshot(snapshot, self.store.media_root, output / 'work'))
                # Private attempt paths mean a stale process cannot replace another claim's files.
                (output / 'caption.txt.tmp').write_text(shop.caption_text(snapshot['plan'], snapshot.get('affiliate_link')), encoding='utf-8')
                (output / 'details.json.tmp').write_text(json.dumps(details, ensure_ascii=False), encoding='utf-8')
                self.store.heartbeat(command['id'], owner, lease_seconds=self.lease_seconds)
                os.replace(video, output / 'final.mp4')
                os.replace(output / 'caption.txt.tmp', output / 'caption.txt')
                os.replace(output / 'details.json.tmp', output / 'details.json')
                self.store.set_render_result(render_id, 'ready', outputs={'video': str(relative / 'final.mp4'),
                                             'caption': str(relative / 'caption.txt'), 'details': str(relative / 'details.json')}, **fence)
        except Conflict:
            raise
        except Exception as exc:
            self.store.set_render_result(render_id, 'failed', error=str(exc)[:1500], **fence)
            self.store.notify(frozen['job_id'], 'failed', render_id, render_id=render_id, **fence)
            raise
        self.store.notify(frozen['job_id'], 'ready', render_id, render_id=render_id, **fence)

    def notify(self, command, owner):
        payload = command['payload']
        job = self.store.get_job(payload['job_id'])
        url = os.environ.get('SHOP_PUBLIC_URL', '').rstrip('/')
        text = f"🛍 {job['name']}: {MILESTONES.get(payload['milestone'], payload['milestone'])}"
        if payload.get('detail'):
            text += f"\n{payload['detail']}"
        if url:
            text += f"\n{url}/shop/{job['id']}"
        self.store.heartbeat(command['id'], owner, lease_seconds=self.lease_seconds)
        async def deliver():
            if self.send:
                await self.send(text)
            else:
                async with httpx.AsyncClient() as client:
                    result = await telegram.Bot.from_env(client).say(text)
                    if result is None:
                        raise RuntimeError('Telegram delivery failed')
        asyncio.run(deliver())


async def serve():
    store = Store(Path(os.environ.get('SHOP_ROOT', '/shop-data')),
                  Path(os.environ.get('SHOP_MEDIA_ROOT', '/output/shop-studio')))
    worker = Worker(store)
    affiliate = Affiliate(store)
    scanned = None
    while True:
        if scanned is None or time.monotonic() - scanned >= ALERT_SCAN_SECONDS:
            scanned = time.monotonic()
            try:
                await asyncio.to_thread(affiliate.enqueue_alerts)
            except Exception:
                logger.exception('Affiliate alert scan failed')
        try:
            if not await worker.run_once():
                await asyncio.sleep(1)
        except Exception:
            logger.exception('Shop worker loop failed')
            await asyncio.sleep(1)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve())
