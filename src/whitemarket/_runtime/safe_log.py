"""A logger wrapper for the transports: a failing logger never changes the outcome of a request."""

import contextlib
import logging

LOGGER_NAME = "whitemarket"


class SafeLog:
    """A logger that never lets its own failure change the outcome of a request."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def debug(self, message: str, *args: object) -> None:
        with contextlib.suppress(Exception):  # a broken user logger must not fail a request
            self._logger.debug(message, *args)

    def info(self, message: str, *args: object) -> None:
        with contextlib.suppress(Exception):
            self._logger.info(message, *args)

    def warning(self, message: str, *args: object) -> None:
        with contextlib.suppress(Exception):
            self._logger.warning(message, *args)
