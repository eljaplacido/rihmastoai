"""Who the operating system says runs this process, and who owns a file (D-0016).

Both are read from the operating system, never from an environment variable: anyone can set USERNAME
or USER to another name. ``kernel.access`` signs the command line and the MCP server as
``local:<os_user()>``, and records the owner of a changed access file beside what the file claims.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def os_user() -> str:
    """The operating system's account that runs this process."""
    if sys.platform == "win32":
        return os.getlogin()
    import pwd

    return pwd.getpwuid(os.getuid()).pw_name


def file_owner(path: Path) -> str | None:
    """The account that owns ``path`` as the file system records it, or None when it cannot be read.
    Writing into an existing file keeps its owner; replacing the file makes the writer its owner."""
    try:
        if sys.platform == "win32":
            return _windows_owner(str(path))
        import pwd

        return pwd.getpwuid(path.stat().st_uid).pw_name
    except (OSError, KeyError, ValueError, AttributeError):
        return None


def _windows_owner(path: str) -> str | None:
    """The owner in the file's security descriptor (GetNamedSecurityInfoW), as DOMAIN\\name."""
    import ctypes
    from ctypes import wintypes

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ptr = ctypes.POINTER(ctypes.c_void_p)
    info = advapi.GetNamedSecurityInfoW
    info.restype = wintypes.DWORD
    info.argtypes = [wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD, ptr, ptr, ptr, ptr, ptr]
    lookup = advapi.LookupAccountSidW
    lookup.restype = wintypes.BOOL
    size = ctypes.POINTER(wintypes.DWORD)
    lookup.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p, wintypes.LPWSTR, size, wintypes.LPWSTR, size, size]
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    owner, descriptor = ctypes.c_void_p(), ctypes.c_void_p()
    # SE_FILE_OBJECT = 1, OWNER_SECURITY_INFORMATION = 1
    if info(path, 1, 1, ctypes.byref(owner), None, None, None, ctypes.byref(descriptor)) != 0:
        return None
    try:
        name, domain = ctypes.create_unicode_buffer(256), ctypes.create_unicode_buffer(256)
        n, d, use = wintypes.DWORD(256), wintypes.DWORD(256), wintypes.DWORD()
        if not lookup(None, owner, name, ctypes.byref(n), domain, ctypes.byref(d), ctypes.byref(use)):
            return None
        return f"{domain.value}\\{name.value}" if domain.value else name.value
    finally:
        kernel32.LocalFree(descriptor)
