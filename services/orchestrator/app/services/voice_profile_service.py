"""Service layer for managing local voice profile enrollment.

Enrollment pipeline:
  1. start_enrollment()         – sukuria arba nustatyta iš naujo profilį
  2. add_enrollment_sample() x3 – išsaugo audio mėginius ir apskaičiuoja jų fingerprints
  3. finish_enrollment()        – sujungia fingerprints į vieną vidurkį ir išsaugo DB

Speaker verification naudoja MFCC-based cosine similarity (audio_fingerprint.py).
"""

import os
import uuid
import json
import datetime
import logging
import importlib
from types import ModuleType
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.voice_profile import VoiceProfile

log = logging.getLogger(__name__)

# Optional dependency cache for numpy-backed audio biometrics.
_AUDIO_FP_MODULE: Optional[ModuleType] = None
_AUDIO_FP_IMPORT_ERROR: Optional[ModuleNotFoundError] = None
_AUDIO_FP_WARNING_EMITTED = False

VOICE_DATA_DIR = os.path.join("./data", "voice_samples")
os.makedirs(VOICE_DATA_DIR, exist_ok=True)


def _load_audio_fingerprint_module() -> tuple[Optional[ModuleType], Optional[ModuleNotFoundError]]:
    """Lazy-load the optional numpy-backed audio fingerprint module.

    Missing optional dependencies (for example numpy) should not break app startup.
    """
    global _AUDIO_FP_MODULE, _AUDIO_FP_IMPORT_ERROR, _AUDIO_FP_WARNING_EMITTED

    if _AUDIO_FP_MODULE is not None:
        return _AUDIO_FP_MODULE, None
    if _AUDIO_FP_IMPORT_ERROR is not None:
        return None, _AUDIO_FP_IMPORT_ERROR

    try:
        _AUDIO_FP_MODULE = importlib.import_module("app.services.audio_fingerprint")
        return _AUDIO_FP_MODULE, None
    except ModuleNotFoundError as exc:
        # Only treat optional dependency absence as degraded mode.
        if exc.name not in {"numpy", "app.services.audio_fingerprint"}:
            raise
        _AUDIO_FP_IMPORT_ERROR = exc
        if not _AUDIO_FP_WARNING_EMITTED:
            _AUDIO_FP_WARNING_EMITTED = True
            log.warning(
                "Voice biometrics unavailable: missing optional dependency '%s'. "
                "Install voice extras to enable speaker verification.",
                exc.name,
            )
        return None, exc


def get_voice_biometrics_availability() -> dict[str, Any]:
    """Return availability metadata for optional voice biometrics capability."""
    module, err = _load_audio_fingerprint_module()
    if module is not None:
        return {
            "capability_name": "voice_biometrics",
            "available": True,
            "reason_if_unavailable": None,
        }

    missing = err.name if err is not None else "unknown"
    return {
        "capability_name": "voice_biometrics",
        "available": False,
        "reason_if_unavailable": f"missing optional dependency: {missing}",
    }


def _require_audio_fingerprint_module() -> ModuleType:
    module, err = _load_audio_fingerprint_module()
    if module is not None:
        return module
    missing = err.name if err is not None else "unknown"
    raise RuntimeError(
        f"Voice biometrics unavailable: missing optional dependency '{missing}'."
    )


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


async def start_enrollment(db: AsyncSession, profile_name: str = "Primary") -> VoiceProfile:
    """Sukuria arba nustatyta iš naujo voice profile enrollment."""
    existing = await db.execute(select(VoiceProfile))
    rows = existing.scalars().all()
    for profile_row in rows:
        await db.delete(profile_row)
    await db.flush()
    profile = VoiceProfile(
        profile_name=profile_name,
        owner_label="owner",
        enrollment_status="enrolling",
        sample_count=0,
        samples_json="[]",
        fingerprint_json=None,
        version=1,
        verification_enabled=False,
    )
    db.add(profile)
    await db.flush()
    return profile


async def add_enrollment_sample(db: AsyncSession, profile_id: int, audio_bytes: bytes) -> str:
    """Išsaugo enrollment audio mėginį ir atnaujina profilio metaduomenis."""
    profile = await db.get(VoiceProfile, profile_id)
    if not profile:
        raise ValueError("voice profile not found")

    filename = f"sample_{profile_id}_{uuid.uuid4().hex}.webm"
    path = os.path.join(VOICE_DATA_DIR, filename)
    with open(path, "wb") as fh:
        fh.write(audio_bytes)

    samples = profile.sample_paths()
    samples.append(path)
    profile.samples_json = json.dumps(samples)
    profile.sample_count = len(samples)
    profile.updated_at = _utcnow()
    await db.flush()
    return path


async def finish_enrollment(db: AsyncSession, profile_id: int) -> VoiceProfile:
    """Baigia enrollment: apskaičiuoja ir išsaugo voice fingerprint.

    Reikia bent 3 mėginių. Fingerprint = vidurkis iš visų mėginių MFCC vektorių.
    """
    profile = await db.get(VoiceProfile, profile_id)
    if not profile:
        raise ValueError("voice profile not found")

    if profile.sample_count < 3:
        profile.enrollment_status = "enrollment_incomplete"
        profile.updated_at = _utcnow()
        await db.flush()
        return profile

    # Apskaičiuojame fingerprint iš visų enrollment mėginių
    audio_fp = _require_audio_fingerprint_module()
    fingerprints = []
    for sample_path in profile.sample_paths():
        try:
            with open(sample_path, "rb") as f:
                audio_bytes = f.read()
            fp = audio_fp.compute_fingerprint(audio_bytes)
            fingerprints.append(fp)
        except Exception:
            pass  # Praleisti sugadintus failus

    if not fingerprints:
        profile.enrollment_status = "enrollment_incomplete"
        await db.flush()
        return profile

    # Sujungiame į vieną vidurkį
    combined = audio_fp.combine_fingerprints(fingerprints)
    profile.fingerprint_json = audio_fp.fingerprint_to_json(combined)
    profile.enrollment_status = "enrolled"
    profile.verification_enabled = True
    profile.updated_at = _utcnow()
    await db.flush()
    return profile


async def get_voice_profile(db: AsyncSession) -> Optional[VoiceProfile]:
    result = await db.execute(select(VoiceProfile).order_by(VoiceProfile.id).limit(1))
    return result.scalar_one_or_none()


async def get_enrolled_fingerprint(db: AsyncSession) -> tuple[Any | None, float | None, str | None]:
    """Grąžina (fingerprint, threshold, unavailable_reason)."""
    availability = get_voice_biometrics_availability()
    if not availability["available"]:
        return None, None, str(availability["reason_if_unavailable"])

    profile = await get_voice_profile(db)
    if not profile or not profile.fingerprint_json:
        return None, None, None

    audio_fp = _require_audio_fingerprint_module()
    fp = audio_fp.fingerprint_from_json(profile.fingerprint_json)
    threshold = profile.verification_threshold  # gali būti None
    return fp, threshold, None


async def delete_voice_profile(db: AsyncSession) -> None:
    profile = await get_voice_profile(db)
    if not profile:
        return
    for p in profile.sample_paths():
        try:
            os.remove(p)
        except Exception:
            pass
    await db.delete(profile)
    await db.flush()

