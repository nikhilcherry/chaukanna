import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CLASSIFIER_BACKEND", "none")
os.environ.setdefault("WARMUP", "0")
