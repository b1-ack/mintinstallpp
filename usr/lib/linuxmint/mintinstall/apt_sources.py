#!/usr/bin/python3
# encoding=utf-8

# Graphical configuration of the APT software sources.
#
# Both one-line files (/etc/apt/sources.list, /etc/apt/sources.list.d/*.list)
# and deb822 files (/etc/apt/sources.list.d/*.sources) are shown and edited in
# the same way.  Only the values that the user actually changed are written
# back, everything else in the files is preserved byte for byte.

import gettext
import os
import re
import subprocess

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, GObject, Gtk, Pango

_ = gettext.gettext

SOURCES_DIR = "/etc/apt/sources.list.d"
MAIN_LIST = "/etc/apt/sources.list"
MINTINSTALL_LIST = os.path.join(SOURCES_DIR, "mintinstall.list")

KEYRING_DIRS = [
    "/etc/apt/keyrings",
    "/usr/share/keyrings",
    "/usr/local/share/keyrings",
    "/etc/apt/trusted.gpg.d",
]
TRUSTED_KEYRING = "/etc/apt/trusted.gpg"

# Schemes offered in the drop-down list. The user never has to type them.
SCHEMES = ["http", "https", "ftp", "sftp", "file", "cdrom", "copy"]

# Tokens which are too generic to identify the repository a key belongs to.
GENERIC_TOKENS = frozenset((
    "deb", "debs", "debian", "ubuntu", "linux", "mint", "os", "www", "com",
    "org", "net", "edu", "info", "io", "dev", "key", "keys", "keyring",
    "keyrings", "gpg", "asc", "pgp", "archive", "archives", "pool", "dists",
    "repo", "repos", "repository", "mirror", "mirrors", "snapshot", "stable",
    "automatic", "security", "release", "signing", "source", "sources", "main",
    "all", "amd64", "i386", "arm64", "armhf", "noarch", "current", "updates",
    "backports", "debug", "the",
))

# Distribution names are useful when matching keys to repositories even though
# they are too generic for the name/uid heuristic.  Debian publishes a handful
# of keyrings (bookworm, trixie, ...) and all of them belong to Debian mirrors.
MATCH_GENERIC_TOKENS = GENERIC_TOKENS - frozenset(("debian", "ubuntu"))
MATCH_GENERIC_TOKENS = MATCH_GENERIC_TOKENS | frozenset(("trusted",))


def match_tokens(text):
    return set(
        token for token in re.split(r"[^a-z0-9+]+", text.lower())
        if len(token) >= 3 and token not in MATCH_GENERIC_TOKENS)

# Component names, used to find where the suite ends and the components start.
KNOWN_COMPONENTS = frozenset((
    "main", "contrib", "non-free", "non-free-firmware", "universe",
    "multiverse", "restricted", "partner", "free", "nonfree",
))

# APT one-line option -> deb822 field
FLAG_FIELDS = {
    "trusted": "Trusted",
    "arch": "Architectures",
    "signed-by": "Signed-By",
    "lang": "Languages",
    "target": "Targets",
    "pdiffs": "PDiffs",
    "by-hash": "By-Hash",
    "allow-insecure": "Allow-Insecure",
    "allow-weak": "Allow-Weak",
    "check-valid-until": "Check-Valid-Until",
    "valid-until-min": "Valid-Until-Min",
    "valid-until-max": "Valid-Until-Max",
    "date-max-future": "Date-Max-Future",
    "inrelease-path": "InRelease-Path",
    "check-date": "Check-Date",
}

FIELD_FLAGS = dict((field.lower(), flag) for flag, field in FLAG_FIELDS.items())

MANAGED_FIELDS = frozenset((
    "types", "uris", "suites", "components", "enabled",
)) | frozenset(FIELD_FLAGS.keys())

CANONICAL_FIELDS = {
    "types": "Types",
    "uris": "URIs",
    "suites": "Suites",
    "components": "Components",
    "enabled": "Enabled",
    "signed-by": "Signed-By",
    "architectures": "Architectures",
    "trusted": "Trusted",
    "languages": "Languages",
    "targets": "Targets",
    "pdiffs": "PDiffs",
    "by-hash": "By-Hash",
    "allow-insecure": "Allow-Insecure",
    "allow-weak": "Allow-Weak",
    "check-valid-until": "Check-Valid-Until",
    "valid-until-min": "Valid-Until-Min",
    "valid-until-max": "Valid-Until-Max",
    "date-max-future": "Date-Max-Future",
    "inrelease-path": "InRelease-Path",
    "check-date": "Check-Date",
    "comment": "Comment",
}

# Suggestions shown while typing the value of a flag.
FLAG_HINTS = {
    "trusted": "yes",
    "arch": "amd64",
    "lang": "en",
    "target": "Packages",
    "pdiffs": "yes",
    "by-hash": "yes",
    "allow-insecure": "yes",
    "allow-weak": "yes",
    "check-valid-until": "no",
    "valid-until-min": "0",
    "valid-until-max": "0",
    "date-max-future": "0",
}


def canonical_field(name):
    return CANONICAL_FIELDS.get(name.lower(), name)


def split_uri(uri):
    m = re.match(r"^([A-Za-z][A-Za-z0-9+.\-]*):(?://)?(.*)$", uri)
    if m is None:
        return "", "", uri

    scheme = m.group(1)
    separator = "//" if uri[len(scheme) + 1:].startswith("//") else ""

    return scheme, separator, m.group(2)


def parse_flags(text):
    flags = {}
    for token in text.split():
        name, separator, value = token.partition("=")
        if not name:
            continue
        flags[name] = value if separator else None

    return flags


def format_flags(flags):
    parts = []
    for name, value in flags.items():
        if value is None:
            parts.append(name)
        else:
            parts.append("%s=%s" % (name, value))

    return " ".join(parts)


def split_words(value):
    return value.split()


_css_provider = None

CSS = b"""
.sources-scheme button {
    border-radius: 8px;
    min-height: 22px;
    padding: 1px 10px;
}
.source-row {
    background-color: @theme_base_color;
    border: 1px solid @borders;
    border-radius: 3px;
}
.sources-scroll scrollbar {
    opacity: 0;
    transition: opacity 160ms ease-in-out;
}
.sources-scroll scrollbar:hover {
    opacity: 1;
}
"""


def install_css():
    """Installs the small style sheet used by the sources page once."""
    global _css_provider

    if _css_provider is not None:
        return

    screen = Gdk.Screen.get_default()
    if screen is None:
        return

    provider = Gtk.CssProvider()
    try:
        provider.load_from_data(CSS)
    except GLib.Error:
        return

    Gtk.StyleContext.add_provider_for_screen(
        screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    _css_provider = provider


class AptSource:
    """A single repository entry, either a one-line entry or a deb822 stanza."""

    def __init__(self, path, kind, raw):
        self.path = path
        self.kind = kind # "list" or "sources"
        self.raw = raw

        self.enabled = True
        self.types = ["deb"]
        self.uri_scheme = "http"
        self.uri_separator = "//"
        self.address = ""
        self.suite = ""
        self.components = []
        self.flags = {}

        # one-line format
        self.commented_prefix = ""

        # deb822 format
        self.fields = {}
        self.field_order = []

        self._original = None
        self._original_suite_words = 1
        self.is_new = False

    @property
    def full_uri(self):
        if not self.uri_scheme:
            return self.address

        return "%s:%s%s" % (self.uri_scheme, self.uri_separator, self.address)

    def is_src_only(self):
        return bool(self.types) and all(kind == "deb-src" for kind in self.types)

    def is_deb_only(self):
        return bool(self.types) and all(kind == "deb" for kind in self.types)

    def has_source_type(self):
        return "deb-src" in self.types

    def set_codename(self, text):
        self.suite = text.strip()

    def set_components_text(self, text):
        self.components = text.split()

    def clone_as(self, source_type):
        clone = AptSource(self.path, self.kind, "\n" if self.kind == "list" else "")
        clone.enabled = True
        clone.types = [source_type]
        clone.uri_scheme = self.uri_scheme
        clone.uri_separator = self.uri_separator
        clone.address = self.address
        clone.suite = self.suite
        clone.components = list(self.components)
        clone.flags = dict(self.flags)
        clone.is_new = self.kind == "list"
        clone._take_snapshot()

        if self.kind == "sources":
            clone.fields = dict(self.fields)
            clone.field_order = list(self.field_order)
            clone._original = dict(self._original)
            clone._original["types"] = list(self.types)
            clone.types = [source_type]
            clone.is_new = False

        return clone

    def suite_text(self):
        words = []
        if self.suite:
            words.append(self.suite)
        words.extend(self.components)

        return " ".join(words)

    def set_suite_text(self, text):
        words = text.split()
        if not words:
            self.suite = ""
            self.components = []
            return

        # Keep the original suite/components split as long as the number of
        # words doesn't change, so multi-suite repositories survive an edit.
        boundary = None
        if len(words) == self._original_suite_words + len(self.components or []):
            boundary = self._original_suite_words

        if boundary is None:
            boundary = 1
            for index, word in enumerate(words[1:], start=1):
                if word.lower() in KNOWN_COMPONENTS:
                    boundary = index
                    break

        self.suite = " ".join(words[:boundary])
        self.components = words[boundary:]

    def changed(self):
        if self._original is None or self.is_new:
            return True

        return (self.enabled != self._original["enabled"]
                or self.types != self._original["types"]
                or self.full_uri != self._original["uri"]
                or self.suite != self._original["suite"]
                or self.components != self._original["components"]
                or self.flags != self._original["flags"])

    def _take_snapshot(self):
        self._original = {
            "enabled": self.enabled,
            "types": list(self.types),
            "uri": self.full_uri,
            "suite": self.suite,
            "components": list(self.components),
            "flags": dict(self.flags),
        }
        self._original_suite_words = len(self.suite.split()) if self.suite else 1

    # --- one-line format ---------------------------------------------------

    def parse_list_line(self, line):
        match = LIST_LINE_RE.match(line.rstrip("\n"))
        if match is None:
            return False

        prefix = match.group("prefix")
        self.commented_prefix = prefix if "#" in prefix else ""
        self.enabled = "#" not in prefix
        self.types = [match.group("type")]

        flags = match.group("flags")
        self.flags = parse_flags(flags) if flags else {}

        self.uri_scheme, self.uri_separator, self.address = split_uri(match.group("uri"))

        words = match.group("suite").split()
        self.suite = words[0] if words else ""
        components = match.group("components") or ""
        self.components = components.split()

        self._take_snapshot()

        return True

    def render_list_line(self):
        prefix = "" if self.enabled else (self.commented_prefix or "# ")

        line = "%s%s" % (prefix, " ".join(self.types))

        flags = format_flags(self.flags)
        if flags:
            line += " [%s]" % flags

        line += " " + self.full_uri

        if self.suite:
            line += " " + self.suite

        if self.components:
            line += " " + " ".join(self.components)

        if self.raw.endswith("\n"):
            line += "\n"

        return line

    # --- deb822 format -----------------------------------------------------

    def parse_stanza(self, lines):
        fields = {}
        order = []
        current = None

        for line in lines:
            text = line.rstrip("\n")
            if text[:1] in (" ", "\t") and current is not None:
                fields[current] = fields[current] + "\n" + text
                continue

            match = DEB822_FIELD_RE.match(text)
            if match is None:
                current = None
                continue

            name = canonical_field(match.group(1))
            current = name
            fields[name] = match.group(2).strip()
            if name not in order:
                order.append(name)

        self.fields = fields
        self.field_order = order

        self.types = fields.get("Types", "deb").split() or ["deb"]

        uris = fields.get("URIs", "").split()
        self.uri_scheme, self.uri_separator, self.address = split_uri(uris[0] if uris else "")

        self.suite = fields.get("Suites", "").strip()
        self.components = fields.get("Components", "").split()

        enabled = fields.get("Enabled", "yes").strip().lower()
        self.enabled = enabled not in ("no", "false", "0", "off")

        self.flags = {}
        for name in order:
            flag = FIELD_FLAGS.get(name.lower())
            if flag is None:
                continue
            self.flags[flag] = fields[name].strip() or None

        self._take_snapshot()

        return self.address != "" or self.suite != ""

    def render_stanza(self):
        fields = dict(self.fields)
        order = list(self.field_order)

        def set_field(name, value):
            fields[name] = value
            if name not in order:
                order.append(name)

        def drop_field(name):
            fields.pop(name, None)
            while name in order:
                order.remove(name)

        if self.full_uri != self._original["uri"]:
            set_field("URIs", self.full_uri)

        if self.types != self._original["types"]:
            set_field("Types", " ".join(self.types))

        if self.suite != self._original["suite"]:
            set_field("Suites", self.suite)

        if self.components != self._original["components"]:
            if self.components:
                set_field("Components", " ".join(self.components))
            else:
                drop_field("Components")

        if self.enabled != self._original["enabled"]:
            set_field("Enabled", "yes" if self.enabled else "no")

        if self.flags != self._original["flags"]:
            for name in FLAG_FIELDS.values():
                drop_field(name)
            for flag, value in self.flags.items():
                name = FLAG_FIELDS.get(flag)
                if name is None:
                    continue
                set_field(name, "yes" if value is None else str(value))

        lines = []
        for name in order:
            if name not in fields:
                continue
            value = fields[name]
            # A field whose value starts on the next line keeps its layout
            if value.startswith("\n"):
                lines.append("%s:%s" % (name, value))
            else:
                lines.append("%s: %s" % (name, value))

        text = "\n".join(lines)
        if self.raw.endswith("\n"):
            text += "\n"

        return text

    def render(self):
        if not self.changed():
            return self.raw

        if self.kind == "list":
            return self.render_list_line()

        return self.render_stanza()


LIST_LINE_RE = re.compile(
    r"^(?P<prefix>[ \t]*(?:#[ \t]*)*)(?P<type>deb|deb-src)[ \t]+"
    r"(?:\[(?P<flags>[^\]]*)\][ \t]+)?"
    r"(?P<uri>\S+)[ \t]+(?P<suite>\S+)(?:[ \t]+(?P<components>[^#]*?))?[ \t]*$"
)

DEB822_FIELD_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9-]*):[ \t]*(.*)$")


class SourcesFile:
    """One sources file, kept as an ordered list of raw text and stanzas."""

    def __init__(self, path):
        self.path = path
        self.kind = "sources" if path.endswith(".sources") else "list"
        self.chunks = []
        self.sources = []
        self._removed = False
        self.load()

    def load(self):
        if not os.path.isfile(self.path):
            self.chunks = []
            self.sources = []
            return

        with open(self.path, "r", encoding="utf-8", errors="surrogateescape") as stream:
            text = stream.read()

        self.chunks = []
        self.sources = []

        if self.kind == "list":
            for line in text.splitlines(True):
                if LIST_LINE_RE.match(line.rstrip("\n")):
                    source = AptSource(self.path, "list", line)
                    if source.parse_list_line(line):
                        self.chunks.append(source)
                        self.sources.append(source)
                        continue
                self.chunks.append(line)
        else:
            pending = []
            block = []

            def flush_block():
                if not block:
                    return
                raw = "".join(block)
                source = AptSource(self.path, "sources", raw)
                if source.parse_stanza(block):
                    self.chunks.append(source)
                    self.sources.append(source)
                else:
                    self.chunks.append(raw)

            for line in text.splitlines(True):
                stripped = line.strip()
                if not stripped:
                    flush_block()
                    block = []
                    pending.append(line)
                    continue

                if line.lstrip().startswith("#"):
                    flush_block()
                    block = []
                    pending.append(line)
                    continue

                if pending:
                    self.chunks.append("".join(pending))
                    pending = []
                block.append(line)

            flush_block()
            if pending:
                self.chunks.append("".join(pending))

    def changed(self):
        return (self._removed
                or any(source.changed() for source in self.sources))

    def append_source(self, source):
        if self.chunks:
            last = self.chunks[-1]
            if isinstance(last, str):
                if last and not last.endswith("\n"):
                    self.chunks.append("\n")
            elif not last.raw.endswith("\n"):
                self.chunks.append("\n")

        self.chunks.append(source)
        self.sources.append(source)

    def remove_source(self, source):
        if source in self.chunks:
            self.chunks.remove(source)
        if source in self.sources:
            self.sources.remove(source)

        if not source.is_new:
            self._removed = True

    def render(self):
        return "".join(chunk if isinstance(chunk, str) else chunk.render() for chunk in self.chunks)


def load_sources_files():
    paths = []
    if os.path.isfile(MAIN_LIST):
        paths.append(MAIN_LIST)

    try:
        for name in sorted(os.listdir(SOURCES_DIR)):
            if name.endswith((".list", ".sources")):
                paths.append(os.path.join(SOURCES_DIR, name))
    except OSError:
        pass

    files = []
    for path in paths:
        try:
            files.append(SourcesFile(path))
        except (OSError, UnicodeError):
            continue

    return files


class AptKey:
    def __init__(self, path):
        self.path = path
        self.name = os.path.basename(path)
        self.stem, self.extension = os.path.splitext(self.name)
        self.extension = self.extension.lstrip(".").lower() or "key"
        self.uid = None
        self.fingerprints = []
        self._tokens = None
        self._describe()

    def _describe(self):
        if not os.path.isfile(self.path) or os.path.getsize(self.path) == 0:
            return

        try:
            result = subprocess.run(
                ["gpg", "--batch", "--with-colons", "--show-keys",
                 "--no-default-keyring", self.path],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=10)
        except (OSError, subprocess.SubprocessError):
            return

        for line in result.stdout.decode("utf-8", "replace").splitlines():
            parts = line.split(":")
            if len(parts) < 10:
                continue
            if parts[0] == "fpr":
                self.fingerprints.append(parts[9])
            elif parts[0] == "uid" and self.uid is None:
                self.uid = parts[9]

    @property
    def display_name(self):
        # A keyring which bundles several keys is better described by its file
        if self.uid and len(self.fingerprints) <= 1:
            return self.uid

        return self.stem

    @property
    def label(self):
        return "%s: %s" % (self.extension, self.display_name)

    def tokens(self):
        if self._tokens is None:
            # The file name is the most reliable description of the keyring.
            # Only generic file names (or the monolithic trusted.gpg) need the
            # user ids to identify the repository they belong to.
            self._tokens = match_tokens(self.stem) or match_tokens(self.uid or "")

        return self._tokens


def load_system_keys():
    keys = []
    seen = set()

    names = []
    for directory in KEYRING_DIRS:
        try:
            entries = sorted(os.listdir(directory))
        except OSError:
            continue

        for name in entries:
            if not name.endswith((".gpg", ".asc", ".pgp", ".key")):
                continue
            # Debian ships the same keyrings as .gpg and .pgp
            if name.endswith(".pgp") and name[:-4] + ".gpg" in entries:
                continue
            names.append(os.path.join(directory, name))

    if os.path.isfile(TRUSTED_KEYRING):
        names.append(TRUSTED_KEYRING)

    for path in names:
        if path in seen:
            continue
        seen.add(path)
        keys.append(AptKey(path))

    return keys


def source_tokens(source):
    return match_tokens("%s %s" % (source.address, source.suite))


def key_paths_for_source(source):
    signed_by = source.flags.get("signed-by")
    if not signed_by:
        return []

    paths = []
    for entry in signed_by.replace("\n", ",").split(","):
        entry = entry.strip()
        if not entry.startswith("/"):
            continue
        paths.append(os.path.realpath(entry))

    return paths


def match_keys(source, keys):
    """Returns the keys which belong to a repository."""
    signed_by = source.flags.get("signed-by")

    if signed_by:
        wanted = key_paths_for_source(source)
        if not wanted:
            return []

        matched = []
        for key in keys:
            if os.path.realpath(key.path) in wanted:
                matched.append(key)
        return matched

    # Without a signed-by option APT uses the keys from the global keyrings.
    # Attach the keys whose name or uid names this repository.  A single key
    # may be shared by several repositories.
    tokens = source_tokens(source)
    if not tokens:
        return []

    return [key for key in keys if key.tokens() & tokens]


KEY_EXTENSION_RANK = {"gpg": 0, "pgp": 1, "key": 2, "asc": 3}


def dedupe_keys(keys, signed_by_paths=None):
    """Collapses the same key shipped as both .gpg and .asc, etc."""
    if signed_by_paths:
        signed_by_paths = set(os.path.realpath(path) for path in signed_by_paths)

    chosen = {}
    order = []

    for key in keys:
        fingerprints = tuple(sorted(getattr(key, "fingerprints", []) or []))
        identity = fingerprints or ("path", key.path)

        if identity not in chosen:
            chosen[identity] = key
            order.append(identity)
            continue

        current = chosen[identity]
        key_rank = KEY_EXTENSION_RANK.get(getattr(key, "extension", ""), 9)
        current_rank = KEY_EXTENSION_RANK.get(getattr(current, "extension", ""), 9)

        # When signed-by is set, keep the exact file the repository points to.
        if signed_by_paths:
            if (os.path.realpath(key.path) in signed_by_paths
                    and os.path.realpath(current.path) not in signed_by_paths):
                chosen[identity] = key
        elif key_rank < current_rank:
            chosen[identity] = key

    return [chosen[identity] for identity in order]


def write_file_async(path, text, callback):
    """Writes a sources file, asking for authorization only when needed."""
    data = text.encode("utf-8", "surrogateescape")

    if os.access(path, os.W_OK):
        try:
            with open(path, "wb") as stream:
                stream.write(data)
        except OSError as error:
            callback(False, str(error))
            return

        callback(True, "")
        return

    try:
        process = Gio.Subprocess.new(
            ["pkexec", "tee", path],
            Gio.SubprocessFlags.STDIN_PIPE |
            Gio.SubprocessFlags.STDOUT_SILENCE |
            Gio.SubprocessFlags.STDERR_PIPE)
    except GLib.Error as error:
        callback(False, error.message)
        return

    def on_finished(proc, result):
        try:
            _success, _stdout, stderr = proc.communicate_finish(result)
        except GLib.Error as error:
            callback(False, error.message)
            return

        if proc.get_successful():
            callback(True, "")
            return

        message = ""
        if stderr is not None:
            message = stderr.get_data().decode("utf-8", "replace").strip()

        callback(False, message or _("Authentication failed or was cancelled"))

    process.communicate_async(GLib.Bytes.new(data), None, on_finished)


def delete_file_async(path, callback):
    """Deletes a file, asking for authorization only when needed."""
    if os.access(path, os.W_OK) and os.access(os.path.dirname(path), os.W_OK):
        try:
            os.unlink(path)
        except OSError as error:
            callback(False, str(error))
            return

        callback(True, "")
        return

    try:
        process = Gio.Subprocess.new(
            ["pkexec", "rm", "-f", path],
            Gio.SubprocessFlags.STDOUT_SILENCE |
            Gio.SubprocessFlags.STDERR_PIPE)
    except GLib.Error as error:
        callback(False, error.message)
        return

    def on_finished(proc, result):
        try:
            _success, _stdout, stderr = proc.communicate_finish(result)
        except GLib.Error as error:
            callback(False, error.message)
            return

        if proc.get_successful():
            callback(True, "")
            return

        message = ""
        if stderr is not None:
            message = stderr.get_data().decode("utf-8", "replace").strip()

        callback(False, message or _("Authentication failed or was cancelled"))

    process.communicate_async(None, None, on_finished)


def prompt_value(parent, title, label_text, placeholder=""):
    if not isinstance(parent, Gtk.Window):
        parent = None

    dialog = Gtk.Dialog(title=title, transient_for=parent, modal=True)
    dialog.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
    dialog.add_button(_("OK"), Gtk.ResponseType.OK)
    dialog.set_default_response(Gtk.ResponseType.OK)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    box.set_border_width(12)
    box.pack_start(Gtk.Label(label=label_text, xalign=0), False, False, 0)

    entry = Gtk.Entry()
    entry.set_placeholder_text(placeholder)
    entry.set_activates_default(True)
    box.pack_start(entry, False, False, 0)
    box.show_all()

    dialog.get_content_area().pack_start(box, True, True, 0)

    response = dialog.run()
    value = entry.get_text()
    dialog.destroy()

    if response != Gtk.ResponseType.OK:
        return None

    return value


class FlagChip(Gtk.Frame):
    def __init__(self, text, tooltip, callback):
        Gtk.Frame.__init__(self, shadow_type=Gtk.ShadowType.IN)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        box.set_border_width(2)

        label = Gtk.Label(label=text)
        label.set_tooltip_text(tooltip)
        box.pack_start(label, True, True, 2)

        button = Gtk.Button(relief=Gtk.ReliefStyle.NONE)
        button.set_image(Gtk.Image(icon_name="window-close-symbolic", icon_size=Gtk.IconSize.MENU))
        button.set_tooltip_text(_("Remove this flag"))
        button.connect("clicked", callback)
        box.pack_start(button, False, False, 0)

        self.add(box)
        self.show_all()


class SourceRow(Gtk.Frame):
    """One repository, displayed as a bubble."""

    def __init__(self, page, source, src_source=None):
        Gtk.Frame.__init__(self, shadow_type=Gtk.ShadowType.NONE)
        self.get_style_context().add_class("source-row")

        self.page = page
        self.source = source
        self.src_source = src_source
        self._empty_check_scheduled = False

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(box)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        top.set_border_width(6)

        # Binary and source packages are controlled with two checkboxes placed
        # before the protocol.  The first one (deb) enables the repository
        # itself, the second one (src) enables its deb-src entries.
        self.deb_check = Gtk.CheckButton()
        self.deb_check.set_active(source.enabled and not source.is_src_only())
        self.deb_check.set_valign(Gtk.Align.CENTER)
        self.deb_check.set_tooltip_text(_("Applications"))
        if source.is_src_only():
            self.deb_check.set_sensitive(False)
        self.deb_check.connect("notify::active", self.on_enabled_changed)
        top.pack_start(self.deb_check, False, False, 0)

        self.deb_separator = self.make_column_separator()
        top.pack_start(self.deb_separator, False, False, 0)

        self.src_check = Gtk.CheckButton()
        self.src_check.set_active(self.has_src())
        self.src_check.set_valign(Gtk.Align.CENTER)
        self.src_check.set_tooltip_text(_("Source code"))
        self.src_check.connect("notify::active", self.on_src_changed)
        top.pack_start(self.src_check, False, False, 0)

        self.src_separator = self.make_column_separator()
        top.pack_start(self.src_separator, False, False, 0)

        self.scheme_combo = Gtk.ComboBoxText()
        schemes = list(SCHEMES)
        if source.uri_scheme and source.uri_scheme not in schemes:
            schemes.append(source.uri_scheme)
        for scheme in schemes:
            self.scheme_combo.append(scheme, scheme)
        self.scheme_combo.set_tooltip_text(_("Protocol used to reach the repository"))
        self.scheme_combo.set_size_request(96, -1)
        self.scheme_combo.set_valign(Gtk.Align.CENTER)
        self.scheme_combo.get_style_context().add_class("sources-scheme")
        self.scheme_combo.set_active_id(source.uri_scheme or None)
        self.scheme_combo.connect("changed", self.on_scheme_changed)
        top.pack_start(self.scheme_combo, False, False, 0)

        # The option button sits between the protocol and the address.
        self.add_flag_button = Gtk.Button(relief=Gtk.ReliefStyle.NONE)
        self.add_flag_button.set_image(
            Gtk.Image(icon_name="list-add-symbolic", icon_size=Gtk.IconSize.MENU))
        self.add_flag_button.set_tooltip_text(_("Add an option"))
        self.add_flag_button.connect("clicked", self.on_add_flag)
        top.pack_start(self.add_flag_button, False, False, 0)

        self.address_entry = Gtk.Entry()
        self.address_entry.set_text(source.address)
        self.address_entry.set_placeholder_text(_("Repository address"))
        self.address_entry.set_hexpand(True)
        self.address_entry.connect("changed", self.on_address_changed)
        top.pack_start(self.address_entry, True, True, 0)

        self.codename_entry = Gtk.Entry()
        self.codename_entry.set_text(source.suite)
        self.codename_entry.set_placeholder_text(_("Codename"))
        # Wide enough for "unstable", the longest common Debian codename.
        self.codename_entry.set_width_chars(8)
        self.codename_entry.set_max_width_chars(8)
        self.codename_entry.set_hexpand(False)
        self.codename_entry.connect("changed", self.on_codename_changed)
        top.pack_start(self.codename_entry, False, False, 0)

        self.components_entry = Gtk.Entry()
        self.components_entry.set_text(" ".join(source.components))
        self.components_entry.set_placeholder_text(_("Components"))
        # Exactly wide enough for "main contrib non-free non-free-firmware".
        self.components_entry.set_width_chars(32)
        self.components_entry.set_max_width_chars(32)
        self.components_entry.set_hexpand(False)
        self.components_entry.connect("changed", self.on_components_changed)
        top.pack_start(self.components_entry, False, False, 0)

        self.actions_separator = self.make_column_separator()
        top.pack_start(self.actions_separator, False, False, 0)

        self.remove_button = Gtk.Button(relief=Gtk.ReliefStyle.NONE)
        self.remove_button.set_image(
            Gtk.Image(icon_name="user-trash-symbolic", icon_size=Gtk.IconSize.MENU))
        self.remove_button.set_tooltip_text(
            _("Remove this repository (its signing key is kept)"))
        self.remove_button.connect("clicked", self.on_remove_repository)
        top.pack_start(self.remove_button, False, False, 0)

        box.pack_start(top, False, False, 0)

        self.flags_separator_top = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        box.pack_start(self.flags_separator_top, False, False, 0)

        self.flags_flowbox = Gtk.FlowBox()
        self.flags_flowbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flags_flowbox.set_max_children_per_line(20)
        self.flags_flowbox.set_valign(Gtk.Align.CENTER)
        self.flags_flowbox.set_margin_start(6)
        self.flags_flowbox.set_margin_end(6)
        self.flags_flowbox.set_margin_top(4)
        self.flags_flowbox.set_margin_bottom(4)
        box.pack_start(self.flags_flowbox, False, False, 0)

        self.flags_separator_bottom = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        box.pack_start(self.flags_separator_bottom, False, False, 0)

        self.key_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.key_box.set_border_width(2)
        box.pack_start(self.key_box, False, False, 0)

        self.set_tooltip_text(source.path)

        for entry in (self.address_entry, self.codename_entry, self.components_entry):
            entry.connect("focus-out-event", self.on_entry_focus_out)

        self.rebuild_flags()
        self.rebuild_key()
        self.show_all()
        self.update_flags_visibility()

    @staticmethod
    def make_column_separator():
        separator = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        separator.set_margin_top(2)
        separator.set_margin_bottom(2)

        return separator

    # --- model updates -----------------------------------------------------

    def _sync_pair(self):
        if self.src_source is None or self.src_source is self.source:
            return

        self.src_source.uri_scheme = self.source.uri_scheme
        self.src_source.uri_separator = self.source.uri_separator
        self.src_source.address = self.source.address
        self.src_source.suite = self.source.suite
        self.src_source.components = list(self.source.components)
        self.src_source.flags = dict(self.source.flags)

    def on_scheme_changed(self, combo):
        scheme = combo.get_active_id()
        if scheme is not None:
            self.source.uri_scheme = scheme
            if not self.source.uri_separator:
                self.source.uri_separator = "//"
            self._sync_pair()

    def on_address_changed(self, entry):
        self.source.address = entry.get_text().strip()
        self.on_fields_changed()

    def on_codename_changed(self, entry):
        self.source.set_codename(entry.get_text())
        self.on_fields_changed()

    def on_components_changed(self, entry):
        self.source.set_components_text(entry.get_text())
        self.on_fields_changed()

    def on_fields_changed(self):
        self._sync_pair()
        self.schedule_empty_check()

    def on_enabled_changed(self, check, _pspec):
        self.source.enabled = check.get_active()

    def has_src(self):
        if self.source.kind == "sources":
            if self.source.is_src_only():
                return self.source.enabled
            return self.source.has_source_type()

        if self.source.is_src_only():
            return self.source.enabled

        return self.src_source is not None and self.src_source.enabled

    def on_src_changed(self, check, _pspec):
        active = check.get_active()

        if self.source.kind == "sources":
            if self.source.is_src_only():
                self.source.enabled = active
                return

            types = [kind for kind in self.source.types if kind != "deb-src"]
            if active:
                types.append("deb-src")
            if not types:
                types = ["deb"]
            self.source.types = types
            return

        if self.source.is_src_only():
            self.source.enabled = active
            return

        if active:
            if self.src_source is None:
                self.src_source = self.source.clone_as("deb-src")
                self.src_source.enabled = True
                self.page.add_source(self.src_source)
            else:
                self.src_source.enabled = True
            self._sync_pair()
        elif self.src_source is not None:
            if self.src_source.is_new:
                self.page.remove_source(self.src_source)
                self.src_source = None
            else:
                self.src_source.enabled = False

    # --- empty rows --------------------------------------------------------

    def is_empty(self):
        return (not self.source.address
                and not self.source.suite
                and not self.source.components)

    def schedule_empty_check(self):
        if self._empty_check_scheduled:
            return

        self._empty_check_scheduled = True
        GLib.idle_add(self._check_empty)

    def _entry_has_focus(self):
        toplevel = self.get_toplevel()
        if not isinstance(toplevel, Gtk.Window):
            return False

        focus = toplevel.get_focus()
        for entry in (self.address_entry, self.codename_entry, self.components_entry):
            if focus is entry:
                return True
            if entry.get_selection_bounds():
                return True

        return False

    def _check_empty(self):
        self._empty_check_scheduled = False

        if self.get_parent() is None:
            return False

        if not self.is_empty():
            return False

        if self._entry_has_focus():
            return False

        self.page.remove_row(self)
        return False

    def on_entry_focus_out(self, _entry, _event):
        self.schedule_empty_check()
        return False

    # --- flags -------------------------------------------------------------

    def rebuild_flags(self):
        for child in self.flags_flowbox.get_children():
            child.destroy()

        for name, value in self.source.flags.items():
            text = name if value is None else "%s=%s" % (name, value)
            chip = FlagChip(text, _("APT option: %s") % name, self.on_remove_flag)
            chip.flag_name = name
            self.flags_flowbox.add(chip)

        self.flags_flowbox.show_all()
        self.update_flags_visibility()

    def update_flags_visibility(self):
        visible = bool(self.source.flags)
        self.flags_flowbox.set_visible(visible)
        self.flags_separator_top.set_visible(visible)
        self.flags_separator_bottom.set_visible(visible)

    def on_remove_flag(self, button):
        chip = button.get_parent().get_parent()
        self.source.flags.pop(getattr(chip, "flag_name", None), None)
        self._sync_pair()
        self.rebuild_flags()
        self.rebuild_key()
        self.page.refresh_unused_keys()

    def on_add_flag(self, button):
        popover = Gtk.Popover(relative_to=button)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        for name in sorted(FLAG_FIELDS):
            item = Gtk.Button(label=name, relief=Gtk.ReliefStyle.NONE)
            item.connect("clicked", self.on_flag_chosen, popover)
            box.pack_start(item, False, False, 0)
        box.show_all()

        popover.add(box)
        popover.popup()

    def on_flag_chosen(self, button, popover):
        popover.popdown()

        name = button.get_label()
        if name == "signed-by":
            self.pick_key_file()
            return

        value = prompt_value(
            self.get_toplevel(),
            _("Add option"),
            _("Value of the '%s' option:") % name,
            FLAG_HINTS.get(name, ""))

        if value is None:
            return

        value = value.strip()
        self.source.flags[name] = value or None
        self._sync_pair()
        self.rebuild_flags()
        self.rebuild_key()
        self.page.refresh_unused_keys()

    # --- keys --------------------------------------------------------------

    def signed_by_entries(self):
        signed_by = self.source.flags.get("signed-by")
        if not signed_by:
            return []

        return [entry.strip() for entry in signed_by.replace("\n", ",").split(",")
                if entry.strip()]

    def make_key_row(self, text, tooltip):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.set_margin_start(6)
        row.set_margin_end(6)
        row.set_margin_top(2)
        row.set_margin_bottom(2)

        image = Gtk.Image(icon_name="dialog-password", icon_size=Gtk.IconSize.MENU)
        row.pack_start(image, False, False, 0)

        label = Gtk.Label(label=text, xalign=0)
        label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        label.set_tooltip_text(tooltip)
        row.pack_start(label, True, True, 0)

        return row

    def make_remove_key_button(self, path):
        remove = Gtk.Button(relief=Gtk.ReliefStyle.NONE)
        remove.set_image(
            Gtk.Image(icon_name="window-close-symbolic", icon_size=Gtk.IconSize.MENU))
        remove.set_tooltip_text(_("Detach this key from the repository"))
        remove.connect("clicked", self.on_remove_key_path, path)

        return remove

    def rebuild_key(self):
        for child in self.key_box.get_children():
            child.destroy()

        signed_by = self.source.flags.get("signed-by")
        signed_by_paths = key_paths_for_source(self.source) if signed_by else None
        keys = dedupe_keys(match_keys(self.source, self.page.keys), signed_by_paths)

        if keys:
            # A repository may be signed by several keys.  Show every one of
            # them instead of only the first match.
            for key in keys:
                row = self.make_key_row(key.label, key.path)
                if signed_by:
                    row.pack_start(self.make_remove_key_button(key.path), False, False, 0)
                self.key_box.pack_start(row, False, False, 0)
        elif signed_by:
            for entry in self.signed_by_entries():
                row = self.make_key_row(entry.split("\n")[0], entry)
                row.pack_start(self.make_remove_key_button(entry), False, False, 0)
                self.key_box.pack_start(row, False, False, 0)

        self.key_box.show_all()

    def on_remove_key_path(self, button, path):
        entries = self.signed_by_entries()
        keep = []
        for entry in entries:
            if entry == path or os.path.realpath(entry) == os.path.realpath(path):
                continue
            keep.append(entry)

        if keep:
            self.source.flags["signed-by"] = ",".join(keep)
        else:
            self.source.flags.pop("signed-by", None)

        self._sync_pair()
        self.rebuild_key()
        self.rebuild_flags()
        self.page.refresh_unused_keys()

    def on_remove_repository(self, button):
        self.page.remove_row(self)

    def pick_key_file(self):
        parent = self.get_toplevel()
        if not isinstance(parent, Gtk.Window):
            parent = None

        chooser = Gtk.FileChooserDialog(
            title=_("Select the signing key file"),
            transient_for=parent,
            action=Gtk.FileChooserAction.OPEN)
        chooser.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        chooser.add_button(_("Select"), Gtk.ResponseType.OK)
        chooser.set_default_response(Gtk.ResponseType.OK)

        key_filter = Gtk.FileFilter()
        key_filter.set_name(_("Signing keys"))
        for pattern in ("*.gpg", "*.asc", "*.pgp", "*.key"):
            key_filter.add_pattern(pattern)
        chooser.add_filter(key_filter)

        for directory in KEYRING_DIRS:
            if os.path.isdir(directory):
                try:
                    chooser.add_shortcut_folder(directory)
                except GLib.Error:
                    pass

        for directory in ("/usr/share/keyrings", "/etc/apt/keyrings"):
            if os.path.isdir(directory):
                chooser.set_current_folder(directory)
                break

        path = None
        if chooser.run() == Gtk.ResponseType.OK:
            path = chooser.get_filename()
        chooser.destroy()

        if not path:
            return

        entries = self.signed_by_entries()
        if not any(entry == path or os.path.realpath(entry) == os.path.realpath(path)
                   for entry in entries):
            entries.append(path)

        # Flag values are whitespace separated, so the key paths must be joined
        # with commas only.
        self.source.flags["signed-by"] = ",".join(entries)
        self._sync_pair()
        self.rebuild_key()
        self.rebuild_flags()
        self.page.refresh_unused_keys()


class SourcesPage(Gtk.Box):
    """The software sources page, shown inside the main window."""

    __gsignals__ = {
        "saved": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.set_border_width(12)

        install_css()

        self.files = []
        self.keys = []
        self.rows = []
        self._save_queue = []
        self._save_errors = []

        self.build_ui()
        self.reload()

    def build_ui(self):
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        title = Gtk.Label(label=_("Software sources"), xalign=0)
        attributes = Pango.AttrList()
        attributes.insert(Pango.attr_weight_new(Pango.Weight.BOLD))
        title.set_attributes(attributes)
        header.pack_start(title, True, True, 0)

        self.save_button = Gtk.Button(label=_("Save"))
        self.save_button.set_tooltip_text(_("Write the changes to the repository configuration"))
        self.save_button.get_style_context().add_class("suggested-action")
        self.save_button.connect("clicked", self.on_save_clicked)
        header.pack_start(self.save_button, False, False, 0)

        self.pack_start(header, False, False, 0)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_overlay_scrolling(True)
        scrolled.get_style_context().add_class("sources-scroll")
        self.pack_start(scrolled, True, True, 0)

        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        scrolled.add(self.box)

        self.repositories_label = self.make_section_label(_("APT repositories"))
        self.box.pack_start(self.repositories_label, False, False, 0)

        self.repositories_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.box.pack_start(self.repositories_box, False, False, 0)

        self.empty_label = Gtk.Label(label=_("No APT repositories found"), xalign=0)
        self.box.pack_start(self.empty_label, False, False, 0)

        self.add_repository_button = Gtk.Button(relief=Gtk.ReliefStyle.NONE)
        self.add_repository_button.set_tooltip_text(
            _("Add a repository (written to /etc/apt/sources.list.d/mintinstall.list)"))
        image = Gtk.Image(icon_name="list-add-symbolic", icon_size=Gtk.IconSize.MENU)
        image.set_halign(Gtk.Align.CENTER)
        self.add_repository_button.set_image(image)
        self.add_repository_button.connect("clicked", self.on_add_repository)
        self.box.pack_start(self.add_repository_button, False, False, 0)

        self.keys_label = self.make_section_label(_("Unused keys"))
        self.box.pack_start(self.keys_label, False, False, 0)

        self.keys_frame = Gtk.Frame(shadow_type=Gtk.ShadowType.IN)
        self.keys_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.keys_frame.add(self.keys_box)
        self.box.pack_start(self.keys_frame, False, False, 0)

        self.show_all()

    def make_section_label(self, text):
        label = Gtk.Label(label=text, xalign=0)
        label.set_margin_top(6)
        attributes = Pango.AttrList()
        attributes.insert(Pango.attr_weight_new(Pango.Weight.BOLD))
        label.set_attributes(attributes)

        return label

    def reload(self):
        for row in self.rows:
            row.destroy()
        self.rows = []

        self.files = load_sources_files()
        self.keys = load_system_keys()

        sources = []
        for sources_file in self.files:
            sources.extend(sources_file.sources)

        for source, src_source in self.group_sources(sources):
            row = SourceRow(self, source, src_source)
            self.repositories_box.pack_start(row, False, False, 0)
            self.rows.append(row)

        self.show_all()
        self.refresh_unused_keys()
        self.update_empty_state()

    @staticmethod
    def group_sources(sources):
        """Groups deb and deb-src entries of the same repository into one row."""
        groups = []
        lookup = {}

        for source in sources:
            key = (source.path, source.full_uri, source.suite,
                   tuple(source.components))
            entry = lookup.get(key)

            if entry is not None:
                primary, src_source = entry
                can_pair = (primary.kind == "list"
                            and source.kind == "list"
                            and src_source is None
                            and primary.is_src_only() != source.is_src_only()
                            and not (primary.has_source_type() and source.has_source_type()))

                if can_pair:
                    if primary.is_src_only():
                        entry[0] = source
                        entry[1] = primary
                    else:
                        entry[1] = source
                    continue

                suffix = 1
                while key + (suffix,) in lookup:
                    suffix += 1
                key = key + (suffix,)

            entry = [source, None]
            lookup[key] = entry
            groups.append(entry)

        return groups

    def file_for_path(self, path):
        for sources_file in self.files:
            if sources_file.path == path:
                return sources_file

        return None

    def get_file(self, path):
        sources_file = self.file_for_path(path)
        if sources_file is None:
            sources_file = SourcesFile(path)
            self.files.append(sources_file)

        return sources_file

    def add_source(self, source):
        self.get_file(source.path).append_source(source)

    def remove_source(self, source):
        sources_file = self.file_for_path(source.path)
        if sources_file is not None and source in sources_file.sources:
            sources_file.remove_source(source)

    def update_empty_state(self):
        self.empty_label.set_visible(not self.rows)

    # --- repository rows ---------------------------------------------------

    def on_add_repository(self, button):
        sources_file = self.get_file(MINTINSTALL_LIST)

        source = AptSource(MINTINSTALL_LIST, "list", "\n")
        source.uri_scheme = "http"
        source.uri_separator = "//"
        source.enabled = True
        source.is_new = True

        sources_file.append_source(source)

        row = SourceRow(self, source)
        self.repositories_box.pack_start(row, False, False, 0)
        self.rows.append(row)
        row.show_all()
        self.update_empty_state()
        self.refresh_unused_keys()
        row.address_entry.grab_focus()

    def remove_row(self, row):
        if row not in self.rows:
            return

        self.rows.remove(row)

        for source in (row.source, row.src_source):
            if source is None:
                continue

            sources_file = self.file_for_path(source.path)
            if sources_file is not None and source in sources_file.sources:
                sources_file.remove_source(source)

        row.destroy()
        self.update_empty_state()
        self.refresh_unused_keys()

    # --- unused keys -------------------------------------------------------

    def refresh_unused_keys(self):
        used = set()
        for row in self.rows:
            for source in (row.source, row.src_source):
                if source is None:
                    continue
                for key in match_keys(source, self.keys):
                    used.add(key.path)

        for child in self.keys_box.get_children():
            child.destroy()

        unused = [key for key in self.keys if key.path not in used]
        for index, key in enumerate(unused):
            if index > 0:
                self.keys_box.pack_start(
                    Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)

            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            row.set_margin_start(8)
            row.set_margin_end(4)
            row.set_margin_top(4)
            row.set_margin_bottom(4)

            label = Gtk.Label(label=key.label, xalign=0)
            label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            label.set_tooltip_text(key.path)
            row.pack_start(label, True, True, 0)

            remove = Gtk.Button(relief=Gtk.ReliefStyle.NONE)
            remove.set_image(
                Gtk.Image(icon_name="user-trash-symbolic", icon_size=Gtk.IconSize.MENU))
            remove.set_tooltip_text(_("Delete this signing key"))
            remove.connect("clicked", self.on_delete_key, key)
            row.pack_start(remove, False, False, 0)

            self.keys_box.pack_start(row, False, False, 0)

        self.keys_box.show_all()
        self.keys_label.set_visible(bool(unused))
        self.keys_frame.set_visible(bool(unused))

    def on_delete_key(self, button, key):
        parent = self.get_toplevel()
        if not isinstance(parent, Gtk.Window):
            parent = None

        dialog = Gtk.MessageDialog(
            transient_for=parent,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text=_("Delete this signing key?"))
        dialog.format_secondary_text(key.path)
        dialog.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        dialog.add_button(_("Delete"), Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.CANCEL)

        response = dialog.run()
        dialog.destroy()

        if response != Gtk.ResponseType.OK:
            return

        delete_file_async(
            key.path,
            lambda success, error: self.on_key_deleted(key, success, error))

    def on_key_deleted(self, key, success, error):
        if success:
            self.keys = [item for item in self.keys if item.path != key.path]
            self.refresh_unused_keys()
            return

        parent = self.get_toplevel()
        if not isinstance(parent, Gtk.Window):
            parent = None

        message = Gtk.MessageDialog(
            transient_for=parent,
            modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.CLOSE,
            text=_("Unable to delete the signing key"))
        message.format_secondary_text("%s\n%s" % (key.path, error))
        message.run()
        message.destroy()

    # --- saving ------------------------------------------------------------

    def on_save_clicked(self, button):
        self.save()

    def save(self):
        # An empty bubble is not a repository: drop it from the page and from
        # the file before writing anything.
        for row in list(self.rows):
            if row.is_empty():
                self.remove_row(row)

        self._save_queue = [sources_file for sources_file in self.files
                            if sources_file.changed()]
        self._save_errors = []

        if not self._save_queue:
            return

        self._save_next()

    def _save_next(self):
        if not self._save_queue:
            self._save_finished()
            return

        sources_file = self._save_queue.pop(0)
        write_file_async(
            sources_file.path,
            sources_file.render(),
            lambda success, error: self._save_done(sources_file, success, error))

    def _save_done(self, sources_file, success, error):
        if not success:
            self._save_errors.append("%s: %s" % (sources_file.path, error))

        self._save_next()

    def _save_finished(self):
        if self._save_errors:
            parent = self.get_toplevel()
            if not isinstance(parent, Gtk.Window):
                parent = None

            message = Gtk.MessageDialog(
                transient_for=parent,
                modal=True,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.CLOSE,
                text=_("Unable to save the software sources"))
            message.format_secondary_text("\n".join(self._save_errors))
            message.run()
            message.destroy()
        else:
            self.emit("saved")

        self.reload()
