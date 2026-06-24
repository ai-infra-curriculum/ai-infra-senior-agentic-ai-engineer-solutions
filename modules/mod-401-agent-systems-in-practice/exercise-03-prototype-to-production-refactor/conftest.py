"""Put the exercise root on sys.path so ``import agent`` / ``import prototype`` resolve."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
