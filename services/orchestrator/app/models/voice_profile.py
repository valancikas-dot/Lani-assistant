"""ORM model for local voice profiles and enrollment metadata.

This table stores metadata about locally enrolled voice profiles. Audio
samples themselves are saved to the local filesystem (see
services/voice_profile_service.py). The model intentionally does not store raw
audio or any biometric templates – only metadata and paths to locally stored
sample files.
"""

import datetime
import json
from typing import Optional
from sqlalchemy import Integer, String, Boolean, Text, DateTime, Float
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class VoiceProfile(Base):
    """Represents a user's enrolled voice profile (placeholder mode).

    Enrollment and verification are clearly labelled as placeholder until a
    real verification provider is integrated.
    """

    __tablename__ = "voice_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_name: Mapped[str] = mapped_column(String(100), default="Primary", nullable=False)
    owner_label: Mapped[str] = mapped_column(String(100), default="owner", nullable=False)
    enrollment_status: Mapped[str] = mapped_column(String(40), default="not_configured", nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    samples_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    # JSON-serialized float32 numpy array (voice fingerprint for speaker verification)
    fingerprint_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Threshold override (0.0-1.0); None = use DEFAULT_THRESHOLD from audio_fingerprint
    verification_threshold: Mapped[Optional[float]] = mapped_column(nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    verification_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_verified_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    def sample_paths(self) -> list[str]:
        try:
            return json.loads(self.samples_json or "[]")
        except Exception:
            return []
