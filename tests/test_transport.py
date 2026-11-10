import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("transport", ROOT / "addon/runpod_render/transport.py")
transport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)


class Response(io.BytesIO):
    def __init__(self, body, headers=None):
        super().__init__(json.dumps(body).encode())
        self.headers = headers or {}


class UploadTests(unittest.TestCase):
    def test_cancel_before_upload_never_starts_session(self):
        cancel = threading.Event()
        cancel.set()
        with patch.object(transport, "request") as request:
            with self.assertRaises(transport.Cancelled):
                transport.Drive("id", "secret", "refresh").upload("unused", "folder", cancel=cancel)
            request.assert_not_called()

    def test_large_upload_is_chunked_and_confirmed(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "scene.blend"
            source.write_bytes(b"x" * (8 * 1024 * 1024 + 1))
            calls = []
            def request(url, *args, **kwargs):
                if "token" in url:
                    return Response({"access_token": "token"})
                if kwargs.get("method") == "POST":
                    return Response({}, {"Location": "https://upload.test/session"})
                calls.append(kwargs)
                if len(calls) == 1:
                    raise HTTPError(url, 308, "Resume Incomplete", {"Range": "bytes=0-8388607"}, None)
                return Response({"id": "uploaded"})
            with patch.object(transport, "request", side_effect=request):
                self.assertEqual(transport.Drive("id", "secret", "refresh").upload(source, "folder"), "uploaded")
            self.assertEqual(calls[0]["headers"]["Content-Range"], "bytes 0-8388607/8388609")
            self.assertEqual(calls[1]["data"], b"x")

    def test_cancel_between_chunks_stops_transfer(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "scene.blend"
            source.write_bytes(b"x" * (8 * 1024 * 1024 + 1))
            cancel = threading.Event()
            def request(url, *args, **kwargs):
                if "token" in url:
                    return Response({"access_token": "token"})
                if kwargs.get("method") == "POST":
                    return Response({}, {"Location": "https://upload.test/session"})
                cancel.set()
                raise HTTPError(url, 308, "Resume Incomplete", {"Range": "bytes=0-8388607"}, None)
            with patch.object(transport, "request", side_effect=request):
                with self.assertRaises(transport.Cancelled):
                    transport.Drive("id", "secret", "refresh").upload(source, "folder", cancel=cancel)


if __name__ == "__main__":
    unittest.main()
