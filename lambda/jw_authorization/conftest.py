import os
import sys
from pathlib import Path

LAMBDA_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(LAMBDA_DIR))

os.environ.setdefault("ENVIRONMENT", "local")
os.environ.setdefault("CONFIG_SKIP_AWS", "true")
os.environ.setdefault("USER_GG", "TEST_USER_GROUP")
os.environ.setdefault("ADMIN_GG", "TEST_ADMIN_GROUP")
os.environ.setdefault(
    "JW_REQUIRED_GROUPS",
    "TEST_USER_GROUP,TEST_ADMIN_GROUP",
)
