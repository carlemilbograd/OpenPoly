"""
conftest.py — pytest configuration and fixtures for OpenPoly tests.

Handles module isolation between test_prob_model.py (which stubs sys.modules["db"]
at collection time) and test_db.py (which needs the real db module).
"""
import sys
import importlib
import importlib.util
from pathlib import Path
import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))


def _force_load_real_db():
    """
    Load the real db module directly from scripts/db.py, bypassing sys.modules cache.
    Called at conftest collection time, before test_prob_model.py can pollute db.
    """
    spec = importlib.util.spec_from_file_location("_real_db_openpoly", SCRIPTS_DIR / "db.py")
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Load and cache the real db module now, BEFORE any test file is collected
_REAL_DB = _force_load_real_db()


@pytest.fixture
def real_db():
    """Provide the real (non-stubbed) db module to tests that need it."""
    return _REAL_DB


@pytest.fixture(autouse=True)
def _inject_real_db_for_db_tests(request):
    """
    For tests in test_db.py: temporarily restore sys.modules["db"] to the real
    module so that `import db as db_module` inside each test gets the real class,
    not the prob_model stub injected at test_prob_model.py collection time.
    """
    if request.fspath and "test_db" in request.fspath.basename:
        original = sys.modules.get("db")
        sys.modules["db"] = _REAL_DB
        yield
        if original is None:
            sys.modules.pop("db", None)
        else:
            sys.modules["db"] = original
    else:
        yield
