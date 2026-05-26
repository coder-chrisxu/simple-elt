import re
from abc import ABC, abstractmethod
from enum import Enum


class ErrorClass(Enum):
    TRANSIENT = "transient"
    PERMANENT = "permanent"


class ErrorClassifier(ABC):
    """Classifies exceptions as retryable (transient) or non-retryable (permanent)."""

    @abstractmethod
    def classify(self, exception: Exception) -> ErrorClass:
        """Return the error class for the given exception."""


class OracleErrorClassifier(ErrorClassifier):
    """Classifies Oracle-specific errors based on ORA- and DPY- error codes."""

    TRANSIENT_CODES = {
        60,     # deadlock detected
        1033,   # ORACLE startup or shutdown in progress
        2396,   # exceeded maximum idle time
        3113,   # end-of-file on communication channel
        3114,   # not connected to ORACLE
        3135,   # connection lost contact
        12170,  # TNS:connect timeout occurred
        12514,  # TNS:listener does not currently know of service
        12520,  # TNS:listener could not find available handler
        12537,  # TNS:connection closed
        12541,  # TNS:no listener
        12560,  # TNS:protocol adapter error
        12571,  # TNS:packet writer failure
        27102,  # out of memory (can be transient under load)
        # python-oracledb Thin mode driver-level transient codes
        6001,   # connection lost or listener down
        6005,   # connection closed
    }

    def classify(self, exception: Exception) -> ErrorClass:
        if isinstance(exception, (ConnectionError, TimeoutError, OSError)):
            return ErrorClass.TRANSIENT

        if hasattr(exception, "code"):
            code_val = exception.code
            if isinstance(code_val, int):
                if code_val in self.TRANSIENT_CODES:
                    return ErrorClass.TRANSIENT
            elif isinstance(code_val, str):
                match = re.search(r"(\d+)", code_val)
                if match and int(match.group(1)) in self.TRANSIENT_CODES:
                    return ErrorClass.TRANSIENT

        # Robustly extract codes from the string representation
        err_str = str(exception)
        match = re.search(r"(?:ORA|DPY)-(\d+)", err_str)
        if match:
            code = int(match.group(1))
            if code in self.TRANSIENT_CODES:
                return ErrorClass.TRANSIENT

        return ErrorClass.PERMANENT


CLASSIFIER_MAP: dict[str, type[ErrorClassifier]] = {
    "oracle": OracleErrorClassifier,
}
