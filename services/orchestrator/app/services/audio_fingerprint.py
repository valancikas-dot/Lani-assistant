"""audio_fingerprint.py – lokali garso "piršto atspaudų" sistema.

Naudoja tik numpy (be papildomų paketų). Veikimo principas:
  1. PCM audio ištraukiamas iš WebM/webm bylos naudojant žalią bajtu analizę
     (arba tiesiog naudojame raw bytes spektro analizę).
  2. Apskaičiuojamas supaprastintas MFCC (Mel-frequency cepstral coefficients)
     aproksimavimas naudojant FFT.
  3. Rezultatas – vidurkinis vektorius (128 dimensijų), kuris vadinamas "fingerprint".
  4. Verifikacijos metu skaičiuojamas cosine similarity tarp užrašyto
     ir naujo fingerprint – jei > THRESHOLD, balsas atpažintas.

SVARBU: Tai nėra kriptografiškai saugus biometrinis sprendimas.
Skirtas apsaugoti nuo atsitiktinių fone esančių balsų, ne nuo tikslingų atakų.
"""

import struct
import math
from typing import Optional
import numpy as np

# ── Konfigūracija ──────────────────────────────────────────────────────────────
SAMPLE_RATE = 16000       # Tikslinė dažninė sparta (16 kHz)
N_MFCC = 20               # MFCC koeficientų skaičius
N_FFT = 512               # FFT dydis
HOP_LENGTH = 160          # Žingsnis tarp FFT langų (10 ms)
N_MELS = 40               # Mel filtrų skaičius
FINGERPRINT_DIM = 80      # Galutinio vektoriaus dimensija (N_MFCC * 4)

# ── Verifikacijos slenkstis ────────────────────────────────────────────────────
# 0.0 = visi priimami, 1.0 = tik identiškas balsas
# Rekomenduojama: 0.70 – 0.80
DEFAULT_THRESHOLD = 0.72


# ── PCM ištraukimas iš WebM/raw bytes ─────────────────────────────────────────

def _extract_pcm_from_bytes(audio_bytes: bytes, target_sr: int = SAMPLE_RATE) -> np.ndarray:
    """Ištraukia PCM mėginius iš audio bajtu srauto.

    Palaiko:
    - Raw PCM (16-bit signed little-endian)
    - WebM/Opus approximation (naudoja FFT tiesiai iš bajtu)

    Grąžina float32 masyvą [-1, 1].
    """
    # Bandome interpretuoti kaip 16-bit PCM
    n_samples = len(audio_bytes) // 2
    if n_samples > 100:
        try:
            pcm = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
            pcm /= 32768.0
            # Sanity check: jei dauguma reikšmių labai mažos arba labai didelės,
            # tai turbūt ne PCM
            if 0.001 < float(np.abs(pcm).mean()) < 0.99:
                return _resample(pcm, len(pcm), target_sr * (len(audio_bytes) // 32000 + 1))
        except Exception:
            pass

    # Fallback: naudojame bajtu reikšmes kaip signalą (veikia su bet kokiu formatu)
    raw = np.frombuffer(audio_bytes, dtype=np.uint8).astype(np.float32)
    raw = (raw - 128.0) / 128.0  # normalizuojame
    return raw


def _resample(signal: np.ndarray, orig_len: int, target_len: int) -> np.ndarray:
    """Paprastas linijinis resampling."""
    if orig_len == target_len or target_len <= 0:
        return signal
    indices = np.linspace(0, len(signal) - 1, target_len)
    return np.interp(indices, np.arange(len(signal)), signal)


# ── Mel filterbank ─────────────────────────────────────────────────────────────

def _hz_to_mel(hz: float) -> float:
    return 2595.0 * math.log10(1.0 + hz / 700.0)


def _mel_to_hz(mel: float) -> float:
    return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)


def _mel_filterbank(n_fft: int, n_mels: int, sr: int) -> np.ndarray:
    """Grąžina (n_mels, n_fft//2+1) Mel filterbank matricą."""
    low_mel = _hz_to_mel(0.0)
    high_mel = _hz_to_mel(sr / 2.0)
    mel_points = np.linspace(low_mel, high_mel, n_mels + 2)
    hz_points = np.array([_mel_to_hz(m) for m in mel_points])
    bin_points = np.floor((n_fft + 1) * hz_points / sr).astype(int)

    n_freqs = n_fft // 2 + 1
    filters = np.zeros((n_mels, n_freqs))
    for m in range(1, n_mels + 1):
        f_left = bin_points[m - 1]
        f_center = bin_points[m]
        f_right = bin_points[m + 1]
        for k in range(f_left, f_center):
            if f_center != f_left:
                filters[m - 1, k] = (k - f_left) / (f_center - f_left)
        for k in range(f_center, f_right):
            if f_right != f_center:
                filters[m - 1, k] = (f_right - k) / (f_right - f_center)
    return filters


# ── MFCC skaičiavimas ─────────────────────────────────────────────────────────

def compute_mfcc(signal: np.ndarray, sr: int = SAMPLE_RATE,
                 n_mfcc: int = N_MFCC, n_fft: int = N_FFT,
                 hop_length: int = HOP_LENGTH, n_mels: int = N_MELS) -> np.ndarray:
    """Grąžina MFCC matricą (n_mfcc, n_frames)."""
    # Jei signalas per trumpas, pridedame tylą
    if len(signal) < n_fft:
        signal = np.pad(signal, (0, n_fft - len(signal)))

    # Frames
    n_frames = max(1, (len(signal) - n_fft) // hop_length + 1)
    frames = np.lib.stride_tricks.sliding_window_view(signal[:n_frames * hop_length + n_fft], n_fft)[::hop_length]

    # Hamming langas
    window = np.hamming(n_fft)
    frames = frames * window

    # FFT magnitude spektras
    fft_mag = np.abs(np.fft.rfft(frames, n=n_fft))  # (n_frames, n_fft//2+1)
    power = fft_mag ** 2

    # Mel energija
    mel_fb = _mel_filterbank(n_fft, n_mels, sr)  # (n_mels, n_fft//2+1)
    mel_energy = np.dot(power, mel_fb.T)  # (n_frames, n_mels)
    mel_energy = np.where(mel_energy == 0, np.finfo(float).eps, mel_energy)
    log_mel = np.log(mel_energy)

    # DCT (diskretinė kosinusų transformacija)
    n = np.arange(n_mfcc).reshape(-1, 1)
    k = np.arange(n_mels).reshape(1, -1)
    dct_matrix = np.cos(np.pi * n * (2 * k + 1) / (2 * n_mels))
    mfcc = np.dot(dct_matrix, log_mel.T)  # (n_mfcc, n_frames)

    return mfcc


# ── Fingerprint apskaičiavimas ─────────────────────────────────────────────────

def compute_fingerprint(audio_bytes: bytes) -> np.ndarray:
    """Apskaičiuoja garso "piršto atspaudą" iš audio bajtu.

    Grąžina normalizuotą 1D float32 vektorių (FINGERPRINT_DIM dimensijų).
    """
    signal = _extract_pcm_from_bytes(audio_bytes)

    # Minimalus ilgis
    if len(signal) < N_FFT * 2:
        signal = np.pad(signal, (0, N_FFT * 2 - len(signal)))

    mfcc = compute_mfcc(signal)  # (N_MFCC, n_frames)

    # Statistikos: vidurkis, standartinis nuokrypis, min, max kiekvienam koeficientui
    mean = np.mean(mfcc, axis=1)    # (N_MFCC,)
    std = np.std(mfcc, axis=1)      # (N_MFCC,)
    mn = np.min(mfcc, axis=1)       # (N_MFCC,)
    mx = np.max(mfcc, axis=1)       # (N_MFCC,)

    fp = np.concatenate([mean, std, mn, mx])  # (N_MFCC * 4,) = (80,)

    # L2 normalizacija
    norm = np.linalg.norm(fp)
    if norm > 0:
        fp = fp / norm

    return fp.astype(np.float32)


def combine_fingerprints(fingerprints: list[np.ndarray]) -> np.ndarray:
    """Sujungia kelis enrollment fingerprints į vieną vidurkį."""
    if not fingerprints:
        raise ValueError("Nėra fingerprints")
    stacked = np.stack(fingerprints, axis=0)  # (n, dim)
    mean_fp = np.mean(stacked, axis=0)
    norm = np.linalg.norm(mean_fp)
    if norm > 0:
        mean_fp = mean_fp / norm
    return mean_fp.astype(np.float32)


# ── Verifikacija ───────────────────────────────────────────────────────────────

def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity tarp dviejų normalizuotų vektorių."""
    # Jei abu normalizuoti, dot product = cosine similarity
    sim = float(np.dot(a, b))
    # Apribojame [-1, 1]
    return max(-1.0, min(1.0, sim))


def verify_fingerprint(
    enrolled: np.ndarray,
    candidate: np.ndarray,
    threshold: float = DEFAULT_THRESHOLD,
) -> tuple[bool, float]:
    """Palygina du fingerprints.

    Grąžina (passed: bool, similarity: float).
    """
    sim = cosine_similarity(enrolled, candidate)
    return sim >= threshold, sim


# ── JSON serialization ─────────────────────────────────────────────────────────

def fingerprint_to_json(fp: np.ndarray) -> str:
    """Konvertuoja fingerprint į JSON eilutę saugojimui DB."""
    import json
    return json.dumps(fp.tolist())


def fingerprint_from_json(s: str) -> Optional[np.ndarray]:
    """Nuskaito fingerprint iš JSON eilutės."""
    import json
    if not s:
        return None
    try:
        data = json.loads(s)
        arr = np.array(data, dtype=np.float32)
        norm = np.linalg.norm(arr)
        if norm > 0:
            arr = arr / norm
        return arr
    except Exception:
        return None
