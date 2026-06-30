import sys

from db import core as _core

sys.modules[__name__] = _core
