"""Offline migration foundation.

The package contains pure transformation rules and candidate-only persistence
helpers.  Importing it must never initialize or mutate the ODE production
database.
"""

from __future__ import annotations


STAGE = "0.13.3A"
