import json
import os
import shutil
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class Cancelled(RuntimeError):
    pass


def check_cancel(event):
    if event is not None and event.is_set():
        raise Cancelled("Process cancelled. Completed uploads were preserved.")

DRIVE = "https://www.googleapis.com/drive/v3/files"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"


def request(url, token="", *, method="GET", data=None, headers=None):
    headers = dict(headers or {})
    if token:
        headers["Authorization"] = "Bearer " + token
    return urlopen(Request(url, data=data, headers=headers, method=method), timeout=120)


def api(url, token="", payload=None, method=None):
    body = None if payload is None else json.dumps(payload).encode()
    with request(url, token, method=method or ("POST" if body else "GET"),
                 data=body, headers={"Content-Type": "application/json"}) as response:
        return json.load(response)


class Drive:
    def __init__(self, client_id, client_secret, refresh_token):
        self.credentials = dict(client_id=client_id, client_secret=client_secret,
                                refresh_token=refresh_token, grant_type="refresh_token")

    def token(self):
        with request("https://oauth2.googleapis.com/token", method="POST",
                     data=urlencode(self.credentials).encode(),
                     headers={"Content-Type": "application/x-www-form-urlencoded"}) as response:
            return json.load(response)["access_token"]

    def folder(self, name, parent):
        return api(DRIVE, self.token(), dict(name=name, parents=[parent],
                   mimeType="application/vnd.google-apps.folder"))["id"]

    def unique_folder(self, name, parent):
        token = self.token()
        query = f"'{parent}' in parents and trashed = false and mimeType = 'application/vnd.google-apps.folder'"
        params = dict(q=query, fields="nextPageToken,files(name)", pageSize=1000)
        names = set()
        while True:
            page = api(DRIVE + "?" + urlencode(params), token)
            names.update(folder["name"] for folder in page.get("files", []))
            if not page.get("nextPageToken"):
                break
            params["pageToken"] = page["nextPageToken"]
        candidate = name
        suffix = 2
        while candidate in names:
            candidate = f"{name} ({suffix})"
            suffix += 1
        return self.folder(candidate, parent)

    def upload(self, path, parent, name=None, cancel=None):
        check_cancel(cancel)
        token = self.token()
        size = os.path.getsize(path)
        with request(UPLOAD + "?uploadType=resumable", token, method="POST",
                     data=json.dumps(dict(name=name or os.path.basename(path),
                                          parents=[parent])).encode(),
                     headers={"Content-Type": "application/json",
                              "X-Upload-Content-Length": str(size)}) as response:
            location = response.headers["Location"]
        from urllib.error import HTTPError
        with open(path, "rb") as source:
            offset = 0
            while offset < size:
                check_cancel(cancel)
                chunk = source.read(8 * 1024 * 1024)
                end = offset + len(chunk) - 1
                try:
                    with request(location, method="PUT", data=chunk,
                                 headers={"Content-Length": str(len(chunk)),
                                          "Content-Range": f"bytes {offset}-{end}/{size}"}) as response:
                        return json.load(response)["id"]
                except HTTPError as error:
                    if error.code != 308:
                        raise
                    confirmed = error.headers.get("Range", "")
                    if confirmed != f"bytes=0-{end}":
                        raise RuntimeError("Drive upload did not confirm the expected bytes") from error
                offset = end + 1
        raise RuntimeError("Drive did not confirm the completed upload")

    def status_file(self, file_id, payload):
        return api(UPLOAD + "/" + file_id + "?uploadType=media",
                   self.token(), payload, method="PATCH")

    def read_status(self, file_id):
        return api(DRIVE + "/" + file_id + "?alt=media", self.token())

    def download(self, file_id, path):
        with request(DRIVE + "/" + file_id + "?alt=media", self.token()) as response:
            with open(path, "wb") as target:
                shutil.copyfileobj(response, target)
