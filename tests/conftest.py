from __future__ import annotations

import os

# Test suites use local dev auth headers intentionally. Production/default runtime
# keeps CONTEXTSMITH_DEV_AUTH disabled unless operators opt in.
os.environ.setdefault("CONTEXTSMITH_DEV_AUTH", "true")
