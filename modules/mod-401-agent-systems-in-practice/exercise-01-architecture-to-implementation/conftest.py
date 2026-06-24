"""Put the exercise root on sys.path so ``import executor`` resolves under pytest."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
