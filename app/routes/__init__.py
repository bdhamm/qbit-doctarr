"""Routes package for qbit-doctarr.

`bp` is the single blueprint registered by `app/__init__.py`. Submodules
import it and decorate `@bp.route(...)` to register their endpoints. Import
order at the bottom of this file matters only for registration order, not
behavior — all routes resolve by URL path, not by position.

Submodules must be imported AFTER `bp` is defined. Python module init is
sequential, so `from . import pages` sees `bp` already in this package's
namespace.
"""

from flask import Blueprint

bp = Blueprint('main', __name__)

# Import submodules to trigger @bp.route registration. Order is arbitrary.
from . import pages         # noqa: E402,F401
from . import api_stats     # noqa: E402,F401
from . import api_missing   # noqa: E402,F401
from . import api_config    # noqa: E402,F401
from . import api_quarantine  # noqa: E402,F401
from . import api_tasks     # noqa: E402,F401
from . import api_debug     # noqa: E402,F401
from . import api_health    # noqa: E402,F401
from . import api_stalled   # noqa: E402,F401
from . import api_metrics   # noqa: E402,F401
