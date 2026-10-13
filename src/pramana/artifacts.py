"""Private, immutable, content-addressed artifacts with atomic publication."""

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from .contracts import canonical, identifier


def private_dir(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Runtime directories must not be symlinks")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def consumer_root(root, consumer):
    root = private_dir(root)
    return private_dir(private_dir(root / "consumers") / identifier(consumer))


class ArtifactStore:
    def __init__(self, root):
        self.root = private_dir(root)
        self.blobs = private_dir(self.root / "blobs")
        self.tmp = private_dir(self.root / "tmp")

    def put(self, data):
        key = hashlib.sha256(data).hexdigest()
        destination = self.blobs / key
        if destination.exists():
            self.get(key)
            return key
        fd, name = tempfile.mkstemp(dir=self.tmp)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, destination)
            directory = os.open(self.blobs, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(name):
                os.unlink(name)
        return key

    def put_json(self, value):
        return self.put(canonical(value))

    def get(self, key):
        if not re.fullmatch(r"[a-f0-9]{64}", key):
            raise ValueError("Invalid artifact hash")
        path = self.blobs / key
        if path.is_symlink():
            raise ValueError("Artifact symlinks are forbidden")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != key:
            raise ValueError("Corrupt artifact")
        return data

    def get_json(self, key):
        return json.loads(self.get(key))
