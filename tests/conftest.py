import os
import tempfile

# Must be set before the app package is imported.
_tmp = tempfile.mkdtemp(prefix="save-test-")
os.environ["DATA_DIR"] = _tmp
os.environ["DISABLE_BOT"] = "1"
os.environ["SECURE_COOKIES"] = "0"
os.environ["SECRET_KEY"] = "test-secret"
