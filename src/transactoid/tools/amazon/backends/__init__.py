"""Amazon scraper backend implementations."""

from transactoid.tools.amazon.backends.base import AmazonScraperBackend
from transactoid.tools.amazon.backends.playwriter import PlaywriterBackend

__all__ = ["AmazonScraperBackend", "PlaywriterBackend"]

# Stagehand backends are conditionally imported to avoid requiring stagehand.
# Import directly:
#   from transactoid.tools.amazon.backends.stagehand_local import (
#       StagehandLocalBackend,
#   )
#   from transactoid.tools.amazon.backends.stagehand_browserbase import (
#       StagehandBrowserbaseBackend,
#   )
