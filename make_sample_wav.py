"""Write sample_scam_call.wav: 16 s of synthetic speech-like noise bursts (clears the silence gate).
Replace it with a real recording for the demo; the bridge resamples any PCM WAV."""
import wave

import numpy as np

rng = np.random.default_rng(1)
sr, secs = 16000, 16
t = np.arange(sr * secs) / sr
a = (rng.normal(0, 3000, t.size) * (0.5 + 0.5 * np.sin(2 * np.pi * 3 * t))).clip(-32768, 32767).astype(np.int16)
with wave.open("sample_scam_call.wav", "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(a.tobytes())
