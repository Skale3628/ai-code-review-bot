import logging
import sys
from app.core.config import settings


def setup_logging():
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    # Quiet noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
