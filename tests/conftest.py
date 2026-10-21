import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Base SQLite de test isolée (les jobs ne polluent pas le dossier du projet)
os.environ.setdefault("TRAFFICKER_DB", os.path.join(tempfile.mkdtemp(), "test.db"))
