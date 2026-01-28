import logging
from typing import Any
from typing import Dict

from asteval import Interpreter

LOG = logging.getLogger(__name__)


def safe_eval_condition(expression: str, context: Dict[str, Any]) -> bool:
    """Evaluates a python condition expression using asteval."""
    try:
        aeval = Interpreter(usersyms=context)
        result = aeval(expression)

        if len(aeval.error) > 0:
            # asteval suppresses exceptions by default and adds them to aeval.error
            # We want to know if something went wrong
            msg = [str(e.get_error()) for e in aeval.error]
            raise ValueError(f"Error evaluating condition: {msg}")

        return bool(result)
    except Exception as e:
        LOG.error(f"Failed to safely evaluate condition '{expression}': {e}")
        raise e
