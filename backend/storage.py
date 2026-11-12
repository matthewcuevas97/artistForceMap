"""
File-storage helpers shared by backend/cache.py and backend/user_data.py.

* safe_id(): user ids become file names, so anything outside a conservative
  character set (path separators, "..", unicode) is replaced by a hash (BUG-22).
* write_json_atomic(): write to a temp file in the same directory, then
  os.replace() it over the target, so a crash or a concurrent reader never sees
  a truncated file (BUG-11).
* file_lock(): one re-entrant lock per path, held across load→modify→save so two
  threads updating the same cache don't lose each other's writes. (In-process
  only; run a single worker process, or move to SQLite for multi-process.)
"""

import hashlib
import json
import os
import re
import tempfile
import threading
from collections import defaultdict

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]{0,63}$")

_locks = defaultdict(threading.RLock)
_locks_guard = threading.Lock()


def safe_id(user_id) -> str:
    """Return `user_id` if it is a safe file-name stem, else a stable hash of it."""
    s = str(user_id)
    if _SAFE_ID.match(s):
        return s
    return "h_" + hashlib.sha256(s.encode("utf-8")).hexdigest()[:32]


def file_lock(path: str) -> threading.RLock:
    key = os.path.realpath(path)
    with _locks_guard:
        return _locks[key]


def write_json_atomic(path: str, data, **dump_kwargs) -> None:
    """Serialise `data` to `path` atomically. Raises on failure; the old file is untouched."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, **{"indent": 2, **dump_kwargs})
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def read_json(path: str, default):
    """Load JSON from `path`; `default` if missing or unreadable."""
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default
