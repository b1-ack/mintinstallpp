#!/usr/bin/python3
# encoding=utf-8

# Writes APT sources files as root, for mintinstall.
#
# The application sends every changed file at once as a JSON document on
# stdin, so the user is asked for authorization only once per save:
#
#     {"files": [{"path": "/etc/apt/sources.list", "data": "<base64>"}, ...]}
#
# Files are replaced atomically and keep their permissions.  Only files below
# /etc/apt are accepted.

import base64
import json
import os
import sys
import tempfile

ALLOWED_ROOT = "/etc/apt"


def allowed(path):
    if not path or not os.path.isabs(path):
        return False

    root = os.path.realpath(ALLOWED_ROOT)
    real = os.path.realpath(path)
    return real == root or real.startswith(root + os.sep)


def write_file(path, data):
    directory = os.path.dirname(path)

    mode = 0o644
    try:
        mode = os.stat(path).st_mode & 0o777
    except OSError:
        pass

    handle, temporary = tempfile.mkstemp(dir=directory, prefix=".mintinstall-")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def main():
    try:
        request = json.load(sys.stdin)
    except ValueError as error:
        sys.stderr.write("%s\n" % error)
        return 1

    errors = []
    for entry in request.get("files", []):
        path = entry.get("path", "")
        if not allowed(path):
            errors.append("%s: %s" % (path, "invalid path"))
            continue

        try:
            data = base64.b64decode(entry.get("data", ""))
            write_file(path, data)
        except (OSError, ValueError) as error:
            errors.append("%s: %s" % (path, error))

    if errors:
        sys.stderr.write("\n".join(errors))
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
