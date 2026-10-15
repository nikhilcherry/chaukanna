# tts_asset_generator

Pre-generates Chaukanna's scam-warning whispers with Sarvam AI TTS (`bulbul:v3`) so the Flutter app plays them locally mid-call: no network, no latency.

4 warnings (`warn_otp`, `warn_digital_arrest`, `warn_secrecy`, `warn_known_scammer`) x 3 languages (`hi`, `kn`, `en`) = 12 WAVs in `output_assets/`, plus `manifest.json` mapping warning type -> language -> filename.

```
cp .env.example .env     # add SARVAM_API_KEY
python generate.py       # generate (skips existing; --force to redo; --speaker NAME to change voice)
python generate.py --verify
```

Stdlib only, Python 3.8+. Copy `output_assets/*` into the Flutter `assets/audio/`.
