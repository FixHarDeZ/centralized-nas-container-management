"""Voicing a Chapter with Google Cloud Text-to-Speech.

Plain `synthesize`, many small calls, joined here — see docs/adr/0012 for why
`synthesizeLongAudio` is not used. Chirp 3: HD accepts no SSML and, for `th-th`
specifically, no `custom_pronunciations`, so a mispronounced word can only be
fixed by changing the text that is sent. That is what `say.json` is for, and it
is applied **here and nowhere else**: shorts-factory learned that substituting
earlier, where the text is also used for something else, silently desynchronises
the two copies.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path

from . import chunking, config, render


def write_credentials() -> None:
    """Materialise the service account from the vault-held base64 blob.

    The JSON is stored base64-encoded because `scripts/render_env.py` refuses to
    emit a newline into a `.env` file, and a service-account key is multiline.
    """
    blob = os.environ.get("GOOGLE_CREDENTIALS_B64", "").strip()
    if not blob:
        return
    path = config.data_dir() / "google-credentials.json"
    path.write_bytes(base64.b64decode(blob))
    path.chmod(0o600)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(path)


def load_say() -> dict[str, str]:
    path = config.data_dir() / "say.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _speakable(text: str) -> str:
    """The only place substitutions are applied."""
    for wrong, right in load_say().items():
        text = text.replace(wrong, right)
    return text


def _synthesize(text: str, dest: Path) -> Path:
    from google.cloud import texttospeech

    client = texttospeech.TextToSpeechClient()
    response = client.synthesize_speech(
        input=texttospeech.SynthesisInput(text=text),
        voice=texttospeech.VoiceSelectionParams(
            language_code=config.tts_language_code(),
            name=config.tts_voice(),
        ),
        audio_config=texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            # UNVERIFIED on Chirp 3: HD — two Google doc pages disagree about
            # whether it is honoured. Left at 1.0 until someone fires the API.
            speaking_rate=config.tts_speaking_rate(),
        ),
    )
    dest.write_bytes(response.audio_content)
    return dest


async def _trim(src: Path, dest: Path) -> Path:
    """Cut leading and trailing silence, leaving JOIN_SILENCE behind.

    This half of shorts-factory's `tighten()` transfers directly. The other half
    — reconciling reported sentence offsets against the file — does not: that
    existed because edge-tts returns one blob with offsets that overstate the
    real positions, and here every chunk is already its own file.
    """
    pad = config.join_silence()
    await render.ffmpeg(
        "-i", str(src),
        "-af",
        (
            "silenceremove="
            "start_periods=1:start_silence=0:start_threshold=-50dB:"
            "detection=peak,"
            "areverse,"
            "silenceremove="
            f"start_periods=1:start_silence={pad}:start_threshold=-50dB:"
            "detection=peak,"
            "areverse"
        ),
        str(dest),
    )
    return dest


async def voice_chapter(text: str, dest: Path, scratch: Path) -> float:
    """Voice one Chapter into a single file. Returns its measured duration.

    The duration is read back from the finished file, never accumulated from
    what the API reported, because the timestamps in the description are built
    from these numbers.

    `scratch` receives the per-request files and is NOT cleaned up: the raw,
    untrimmed chunks are the only evidence for the one question that can
    reverse docs/adr/0012 — whether the seams are audible — and a temp dir
    deleted them before anyone could listen. The workdir owner prunes.

    Off the event loop throughout: the Google call runs in a thread, the trims
    are asyncio subprocesses. A blocking version froze the poll loop for the
    length of every request, ~20 times a Story.
    """
    chunks = chunking.split(_speakable(text), config.max_request_bytes())
    if any(chunk.forced for chunk in chunks):
        # Loud on purpose: it means the model produced an unbroken run longer
        # than the request cap and a Thai word may have been cut in half.
        raise ValueError(
            "no sentence boundary within the request cap — the Chapter has an "
            "unbroken run over 5,000 bytes and would be cut mid-word",
        )

    scratch.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    for index, chunk in enumerate(chunks):
        raw = await asyncio.to_thread(_synthesize, chunk.text, scratch / f"{index:03d}.raw.wav")
        parts.append(await _trim(raw, scratch / f"{index:03d}.wav"))

    await render.concat(parts, dest)
    return render.probe_duration(dest)
