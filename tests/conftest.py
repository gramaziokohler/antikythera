import logging
import sys

import pytest


@pytest.fixture(autouse=True)
def setup_logging():
    logging.basicConfig(level=logging.DEBUG, format="[%(name)s] %(message)s", stream=sys.stdout, force=True)
