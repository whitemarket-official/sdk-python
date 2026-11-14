"""Where a download is written (SDK_SPEC 3.10 rule 7): blocking file IO, no HTTP.

A path is written through a private temporary file of its own next to it and renamed over it
when the download is complete, so a failure leaves the destination untouched and two downloads to
one path at once never share a file (the last rename wins). A file object is written as is, left
open and unrewound; what it holds after a failure is the caller's to discard.

Every method blocks: the async client runs them in a worker thread (`async_run_blocking`).
"""

import contextlib
import os
import secrets
import stat
from pathlib import Path
from typing import BinaryIO, Final, Protocol

from whitemarket.errors.base import GeneralExportError

Destination = str | os.PathLike[str] | BinaryIO

_NAME_PART: Final = 40
_CREATE_TRIES: Final = 8
_NO_FOLLOW: Final = getattr(os, "O_NOFOLLOW", 0)
_WRITE_FAILED: Final = "Writing the download failed."
_NO_TEMPORARY: Final = "Cannot create a temporary file next to the download destination."


def _chmod(descriptor: int, mode: int) -> None:
    if hasattr(os, "fchmod"):  # not on every platform; the mode is a no-op there anyway
        os.fchmod(descriptor, mode)


class DownloadSink(Protocol):
    def write(self, data: bytes) -> None: ...

    def commit(self) -> None: ...

    def abort(self) -> None: ...


def abort_sink(sink: DownloadSink) -> None:
    """Give a sink back unused (`abort` as a function, for a cleanup callback)."""
    sink.abort()


def open_sink(destination: Destination) -> DownloadSink:
    """The sink for `destination`; raises `GeneralExportError` when it cannot be written."""
    if not isinstance(destination, str | os.PathLike):
        return _StreamSink(destination)
    path = Path(os.fspath(destination))
    if path.is_dir():
        raise GeneralExportError("The download destination is a directory.")
    return _FileSink(path)


class _FileSink:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._temporary, self._file, self._new_mode = self._create()

    def _create(self) -> tuple[Path, BinaryIO, int]:
        # Mode 0666 with O_EXCL: the umask gives the file the mode a new file would have (kept
        # for the commit), and a name that exists (or a symlink planted there) is never opened.
        # The file is made private (0600) before anything is written to it.
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NO_FOLLOW
        name = self._path.name[:_NAME_PART]
        for _ in range(_CREATE_TRIES):
            temporary = self._path.with_name(f".{name}.{secrets.token_hex(6)}.part")
            try:
                descriptor = os.open(temporary, flags, 0o666)
            except FileExistsError:
                continue
            except OSError as error:
                raise GeneralExportError(_NO_TEMPORARY) from error
            try:
                new_mode = stat.S_IMODE(os.fstat(descriptor).st_mode)
                _chmod(descriptor, 0o600)
            except OSError as error:
                os.close(descriptor)
                temporary.unlink(missing_ok=True)
                raise GeneralExportError(_NO_TEMPORARY) from error
            return temporary, os.fdopen(descriptor, "wb"), new_mode
        raise GeneralExportError(_NO_TEMPORARY)

    def write(self, data: bytes) -> None:
        try:
            self._file.write(data)
        except OSError as error:
            raise GeneralExportError(_WRITE_FAILED) from error

    def commit(self) -> None:
        try:
            self._file.flush()
            os.fsync(self._file.fileno())
            _chmod(self._file.fileno(), self._final_mode())
            self._file.close()
            os.replace(self._temporary, self._path)
        except OSError as error:
            raise GeneralExportError("Cannot move the finished download into place.") from error

    def _final_mode(self) -> int:
        """The mode of the file being replaced, else the mode a new file would get (as PHP's
        `0666 & ~umask()`)."""
        try:
            return stat.S_IMODE(os.stat(self._path).st_mode)
        except OSError:
            return self._new_mode

    def abort(self) -> None:
        with contextlib.suppress(OSError):
            self._file.close()
        with contextlib.suppress(OSError):
            self._temporary.unlink()


class _StreamSink:
    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream
        try:
            writable = stream.writable()
        except (OSError, ValueError, AttributeError):
            writable = False
        if not writable:
            raise GeneralExportError("The download destination stream is not writable.")

    def write(self, data: bytes) -> None:
        # A write may take less than it is given (a socket, a full disk): the rest is written
        # again, and a write that takes nothing fails instead of looping.
        view = memoryview(data)
        try:
            while view:
                written = self._stream.write(view)
                if not written:
                    raise GeneralExportError("Writing the download made no progress.")
                view = view[written:]
        except (OSError, ValueError) as error:
            raise GeneralExportError(_WRITE_FAILED) from error

    def commit(self) -> None:
        try:
            self._stream.flush()
        except (OSError, ValueError) as error:
            raise GeneralExportError(_WRITE_FAILED) from error

    def abort(self) -> None:
        return None
