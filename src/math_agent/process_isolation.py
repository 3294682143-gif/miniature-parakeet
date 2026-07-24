from __future__ import annotations

import ctypes
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager

MAX_CONCURRENT_ISOLATED_PROCESSES = 4
PROCESS_SLOT_WAIT_SECONDS = 0.1
_PROCESS_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT_ISOLATED_PROCESSES)


class ProcessCapacityError(RuntimeError):
    """Raised when the process-wide isolated-worker budget is exhausted."""


@contextmanager
def isolated_process_slot() -> Iterator[None]:
    """Reserve one process-wide worker slot and always return it to the pool."""

    acquired = _PROCESS_SLOTS.acquire(timeout=PROCESS_SLOT_WAIT_SECONDS)
    if not acquired:
        raise ProcessCapacityError("isolated process capacity is exhausted")
    try:
        yield
    finally:
        _PROCESS_SLOTS.release()


class WindowsJobLimits:
    """Own a Windows job that bounds and terminates an assigned child process."""

    def __init__(self, handle: int) -> None:
        self.handle = handle

    def close(self) -> None:
        if not self.handle:
            return
        try:
            ctypes.windll.kernel32.CloseHandle(self.handle)
        finally:
            self.handle = 0


def assign_windows_job_limits(
    pid: int, *, memory_limit_bytes: int, cpu_limit_seconds: int
) -> WindowsJobLimits | None:
    if os.name != "nt":
        return None
    try:
        from ctypes import wintypes

        class _BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class _IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class _ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _BasicLimitInformation),
                ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.OpenProcess.restype = wintypes.HANDLE
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        limits = _ExtendedLimitInformation()
        limits.BasicLimitInformation.PerProcessUserTimeLimit = (
            cpu_limit_seconds * 10_000_000
        )
        # CPU time, process memory, and kill-on-close.
        limits.BasicLimitInformation.LimitFlags = 0x2 | 0x100 | 0x2000
        limits.ProcessMemoryLimit = memory_limit_bytes
        if not kernel32.SetInformationJobObject(
            job, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            kernel32.CloseHandle(job)
            return None
        process_handle = kernel32.OpenProcess(0x1 | 0x100 | 0x1000, False, pid)
        if not process_handle:
            kernel32.CloseHandle(job)
            return None
        try:
            if not kernel32.AssignProcessToJobObject(job, process_handle):
                kernel32.CloseHandle(job)
                return None
        finally:
            kernel32.CloseHandle(process_handle)
        return WindowsJobLimits(int(job))
    except (AttributeError, OSError, TypeError, ValueError):
        return None
