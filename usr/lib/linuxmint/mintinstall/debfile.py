#!/usr/bin/python3
# encoding=utf-8
# -*- coding: UTF-8 -*-

"""Reading and installing a local .deb file.

This is UI-free: it only runs dpkg-deb/apt and returns plain data, so it can be
used from a worker thread without touching GTK.
"""

import os
import shutil
import subprocess
import tarfile
import tempfile

ICON_EXTENSIONS = (".png", ".svg", ".xpm")
ICON_SEARCH_DIRS = ("/usr/share/icons/", "/usr/share/pixmaps/")
ICON_TEMP_PREFIX = "mintinstall-deb-icon-"


def read_metadata(path):
    """Read the control fields of a local .deb file. Returns None if it can't be parsed."""
    try:
        result = subprocess.run(["dpkg-deb", "--field", path],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        print("MintInstall: Could not read '%s': %s" % (path, e))
        return None

    if result.returncode != 0:
        print("MintInstall: Could not read '%s': %s" % (path, result.stderr.decode("utf-8", errors="replace").strip()))
        return None

    fields = {}
    current = None

    for line in result.stdout.decode("utf-8", errors="replace").splitlines():
        if line.startswith((" ", "\t")):
            if current is not None:
                fields[current] += "\n" + line.strip()
            continue

        if ":" not in line:
            current = None
            continue

        name, value = line.split(":", 1)
        current = name.strip()
        fields[current] = value.strip()

    if not fields.get("Package") or not fields.get("Version"):
        return None

    return fields


def split_description(description):
    """Split a Debian Description field into its summary and body."""
    if not description:
        return "", ""

    lines = description.splitlines()
    summary = lines[0].strip()

    body = []
    for line in lines[1:]:
        line = line.strip()
        body.append("" if line == "." else line)

    return summary, "\n".join(body).strip()


def find_icon(path, package):
    """Find an icon for the package inside the deb and extract it to a temporary file."""
    candidates = []

    try:
        result = subprocess.run(["dpkg-deb", "--contents", path],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        print("MintInstall: Could not list '%s': %s" % (path, e))
        return None

    for line in result.stdout.decode("utf-8", errors="replace").splitlines():
        if not line.startswith("-"):
            continue

        parts = line.split(None, 5)
        if len(parts) < 6:
            continue

        member = parts[5].strip()
        lowered = member.lower()

        if not lowered.endswith(ICON_EXTENSIONS):
            continue

        if not any(directory in member for directory in ICON_SEARCH_DIRS):
            continue

        basename = os.path.basename(member).rsplit(".", 1)[0]

        if basename == package:
            candidates.insert(0, member)
        elif basename.startswith(package):
            candidates.append(member)

    for member in candidates:
        icon_path = extract_member(path, member)
        if icon_path is not None:
            return icon_path

    return None


def extract_member(path, member):
    """Extract a single file from a deb to a temporary location."""
    wanted = member[2:] if member.startswith("./") else member
    suffix = os.path.splitext(wanted)[1]

    try:
        process = subprocess.Popen(["dpkg-deb", "--fsys-tarfile", path],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError as e:
        print("MintInstall: Could not open '%s': %s" % (path, e))
        return None

    fd, target = tempfile.mkstemp(prefix=ICON_TEMP_PREFIX, suffix=suffix)

    try:
        with tarfile.open(fileobj=process.stdout, mode="r|") as tar:
            for entry in tar:
                if entry.name.lstrip("./") != wanted:
                    continue

                source = tar.extractfile(entry)
                if source is None:
                    break

                with os.fdopen(fd, "wb") as f:
                    f.write(source.read())
                fd = None

                return target
    except (tarfile.TarError, OSError) as e:
        print("MintInstall: Could not extract '%s' from '%s': %s" % (wanted, path, e))
    finally:
        process.stdout.close()
        process.wait()

        if fd is not None:
            os.close(fd)
            remove_temp_file(target)

    return None


def extract_to_directory(path, member, directory):
    """Extract one regular file from a deb into directory, keeping its file name.

    Keeping the real name (and extension) lets the desktop pick the right default
    application for it. Returns the extracted path, or None if the member isn't a
    regular file or can't be extracted. Blocks, so call it from a worker thread.
    """
    def normalize(name):
        while name.startswith("./"):
            name = name[2:]
        return name.rstrip("/")

    wanted = normalize(member)
    basename = os.path.basename(wanted)

    if wanted == "" or basename == "":
        return None

    target = os.path.join(directory, basename)

    try:
        process = subprocess.Popen(["dpkg-deb", "--fsys-tarfile", path],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError as e:
        print("MintInstall: Could not open '%s': %s" % (path, e))
        return None

    extracted = False

    try:
        with tarfile.open(fileobj=process.stdout, mode="r|") as tar:
            for entry in tar:
                if normalize(entry.name) != wanted:
                    continue

                if not entry.isfile():
                    break

                source = tar.extractfile(entry)
                if source is None:
                    break

                with open(target, "wb") as f:
                    shutil.copyfileobj(source, f)

                # It is only a temporary copy of the packaged file.
                os.chmod(target, 0o444)
                extracted = True
                break
    except (tarfile.TarError, OSError) as e:
        print("MintInstall: Could not extract '%s' from '%s': %s" % (wanted, path, e))
    finally:
        process.stdout.close()
        process.kill()
        process.wait()

    return target if extracted else None


def remove_temp_file(path):
    if path is None:
        return

    try:
        os.unlink(path)
    except OSError:
        pass


def list_contents(path):
    """Return (member, size, is_dir) tuples for the contents of a .deb file."""
    try:
        result = subprocess.run(["dpkg-deb", "--contents", path],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        print("MintInstall: Could not list '%s': %s" % (path, e))
        return []

    if result.returncode != 0:
        return []

    entries = []

    for line in result.stdout.decode("utf-8", errors="replace").splitlines():
        parts = line.split(None, 5)

        if len(parts) < 6:
            continue

        permissions = parts[0]
        member = parts[5].strip()

        if member in (".", "./"):
            continue

        # Symlinks are listed as "name -> target".
        if " -> " in member:
            member = member.split(" -> ", 1)[0].strip()

        try:
            size = int(parts[2])
        except ValueError:
            size = 0

        entries.append((member, size, permissions.startswith("d")))

    return entries


def get_unmet_dependencies(path):
    """Return the dependency strings of a local .deb that cannot be satisfied.

    Uses apt's own dependency resolution, so it matches what installing would do.
    """
    try:
        import apt.debfile as apt_debfile
    except ImportError:
        return []

    try:
        deb = apt_debfile.DebPackage(path)
        installable = deb.check()
        failure = getattr(deb, "_failure_string", "") or ""
    except Exception as e:
        print("MintInstall: Could not check the dependencies of '%s': %s" % (path, e))
        return []

    if installable:
        return []

    unmet = []

    for line in failure.splitlines():
        line = line.strip()

        if line.startswith("Dependency is not satisfiable:"):
            unmet.append(line.split(":", 1)[1].strip())

    return unmet


def get_installed_version(package):
    """Return the installed version of a package, or None if it isn't installed."""
    if not package:
        return None

    try:
        result = subprocess.run(["dpkg-query", "-W", "-f=${Status}\t${Version}", package],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=15)
    except (OSError, subprocess.SubprocessError) as e:
        print("MintInstall: Could not query '%s': %s" % (package, e))
        return None

    if result.returncode != 0:
        return None

    status, _, version = result.stdout.decode("utf-8", errors="replace").strip().partition("\t")

    if "install ok installed" not in status:
        return None

    return version.strip() or None


def is_newer(version, installed_version):
    """True if version is newer than installed_version (Debian version rules)."""
    if not version or not installed_version:
        return False

    try:
        result = subprocess.run(["dpkg", "--compare-versions", version, "gt", installed_version],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=15)
    except (OSError, subprocess.SubprocessError) as e:
        print("MintInstall: Could not compare versions: %s" % e)
        return False

    return result.returncode == 0


def _run_apt(arguments):
    env = os.environ.copy()
    env["DEBIAN_FRONTEND"] = "noninteractive"

    try:
        process = subprocess.Popen(["pkexec", "env", "DEBIAN_FRONTEND=noninteractive", "apt-get"] + arguments,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, env=env)
        output = process.communicate()[0].decode("utf-8", errors="replace")
        return process.returncode, output
    except OSError as e:
        return -1, str(e)


def install(path):
    """Install or update a local .deb through apt.

    Blocks until apt finishes, so call it from a worker thread.
    Returns (returncode, combined_output).
    """
    return _run_apt(["install", "-y", path])


def remove(package):
    """Remove the installed package through apt.

    Blocks until apt finishes, so call it from a worker thread.
    Returns (returncode, combined_output).
    """
    return _run_apt(["remove", "-y", package])
