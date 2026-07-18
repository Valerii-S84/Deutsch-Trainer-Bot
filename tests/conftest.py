from __future__ import annotations

import os


# Keep test collection deterministic when the host exports a non-project
# shorthand such as APP_ENV=dev. Individual tests may still override it.
os.environ["APP_ENV"] = "development"
