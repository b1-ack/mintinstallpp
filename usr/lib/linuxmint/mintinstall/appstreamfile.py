#!/usr/bin/python3
# encoding=utf-8
# -*- coding: UTF-8 -*-

"""Reading a local AppStream component file (.metainfo.xml / .appdata.xml).

UI-free: returns plain data that the package page displays.
"""

import os
import re
import shutil
import subprocess
import urllib.parse

from xml.etree import ElementTree as ET

from mintcommon.installer import installer as mint_installer

XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def read_metadata(path, locale):
    """Parse an AppStream component file. Returns None if it isn't one."""
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as e:
        print("MintInstall: Could not read '%s': %s" % (path, e))
        return None

    if root.tag.rsplit("}", 1)[-1] != "component":
        print("MintInstall: '%s' is not an AppStream component file." % path)
        return None

    def pick(nodes):
        fallback = ""

        for node in nodes:
            value = "".join(node.itertext()).strip()

            if value == "":
                continue

            lang = node.get(XML_LANG)

            if lang is None:
                if fallback == "":
                    fallback = value
            elif lang.replace("_", "-").split("-")[0] == locale:
                return value

        return fallback

    def first_text(tag):
        node = root.find(tag)

        if node is None:
            return ""

        return " ".join("".join(node.itertext()).split())

    description_parts = []
    description_node = root.find("description")

    if description_node is not None:
        for child in description_node:
            tag = child.tag.rsplit("}", 1)[-1]

            if tag in ("p", "li"):
                value = " ".join("".join(child.itertext()).split())

                if value != "":
                    description_parts.append(("\u2022 " if tag == "li" else "") + value)
            elif tag in ("ul", "ol"):
                for item in child:
                    value = " ".join("".join(item.itertext()).split())

                    if value != "":
                        description_parts.append("\u2022 " + value)

    homepage = ""

    for url_node in root.findall("url"):
        if url_node.get("type") == "homepage":
            homepage = "".join(url_node.itertext()).strip()
            break

    developer = pick(root.findall("developer_name"))

    if developer == "":
        developer = first_text("developer/name")

    icon_path = None
    icon_name = None

    for icon_node in root.findall("icon"):
        icon_type = icon_node.get("type")
        value = (icon_node.text or "").strip()

        if value == "":
            continue

        if icon_type == "local" and os.path.isfile(value):
            icon_path = value
            break

        if icon_type in ("stock", "cached") and icon_name is None:
            icon_name = value

    if icon_name is not None and icon_name.endswith(".png"):
        icon_name = icon_name[:-4]

    component_id = first_text("id")
    pkg_names = []

    pkgname = first_text("pkgname")

    if pkgname != "":
        pkg_names.append(pkgname)

    for binary_node in root.findall("provides/binary"):
        value = (binary_node.text or "").strip()

        if value != "" and value not in pkg_names:
            pkg_names.append(value)

    candidates = [component_id]

    if component_id.endswith(".desktop"):
        candidates.append(component_id[:-len(".desktop")])

    for candidate in candidates:
        if candidate != "" and candidate not in pkg_names:
            pkg_names.append(candidate)

    bundle_node = root.find("bundle")
    bundle_ref = ""

    if bundle_node is not None and bundle_node.get("type") == "flatpak":
        bundle_ref = (bundle_node.text or "").strip()

    version = ""
    release_node = root.find("releases/release")

    if release_node is not None:
        version = release_node.get("version", "")

    if version == "":
        version = root.get("version", "")

    return {
        "id": component_id,
        "name": pick(root.findall("name")) or component_id,
        "summary": pick(root.findall("summary")),
        "description": "\n".join(description_parts),
        "developer": developer,
        "homepage": homepage,
        "license": first_text("project_license"),
        "version": version,
        "icon_path": icon_path,
        "icon_name": icon_name,
        "pkg_names": pkg_names,
        "bundle_ref": bundle_ref,
    }


def _parse_appstream_arg(raw_arg):
    """Clean an appstream:// URI or component id into a normalized id and
    a list of candidate names, using the same logic as b1ack.appstream-remove.
    Returns (clean_id, candidates) where candidates is a list of names to try."""
    unquoted = urllib.parse.unquote(raw_arg.strip())

    if unquoted.startswith("file://"):
        unquoted = unquoted[7:]

    clean = re.sub(r'^appstream:/*/*', '', unquoted).strip('/')
    clean = clean.split('?')[0].split('#')[0].strip()

    if not clean:
        return ("", [])

    base = os.path.basename(clean)
    name_no_ext = re.sub(r'\.desktop$', '', base)
    desktop_name = "%s.desktop" % name_no_ext

    candidates = [desktop_name, name_no_ext, base]
    if base != desktop_name and not base.endswith(".desktop"):
        candidates.append("%s.desktop" % base)

    # Last dotted segment (org.gnome.Nautilus -> Nautilus)
    if "." in name_no_ext:
        last_part = name_no_ext.split(".")[-1]
        candidates.extend([last_part, "%s.desktop" % last_part, last_part.lower()])

    # Full path without .desktop suffix and lowered last segment
    candidates.append(name_no_ext.lower())

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            unique.append(c)

    return (clean, unique)


def _desktop_dirs():
    """Return the application directories to search, most specific first."""
    user_app_dir = os.path.join(
        os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"),
        "applications"
    )
    user_dirs = [
        user_app_dir,
        os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
    ]

    global_dirs = ["/usr/share/applications"]
    data_dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    for d in data_dirs.split(":"):
        if d:
            global_dirs.append(os.path.join(d, "applications"))
    global_dirs.extend([
        "/var/lib/flatpak/exports/share/applications",
        "/usr/local/share/applications",
        "/var/lib/snapd/desktop/applications",
    ])

    seen = set()
    ordered = []
    for d in global_dirs + user_dirs:
        norm = os.path.normpath(d)
        if norm not in seen and os.path.isdir(norm):
            seen.add(norm)
            ordered.append(norm)

    return ordered


def _find_desktop_file(candidates):
    """Search desktop files in standard directories, similar to b1ack.appstream-remove."""
    ordered = _desktop_dirs()

    # Exact name match
    for d in ordered:
        for c in candidates:
            p = os.path.join(d, c)
            if os.path.isfile(p):
                return p
            if not c.endswith(".desktop"):
                p2 = os.path.join(d, c + ".desktop")
                if os.path.isfile(p2):
                    return p2

    # Case-insensitive match
    for d in ordered:
        try:
            entries = os.listdir(d)
        except OSError:
            continue
        for c in candidates:
            c_lower = c.lower()
            for entry in entries:
                if entry.lower() == c_lower or entry.lower() == c_lower + ".desktop":
                    full_p = os.path.join(d, entry)
                    if os.path.isfile(full_p):
                        return full_p

    # Flatpak content match
    for d in ordered:
        try:
            entries = os.listdir(d)
        except OSError:
            continue
        for entry in entries:
            if not entry.endswith(".desktop"):
                continue
            p = os.path.join(d, entry)
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read(4096)
                    for c in candidates:
                        c_no_ext = re.sub(r'\.desktop$', '', c)
                        if ("X-Flatpak=%s" % c_no_ext) in content or ("flatpak run %s" % c_no_ext) in content:
                            return p
            except OSError:
                continue

    return None


def _read_desktop_file(path):
    """Return the keys of the [Desktop Entry] group of a desktop file."""
    entry = {}

    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            in_entry = False

            for line in f:
                line = line.strip()

                if line.startswith("[") and line.endswith("]"):
                    in_entry = line == "[Desktop Entry]"
                    continue

                if not in_entry or line.startswith("#") or "=" not in line:
                    continue

                key, _, value = line.partition("=")
                entry[key.strip()] = value.strip()
    except OSError:
        pass

    return entry


def _name_variants(value):
    """Turn a display or file name into package-name-like spellings.

    'AstralRinth App' gives 'astral-rinth-app', which is how names that differ
    from the package name (spaces, capitals) still find the package."""
    value = re.sub(r'\.desktop$', '', value.strip())

    if value == "":
        return []

    spaced = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', value)
    slug = re.sub(r'[^a-z0-9]+', '-', spaced.lower()).strip('-')
    compact = re.sub(r'[^a-z0-9]+', '', value.lower())

    variants = []

    for variant in (slug, compact):
        if variant != "" and variant not in variants:
            variants.append(variant)

    return variants


def _dpkg_owner(path):
    """Return the Debian package that ships a file, if any."""
    try:
        result = subprocess.run(["dpkg", "-S", path],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL,
                                timeout=10,
                                universal_newlines=True)
    except (OSError, subprocess.SubprocessError):
        return None

    if result.returncode != 0:
        return None

    for line in result.stdout.splitlines():
        owner, sep, _path = line.rpartition(": ")

        if sep:
            # Multi-arch packages are listed as 'name:arch'.
            return owner.split(":")[0].strip() or None

    return None


def _package_names_for_desktop(desktop_path):
    """Candidate catalog names for a desktop file."""
    names = []

    def add(name):
        if name and name not in names:
            names.append(name)

    entry = _read_desktop_file(desktop_path)
    exec_line = entry.get("Exec", "")

    flatpak_id = entry.get("X-Flatpak", "")
    match = re.search(r'flatpak\s+(?:run\s+)?([^\s]+)', exec_line)

    if flatpak_id == "" and match is not None:
        flatpak_id = match.group(1)

    add(flatpak_id)

    # The package owning the desktop file is the most reliable answer, e.g.
    # 'AstralRinth App.desktop' -> 'astral-rinth-app'.
    add(_dpkg_owner(desktop_path))

    command = exec_line.split()[0] if exec_line.strip() != "" else ""
    command = os.path.basename(command)

    if command != "":
        add(_dpkg_owner(shutil.which(command) or os.path.join("/usr/bin", command)))

    for value in (entry.get("Name", ""), os.path.basename(desktop_path), command):
        for variant in _name_variants(value):
            add(variant)

    return names


def find_pkginfo_by_id(installer, component_id):
    """Look up the catalog package behind an AppStream id (appstream:// links).

    Uses the same URI parsing and candidate-generation logic as
    b1ack.appstream-remove to handle cases where the desktop file name
    differs from the component id or lives in a user-local directory."""
    clean_id, candidates = _parse_appstream_arg(component_id)

    if not clean_id:
        return None

    try:
        # 1. Try each candidate as a Flatpak package name (exact match).
        for name in candidates:
            name_no_ext = re.sub(r'\.desktop$', '', name)
            for try_name in (name_no_ext, name):
                pkginfo = installer.find_pkginfo(try_name, mint_installer.PKG_TYPE_FLATPAK)
                if pkginfo is not None:
                    return pkginfo

        # 2. Try each candidate as an APT package name.
        tried_apt = set()
        for name in candidates:
            name_no_ext = re.sub(r'\.desktop$', '', name)
            try_names = [name_no_ext, name_no_ext.lower(), name]
            try_names.extend(_name_variants(name))

            for try_name in try_names:
                if try_name in tried_apt:
                    continue
                tried_apt.add(try_name)
                pkginfo = installer.find_pkginfo(try_name, mint_installer.PKG_TYPE_APT)
                if pkginfo is not None:
                    return pkginfo

        # 3. Read the desktop file itself - its owning package, its Flatpak id
        #    or the names it uses - then look that up in the catalog.
        desktop_path = _find_desktop_file(candidates)

        if desktop_path is not None:
            for name in _package_names_for_desktop(desktop_path):
                for pkg_type in (mint_installer.PKG_TYPE_APT, mint_installer.PKG_TYPE_FLATPAK):
                    pkginfo = installer.find_pkginfo(name, pkg_type)

                    if pkginfo is not None:
                        return pkginfo

    except Exception as e:
        print("MintInstall: Could not look up '%s' in the catalog: %s" % (component_id, e))

    return None


def find_pkginfo(installer, metadata):
    """Look the component up in the catalog, so its regular package page can be shown."""
    try:
        for name in metadata.get("pkg_names", []):
            pkginfo = installer.find_pkginfo(name, mint_installer.PKG_TYPE_APT)

            if pkginfo is not None:
                return pkginfo

        bundle_ref = metadata.get("bundle_ref", "")

        if bundle_ref != "":
            pkginfo = installer.find_pkginfo(bundle_ref, mint_installer.PKG_TYPE_FLATPAK)

            if pkginfo is not None:
                return pkginfo
    except Exception as e:
        print("MintInstall: Could not look up the AppStream component in the catalog: %s" % e)

    return None
