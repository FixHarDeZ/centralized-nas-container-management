"""Bounded content validation for untrusted Shop uploads."""
from __future__ import annotations

import json
import math
import subprocess
import warnings
from pathlib import Path

from PIL import Image, ImageOps

# A 7-shot pack of 10 s shots is 70 s; room for hand trims and a longer one.
EXPORT_SECONDS = 180


class MediaError(ValueError):
    pass


def run(args: list[str], *, timeout: int = 1800) -> str:
    try:
        result = subprocess.run(args, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MediaError(f'media command failed: {exc}') from exc
    if result.returncode:
        raise MediaError(result.stderr.decode(errors='replace')[-1500:] or 'media command failed')
    if len(result.stdout) > 1024 * 1024:
        raise MediaError('media metadata too large')
    return result.stdout.decode(errors='replace')


def _dimensions(width, height, *, video=False):
    maximum = 3840 if video else 8192
    if not 64 <= width <= maximum or not 64 <= height <= maximum or width * height > 40_000_000:
        raise MediaError('unsupported media dimensions')
    if video and min(width, height) > 2160:
        raise MediaError('unsupported media dimensions: maximum 3840x2160 or portrait')


def probe(path: Path, *, reference: bool = False, export: bool = False) -> dict:
    """`export`: a whole Storyboard Studio export (ADR 0018), up to EXPORT_SECONDS
    long and with the character's voice in it; a scene clip stays within 60 s."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        raise MediaError('empty or missing media')
    if path.suffix.lower() in {'.jpg', '.jpeg', '.png', '.webp'}:
        if path.stat().st_size > 15 * 1024 * 1024:
            raise MediaError('image exceeds size limit')
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(path) as img:
                    if img.format not in {'JPEG', 'PNG', 'WEBP'} or getattr(img, 'n_frames', 1) != 1:
                        raise MediaError('unsupported or animated image')
                    _dimensions(*img.size)
                    img.verify()
                with Image.open(path) as img:
                    img.load()
                    width, height = ImageOps.exif_transpose(img).size
        except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise MediaError(f'invalid image: {exc}') from exc
        return {'type': 'image', 'width': width, 'height': height, 'duration': 0, 'has_audio': False}
    if reference or path.suffix.lower() not in {'.mp4', '.mov'}:
        raise MediaError('expected a product image' if reference else 'unsupported media type')
    if path.stat().st_size > 100 * 1024 * 1024:
        raise MediaError('video exceeds size limit')
    try:
        data = json.loads(run(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe', '-show_streams', '-show_format', '-of', 'json', str(path)], timeout=15))
        streams = data['streams']
        videos = [stream for stream in streams if stream['codec_type'] == 'video']
        if len(videos) != 1 or any(stream['codec_type'] not in {'video', 'audio'} for stream in streams):
            raise MediaError('video must have one video stream and optional audio only')
        video = videos[0]
        if video.get('disposition', {}).get('attached_pic') or video.get('codec_name') not in {'h264', 'hevc', 'vp9', 'av1', 'mpeg4', 'prores'}:
            raise MediaError('unsupported video codec')
        if not set(data['format']['format_name'].split(',')) & {'mov', 'mp4', 'm4a', '3gp', '3g2', 'mj2'}:
            raise MediaError('unsupported video container')
        width, height = int(video['width']), int(video['height'])
        _dimensions(width, height, video=True)
        duration = float(video.get('duration') or data['format']['duration'])
        numerator, denominator = video['avg_frame_rate'].split('/')
        fps = float(numerator) / float(denominator)
        longest = EXPORT_SECONDS if export else 60
        if not math.isfinite(duration) or not .1 <= duration <= longest or not 1 <= fps <= 60:
            raise MediaError('unsupported video duration or frame rate')
        if export and not any(stream['codec_type'] == 'audio' for stream in streams):
            raise MediaError('export has no audio: export from Scenes with the character speaking')
        # Decode the complete bounded source, catching truncated/corrupt frames.
        run(['ffmpeg', '-v', 'error', '-xerror', '-threads', '2', '-protocol_whitelist', 'file,pipe', '-i', str(path), '-map', '0:v:0', '-an', '-f', 'null', '-'], timeout=300 if export else 60)
        return {'type': 'video', 'width': width, 'height': height, 'duration': duration, 'fps': fps,
                'has_audio': any(stream['codec_type'] == 'audio' for stream in streams)}
    except (KeyError, ValueError, TypeError, ZeroDivisionError) as exc:
        if isinstance(exc, MediaError):
            raise
        raise MediaError(f'invalid video metadata: {exc}') from exc
