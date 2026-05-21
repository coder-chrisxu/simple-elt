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
    """Classifies Oracle-specific errors based on ORA- error codes."""

    TRANSIENT_CODES = {
        3113,   # end-of-file on communication channel
        3114,   # not connected to ORACLE
        2396,   # exceeded maximum idle time
        12571,  # TNS:packet writer failure
        3135,   # connection lost contact
        12514,  # TNS:listener does not currently know of service
        12170,  # TNS:connect timeout occurred
        12541,  # TNS:no listener
        12560,  # TNS:protocol adapter error
        27102,  # out of memory (can be transient under load)
    }

    def classify(self, exception: Exception) -> ErrorClass:
        if isinstance(exception, (ConnectionError, TimeoutError, OSError)):
            return ErrorClass.TRANSIENT

        error = getattr(exception, "args", [None])[0] if exception.args else None
        if isinstance(error, str):
            code = self._extract_ora_code(error)
            if code is not None and code in self.TRANSIENT_CODES:
                return ErrorClass.TRANSIENT

        if hasattr(exception, "code") and isinstance(exception.code, int):
            if exception.code in self.TRANSIENT_CODES:
                return ErrorClass.TRANSIENT

        return ErrorClass.PERMANENT

    @staticmethod
    def _extract_ora_code(message: str) -> int | None:
        """Extract the numeric code from an ORA-XXXXX string."""
        match = re.search(r"ORA-(\d+)", message)
        return int(match.group(1)) if match else None


CLASSIFIER_MAP: dict[str, type[ErrorClassifier]] = {
    "oracle": OracleErrorClassifier,
}
