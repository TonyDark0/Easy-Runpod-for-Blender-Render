import json
import os
import shutil
from urllib.parse import urlencode
from urllib.request import Request, urlopen

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

    def upload(self, path, parent, name=None):
        token = self.token()
        size = os.path.getsize(path)
        with request(UPLOAD + "?uploadType=resumable", token, method="POST",
                     data=json.dumps(dict(name=name or os.path.basename(path),
                                          parents=[parent])).encode(),
                     headers={"Content-Type": "application/json",
                              "X-Upload-Content-Length": str(size)}) as response:
            location = response.headers["Location"]
        with open(path, "rb") as source:
            with request(location, method="PUT", data=source,
                         headers={"Content-Length": str(size)}) as response:
                return json.load(response)["id"]

    def status_file(self, file_id, payload):
        return api(UPLOAD + "/" + file_id + "?uploadType=media",
                   self.token(), payload, method="PATCH")

    def read_status(self, file_id):
        return api(DRIVE + "/" + file_id + "?alt=media", self.token())

    def download(self, file_id, path):
        with request(DRIVE + "/" + file_id + "?alt=media", self.token()) as response:
            with open(path, "wb") as target:
                shutil.copyfileobj(response, target)
