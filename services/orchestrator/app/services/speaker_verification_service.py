"""Garso kalbėtojo verifikacija naudojant MFCC cosine similarity.

Pakeičia placeholder implementaciją realiu MFCC-based fingerprint palyginimu.

Naudojimas:
    result = await verify_speaker(db, audio_bytes)
    if result["status"] == "success":
        # Balsas atpažintas kaip savininko balsas
    elif result["status"] == "blocked":
        # Nepažįstamas balsas — atmesti komandą
    elif result["status"] == "no_profile":
        # Nėra enrollment – leidžiame (verifikacija neaktyvuota)
"""

import datetime
import logging
from typing import Dict

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.settings import UserSettings
from app.services.voice_profile_service import get_enrolled_fingerprint

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD = 0.72


async def _load_security_mode(db: AsyncSession) -> str:
    """Best-effort read of security_mode; defaults to normal."""
    try:
        row = await db.execute(select(UserSettings).where(UserSettings.id == 1))
        settings = row.scalar_one_or_none()
        if settings is None:
            return "normal"
        return getattr(settings, "security_mode", "normal") or "normal"
    except Exception:
        return "normal"


async def verify_speaker(db: AsyncSession, audio_bytes: bytes) -> Dict:
    """Palygina audio su užregistruotu balso profiliu.

    Grąžina dict su laukais:
        status:     'success' | 'blocked' | 'no_profile' | 'disabled' | 'error'
        similarity: float (0.0 – 1.0)
        threshold:  float
        message:    str (lietuviškas aprašymas)
    """
    # 1. Gauname enrollment fingerprint iš DB
    try:
        enrolled_fp, custom_threshold, unavailable_reason = await get_enrolled_fingerprint(db)
    except Exception as exc:
        logger.error("Nepavyko gauti voice profile: %s", exc)
        return {
            "status": "error",
            "reason": "speaker_profile_lookup_failed",
            "similarity": 0.0,
            "threshold": DEFAULT_THRESHOLD,
            "message": "Vidinė klaida tikrinant balsą.",
        }

    # Optional dependency unavailable: explicit degraded mode.
    if unavailable_reason:
        security_mode = await _load_security_mode(db)
        if security_mode == "strict":
            return {
                "status": "blocked",
                "reason": "voice_biometrics_unavailable",
                "similarity": 0.0,
                "threshold": DEFAULT_THRESHOLD,
                "message": (
                    "Balso biometrika nepasiekiama šioje aplinkoje. "
                    "Strict režime reikalingas rankinis patvirtinimas."
                ),
            }
        return {
            "status": "unavailable",
            "reason": "voice_biometrics_unavailable",
            "similarity": 0.0,
            "threshold": DEFAULT_THRESHOLD,
            "message": (
                "Balso biometrika nepasiekiama: "
                f"{unavailable_reason}."
            ),
        }

    # 2. Jei nėra profilio — verifikacija neaktyvuota, leidžiame
    if enrolled_fp is None:
        return {
            "status": "no_profile",
            "reason": "voice_profile_not_enrolled",
            "similarity": 1.0,
            "threshold": DEFAULT_THRESHOLD,
            "message": "Balso profilis neužregistruotas. Komanda vykdoma be verifikacijos.",
        }

    # 3. Jei audio tuščias
    if not audio_bytes or len(audio_bytes) < 500:
        return {
            "status": "blocked",
            "reason": "audio_too_short",
            "similarity": 0.0,
            "threshold": DEFAULT_THRESHOLD,
            "message": "Audio per trumpas arba tuščias. Komanda atmesta.",
        }

    # 4. Apskaičiuojame kandidato fingerprint
    try:
        from app.services.audio_fingerprint import compute_fingerprint, verify_fingerprint
        candidate_fp = compute_fingerprint(audio_bytes)
    except Exception as exc:
        logger.error("Nepavyko apskaičiuoti fingerprint: %s", exc)
        return {
            "status": "error",
            "reason": "fingerprint_compute_failed",
            "similarity": 0.0,
            "threshold": DEFAULT_THRESHOLD,
            "message": "Nepavyko išanalizuoti garso. Bandykite dar kartą.",
        }

    # 5. Lyginame
    threshold = custom_threshold if custom_threshold is not None else DEFAULT_THRESHOLD
    passed, similarity = verify_fingerprint(enrolled_fp, candidate_fp, threshold)

    logger.info(
        "Speaker verification: similarity=%.3f threshold=%.3f passed=%s",
        similarity, threshold, passed,
    )

    if passed:
        # Atnaujinome last_verified_at
        try:
            from app.services.voice_profile_service import get_voice_profile
            from app.models.settings import UserSettings
            profile = await get_voice_profile(db)
            if profile:
                profile.last_verified_at = datetime.datetime.now(datetime.timezone.utc)
                await db.flush()
            settings_row = await db.get(UserSettings, 1)
            if settings_row:
                settings_row.failed_voice_attempts = 0
                await db.flush()
        except Exception:
            pass

        return {
            "status": "success",
            "similarity": round(similarity, 3),
            "threshold": threshold,
            "message": f"Balsas atpažintas ✓ (panašumas: {similarity:.0%})",
        }
    else:
        # Registruojame nesėkmingą bandymą
        try:
            from app.models.settings import UserSettings
            settings_row = await db.get(UserSettings, 1)
            if settings_row:
                settings_row.failed_voice_attempts = (settings_row.failed_voice_attempts or 0) + 1
                await db.flush()
        except Exception:
            pass

        return {
            "status": "blocked",
            "similarity": round(similarity, 3),
            "threshold": threshold,
            "message": (
                f"Balsas neatpažintas ✗ (panašumas: {similarity:.0%}, "
                f"reikalinga: {threshold:.0%}). Komanda atmesta."
            ),
        }
