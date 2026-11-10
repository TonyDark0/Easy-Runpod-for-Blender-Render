"""Local OAuth storage. Windows uses the signed-in user's DPAPI protection."""
import base64
import ctypes
import json
import os


def _protect(data, decrypt=False):
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_char))]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    target = Blob()
    function = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise OSError("Could not access protected Google credentials for this Windows user")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        ctypes.windll.kernel32.LocalFree(target.data)


def read_credentials(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if "windows_dpapi" in data:
        if os.name != "nt":
            raise ValueError("Reconnect Google Drive on this computer")
        return json.loads(_protect(base64.b64decode(data["windows_dpapi"]), decrypt=True))
    return data  # Existing installations are migrated on their next connection.


def write_credentials(path, data):
    payload = json.dumps(data).encode("utf-8")
    if os.name == "nt":
        payload = json.dumps({"windows_dpapi": base64.b64encode(_protect(payload)).decode()}).encode()
    temporary = path.with_suffix(".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
    temporary.replace(path)
