#!/usr/bin/python3
# encoding=utf-8
# -*- coding: UTF-8 -*-

import sys
import os
import gettext
import threading
import locale
import urllib.request, urllib.parse, urllib.error
import random
from datetime import datetime
import subprocess
import shutil
import tempfile
import platform
import time
import json
import re
import math
from pathlib import Path
import traceback
from operator import attrgetter

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('XApp', '1.0')
from gi.repository import Gtk, Gdk, GdkPixbuf, GObject, GLib, Gio, XApp, Pango
import cairo

from mintcommon.installer import installer
from mintcommon.installer import dialogs
import prefs
import apt_sources
import reviews
import housekeeping
import debfile
import appstreamfile
from misc import print_timing, networking_available, get_os_name
import imaging
from screenshot_window import ScreenshotWindow


from math import pi
DEGREES = pi / 180


#Hardcoded mouse back button key for button-press-event
#May not work on all mice
MOUSE_BACK_BUTTON = 8

#How many milliseconds between banner slides
BANNER_TIMER = 500

# package type combobox columns
# index, label, icon-name, tooltip, pkginfo
PACKAGE_TYPE_COMBO_INDEX = 0
PACKAGE_TYPE_COMBO_LABEL = 1
PACKAGE_TYPE_COMBO_SUMMARY = 2
PACKAGE_TYPE_COMBO_ICON_NAME = 3
PACKAGE_TYPE_COMBO_PKGINFO = 4

# Don't let mintinstall run as root
if os.getuid() == 0:
    print("The software manager should not be run as root. Please run it in user mode.")
    sys.exit(1)

# i18n
APP = 'mintinstallpp'
LOCALE_DIR = "/usr/share/linuxmint/locale"
locale.bindtextdomain(APP, LOCALE_DIR)
gettext.bindtextdomain(APP, LOCALE_DIR)
gettext.textdomain(APP)
_ = gettext.gettext

import setproctitle
setproctitle.setproctitle("mintinstall")

Gtk.IconTheme.get_default().append_search_path("/usr/share/linuxmint/mintinstall")

# List of aliases
ALIASES = {}
ALIASES['spotify-client'] = "Spotify"
ALIASES['steam-installer'] = "Steam"
ALIASES['minecraft-launcher'] = "Minecraft"
ALIASES['virtualbox-qt'] = "Virtualbox " # Added a space to force alias
ALIASES['virtualbox'] = "Virtualbox (base)"
ALIASES['sublime-text'] = "Sublime"
ALIASES['mint-meta-codecs'] = _("Multimedia Codecs")
ALIASES['mint-meta-codecs-kde'] = _("Multimedia Codecs for KDE")
ALIASES['mint-meta-debian-codecs'] = _("Multimedia Codecs")
ALIASES['firefox'] = "Firefox"
ALIASES['vlc'] = "VLC"
ALIASES['mpv'] = "Mpv"
ALIASES['gimp'] = "Gimp"
ALIASES['gnome-maps'] = "GNOME Maps"
ALIASES['thunderbird'] = "Thunderbird"
ALIASES['pia-manager'] = "PIA Manager"
ALIASES['skypeforlinux'] = "Skype"
ALIASES['google-earth-pro-stable'] = "Google Earth"
ALIASES['whatsapp-desktop'] = "WhatsApp"
ALIASES['wine-installer'] = "Wine"

libdir = os.path.dirname(__file__) if os.path.exists(os.path.join(os.path.dirname(__file__), "apt_flatpak_match_data.info")) else "/usr/lib/linuxmint/mintinstall"

with open(os.path.join(libdir, "apt_flatpak_match_data.info")) as f:
    match_data = json.load(f)

FLATPAK_EQUIVS = match_data["apt_flatpak_matches"]
DEB_EQUIVS = dict((v, k) for k,v in FLATPAK_EQUIVS.items())

pkg_tile_ui = "/usr/share/linuxmint/mintinstall/mintinstall.gresource"
if os.path.exists(pkg_tile_ui):
    UI_RESOURCES = Gio.Resource.load(pkg_tile_ui)
    UI_RESOURCES._register()

def load_builder(filename):
    local_path = os.path.normpath(os.path.join(os.path.dirname(__file__), "../../../../resources", filename))
    if os.path.exists(local_path):
        return Gtk.Builder.new_from_file(local_path)
    return Gtk.Builder.new_from_resource("/com/linuxmint/mintinstall/" + filename)

KB = 1000
MB = KB * 1000

def get_size_for_display(size):
    if size == 0:
        return ""

    if size > (5 * MB):
        size = (size // MB) * MB
    elif size > KB:
        size = (size // KB) * KB

    formatted = GLib.format_size(size).replace(".0", "")
    return formatted

class NonScrollingComboBox(Gtk.ComboBox):
    def __init__(self, area):
        Gtk.ComboBox.__init__(self, cell_area=area, height_request=36)

    def do_scroll_event(self, event, data=None):
        # Skip Gtk.ComboBox's default handler.
        #
        # Connecting to a Gtk.ComboBox and stopping a scroll-event
        # prevents unintentional combobox changes, but also breaks
        # any scrollable parents when passing over the combobox.
        Gtk.Widget.do_scroll_event(self, event)

class HeadingMenuItem(Gtk.MenuItem):
    def __init__(self, *args, **kargs):
        Gtk.MenuItem.__init__(self, *args, **kargs)
        label = self.get_child()

        if (isinstance(label, Gtk.Label)):
            label.set_use_markup(True)
            label.set_markup("<b>%s</b>" % label.get_label())

    def do_button_press_event(self, event):
        return Gdk.EVENT_STOP

    def do_button_release_event(self, event):
        return Gdk.EVENT_STOP

    def do_key_press_event(self, event):
        return Gdk.EVENT_STOP

    def do_key_release_event(self, event):
        return Gdk.EVENT_STOP

    def do_enter_notify_event(self, event):
        return Gdk.EVENT_STOP

class FlatpakAddonRow(Gtk.ListBoxRow):
    def __init__(self, app, parent_pkginfo, addon_pkginfo, name_size_group, button_size_group):
        Gtk.ListBoxRow.__init__(self)
        self.box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4, margin_start=10, margin_end=10, margin_top=4, margin_bottom=4)
        self.add(self.box)

        self.app = app
        self.parent_pkginfo = parent_pkginfo
        self.addon_pkginfo = addon_pkginfo

        self.spinner = Gtk.Spinner(active=True, no_show_all=True, visible=True)
        self.box.pack_start(self.spinner, False, False, 0)

        self.action = Gtk.Button(label="",
                                 sensitive=False,
                                 image=self.spinner,
                                 always_show_image=True,
                                 valign=Gtk.Align.CENTER,
                                 no_show_all=True)
        self.action.set_size_request(100, -1)
        button_size_group.add_widget(self.action)
        self.action.connect("clicked", self.action_clicked)
        self.box.pack_end(self.action, False, False, 0)

        label_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.box.pack_start(label_box, False, False, 0)

        name = Gtk.Label(label="<b>%s</b>" % addon_pkginfo.get_display_name(), use_markup=True, xalign=0.0, selectable=True)
        name_size_group.add_widget(name)
        label_box.pack_start(name, False, False, 0)

        summary = Gtk.Label(label=addon_pkginfo.get_summary(), xalign=0.0, wrap=True, max_width_chars=60, selectable=True)
        label_box.pack_start(summary, False, False, 0)

        if not self.app.installer.pkginfo_is_installed(self.parent_pkginfo):
            self.action.hide()
            self.set_sensitive(False)
            return

        self.action.show()
        self.update_button()

    def update_button(self):
        if not self.app.installer.pkginfo_is_installed(self.addon_pkginfo):
            self.action.set_label(_("Add"))
            self.action.set_sensitive(True)
            self.action.get_style_context().add_class("suggested-action")
            self.action.get_style_context().remove_class("destructive-action")
            self.spinner.hide()
        else:
            self.action.set_label(_("Remove"))
            self.action.set_sensitive(True)
            self.action.get_style_context().add_class("destructive-action")
            self.action.get_style_context().remove_class("suggested-action")
            self.spinner.hide()

    def info_ready(self, task):
        self.app.installer.execute_task(task)
        self.action.set_label("")
        self.app.update_activity_widgets()

    def info_error(self, task):
        self.task = task

        self.spinner.hide()
        self.action.set_sensitive(False)
        self.action.set_label(_("Unavailable"))
        self.action.get_style_context().remove_class("suggested-action")
        self.action.get_style_context().remove_class("destructive-action")

    def action_clicked(self, widget):
        self.app.installer.select_pkginfo(self.addon_pkginfo,
                                          self.info_ready, self.info_error,
                                          self.installer_finished, self.installer_progress,
                                          use_mainloop=True)

    def installer_finished(self, task):
        self.app.update_activity_widgets()
        self.update_button()

    def installer_progress(self, pkginfo, progress, estimating, status_text=None):
        self.spinner.show()

class SaneProgressBar(Gtk.DrawingArea):
    def __init__(self):
        super(Gtk.DrawingArea, self).__init__(width_request=-1,
                                              height_request=8,
                                              margin_top=1, #???  to align better with the stars and count
                                              hexpand=True,
                                              valign=Gtk.Align.CENTER,
                                              visible=True)
        self.connect("draw", self.draw_bar)
        self.fraction = 0

    def update_colors(self):
        context = self.get_style_context()

        ret, self.fill_color = context.lookup_color("fg_color")
        if not ret:
            self.fill_color = Gdk.RGBA()
            self.fill_color.parse("grey")
        ret, self.trough_color = context.lookup_color("bg_color")
        if not ret:
            self.trough_color = Gdk.RGBA()
            self.trough_color.parse("white")

        ret, self.border_color = context.lookup_color("borders_color")
        if not ret:
            self.border_color = Gdk.RGBA()
            self.border_color.parse("grey")

    def draw_bar(self, widget, cr):
        self.update_colors()

        allocation = self.get_allocation()

        cr.set_antialias(cairo.ANTIALIAS_SUBPIXEL)
        cr.save()
        cr.set_line_width(1)

        self.rounded_rect(cr, 1, 1, allocation.width - 2, allocation.height - 2)
        cr.clip()

        Gdk.cairo_set_source_rgba(cr, self.trough_color)
        self.rounded_rect(cr, 1, 1, allocation.width - 2, allocation.height - 2)
        cr.fill()

        Gdk.cairo_set_source_rgba(cr, self.fill_color)
        self.rounded_rect(cr, -20, 1, allocation.width * self.fraction + 20, allocation.height - 2)
        cr.fill()

        Gdk.cairo_set_source_rgba(cr, self.border_color)
        self.rounded_rect(cr, 1, 1, allocation.width - 2, allocation.height - 2)
        cr.stroke()

        cr.restore()

        return True

    def rounded_rect(self, cr, x, y, width, height):
        radius = 3
        cr.new_sub_path()
        cr.arc(x + radius, y + radius, radius, 180 * DEGREES, 270 * DEGREES)
        cr.arc(x + width - radius, y + radius, radius, -90 * DEGREES, 0 * DEGREES)
        cr.arc(x + width - radius, y + height - radius, radius, 0 * DEGREES, 90 * DEGREES)
        cr.arc(x + radius, y + height - radius, radius, 90 * DEGREES, 180 * DEGREES)
        cr.close_path()

    def set_fraction(self, fraction):
        self.fraction = fraction
        self.queue_draw()


class BannerTile(Gtk.FlowBoxChild):
    def __init__(self, pkginfo, installer, name, background, color, is_flatpak, app_json, on_clicked_action):
        super(Gtk.FlowBoxChild, self).__init__()

        self.pkginfo = pkginfo
        self.installer = installer
        self.is_flatpak = is_flatpak
        self.init_name = name
        self.background = background
        self.color = color

        self.image_uri = (f"/usr/share/linuxmint/mintinstall/featured/{name}.svg")

        css = """
#BannerTile {
    background: %(background)s;
    color: %(color)s;
    padding: 12px;
    border-radius: 5px;
}
#BannerTitle {
    color: %(color)s;
    font-weight: bold;
    font-size: 44px;
    padding-top: 8px;
}
#BannerSummary {
    color: %(color)s;
    font-weight: normal;
    font-size: 16px;
    padding-top: 4px;
}
#BannerFlatpakLabel {
    font-weight: normal;
    font-size: 12px;
}
""" % {'background':background, 'color':color}

        self.set_name("BannerTile")
        style_provider = Gtk.CssProvider()
        style_provider.load_from_data(str.encode(css))

        """ Have to reuse .add_provider(style_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION) for every widget because
        add_provider doesn't cascade to children, and can't set the whole screen context for multiple tiles
        without making them uniform """
        self.get_style_context().add_provider(style_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        label_name = Gtk.Label(xalign=0)
        label_name.set_label(pkginfo.get_display_name())
        label_name.set_name("BannerTitle")
        label_name.get_style_context().add_provider(style_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        label_summary = Gtk.Label(xalign=0)
        label_summary.set_label(pkginfo.get_summary())
        label_summary.set_name("BannerSummary")
        label_summary.get_style_context().add_provider(style_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        image = Gtk.Image.new_from_file(self.image_uri)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, halign=Gtk.Align.START)
        vbox.get_style_context().add_provider(style_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        vbox.set_border_width(6)

        vbox.pack_start(label_name, False, False, 0)
        vbox.pack_start(label_summary, False, False, 0)

        if self.is_flatpak:
            box_flatpak = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            box_flatpak.get_style_context().add_provider(style_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            box_flatpak.pack_start(Gtk.Image.new_from_icon_name("mintinstall-package-flatpak-symbolic", Gtk.IconSize.MENU), False, False, 0)
            label_flatpak = Gtk.Label(label="Flathub")
            label_flatpak.set_name("BannerFlatpakLabel")
            label_flatpak.get_style_context().add_provider(style_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            box_flatpak.pack_start(label_flatpak, False, False, 0)
            vbox.pack_start(box_flatpak, False, False, 0)

        hbox = Gtk.Box(spacing=24)
        hbox.pack_start(image, False, False, 0)
        hbox.pack_start(vbox, True, True, 0)
        hbox.show_all()
        self.add(hbox)

        self.box = hbox

class PackageTile(Gtk.FlowBoxChild):
    def __init__(self, pkginfo, installer, show_package_type=False, review_info=None, upgradable=False):
        super(PackageTile, self).__init__()

        self.button = Gtk.Button();
        self.button.connect("clicked", self._activate_fb_child)
        self.button.set_can_focus(False)
        self.add(self.button)

        self.pkginfo = pkginfo
        self.installer = installer
        self.review_info = review_info
        self.show_package_type = show_package_type
        self.upgradable = upgradable

        self.pkg_category = ''
        if len(pkginfo.categories) > 0:
            if len(pkginfo.categories) == 1:
                self.pkg_category = pkginfo.categories[0]
            else:
                self.pkg_category = pkginfo.categories[1]


        self.builder = load_builder("package-tile.glade")

        self.overlay = self.builder.get_object("vertical_package_tile")
        self.button.add(self.overlay)

        self.icon_holder = self.builder.get_object("icon_holder")
        self.package_label = self.builder.get_object("package_label")
        self.package_summary = self.builder.get_object("package_summary")
        self.package_type_box = self.builder.get_object("package_type_box")
        self.package_type_emblem = self.builder.get_object("package_type_emblem")
        self.package_type_name = self.builder.get_object("package_type_name")
        self.installed_mark = self.builder.get_object("installed_mark")
        self.update_mark = self.builder.get_object("update_mark")
        self.verified_mark = self.builder.get_object("verified_mark")
        self.icon = None

        self.repopulate_tile()

    def repopulate_tile(self):
        if self.icon is not None:
            self.icon.destroy()

        icon_string = self.pkginfo.get_icon(imaging.FEATURED_ICON_SIZE)
        if not icon_string:
            icon_string = imaging.FALLBACK_PACKAGE_ICON_PATH
        self.icon = imaging.get_icon(icon_string, imaging.FEATURED_ICON_SIZE)
        self.icon_holder.add(self.icon)

        display_name = self.pkginfo.get_display_name()
        self.package_label.set_label(display_name)

        summary = self.pkginfo.get_summary()
        self.package_summary.set_label(summary)

        if self.show_package_type:
            if self.pkginfo.pkg_hash.startswith("f"):

                remote_info = None

                try:
                    remote_info = self.installer.get_remote_info_for_name(self.pkginfo.remote)
                    if remote_info:
                        self.package_type_name.set_label(remote_info.title)
                except:
                    pass

                if remote_info is None:
                    self.package_type_name.set_label(self.pkginfo.remote.capitalize())

                self.package_type_emblem.set_from_icon_name("mintinstall-package-flatpak-symbolic", Gtk.IconSize.MENU)
                self.package_type_box.show()
                self.package_type_box.set_tooltip_text(_("This package is a Flatpak"))
            else:
                self.package_type_name.hide()
                self.package_type_emblem.hide()

        if self.pkginfo.verified:
            self.builder.get_object("review_info_box").show()
            if self.review_info:
                self.fill_rating_widget(self.review_info)
        else:
            self.builder.get_object("unsafe_box").show()

        self.show_all()
        self.refresh_state()

    def _activate_fb_child(self, widget):
        self.activate()

    def refresh_state(self):
        self.installed = self.installer.pkginfo_is_installed(self.pkginfo)

        if self.installed:
            self.installed_mark.set_from_icon_name("mintinstall-installed", Gtk.IconSize.MENU)
        else:
            self.installed_mark.clear()

        if self.upgradable:
            self.update_mark.set_tooltip_text(_("Update available"))
            self.update_mark.show()
        else:
            self.update_mark.hide()

    def fill_rating_widget(self, review_info):
        rating = str(review_info.avg_rating)
        num_reviews_label = self.builder.get_object("num_reviews_label")
        num_reviews_label.set_label(rating)

class ReviewTile(Gtk.ListBoxRow):
    def __init__(self, username, date, comment, rating):
        super(Gtk.ListBoxRow, self).__init__()

        main_box = Gtk.Box()
        main_box.set_margin_start(12)
        main_box.set_margin_end(12)
        main_box.set_margin_top(12)
        main_box.set_margin_bottom(12)

        ratings_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        stars_box = Gtk.Box()
        for i in range(rating):
            stars_box.pack_start(Gtk.Image.new_from_icon_name("xsi-starred-symbolic", Gtk.IconSize.MENU), False, False, 0)
        for i in range(5 - rating):
            stars_box.pack_start(Gtk.Image.new_from_icon_name("xsi-non-starred-symbolic", Gtk.IconSize.MENU), False, False, 0)
        ratings_box.pack_start(stars_box, False, False, 0)

        label_name = Gtk.Label(xalign=0.0)
        label_name.set_markup("<small>%s</small>" % GLib.markup_escape_text(username))
        ratings_box.pack_start(label_name, False, False, 0)

        label_date = Gtk.Label(xalign=0.0)
        label_date.set_markup("<small>%s</small>" % GLib.markup_escape_text(date))
        ratings_box.pack_start(label_date, False, False, 0)

        label_comment = Gtk.Label(xalign=0.0, selectable=True)
        label_comment.set_label(comment)
        label_comment.set_line_wrap(True)

        comment_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        comment_box.set_margin_start(12)
        comment_box.pack_start(label_comment, False, False, 0)

        main_box.pack_start(ratings_box, False, False, 0)
        main_box.pack_start(comment_box, True, True, 0)

        self.add(main_box)

class Category:
    def __init__(self, name, parent, categories, icon_name=""):
        self.name = name
        self.parent = parent
        self.icon_name = icon_name
        self.subcategories = []
        self.pkginfos = []
        self.matchingPackages = []
        if parent is not None:
            parent.subcategories.append(self)
        if categories is not None:
            categories.append(self)
        cat = self
        while cat.parent is not None:
            cat = cat.parent

class SortPackage:
    def __init__(self, pkg):
        self.pkg = pkg
        self.name = pkg.name
        self.unverified = not pkg.verified
        self.installed = False
        self.score_desc = 0
        self.search_tier = pkg.search_tier if hasattr(pkg, "search_tier") else 0

class SubcategoryFlowboxChild(Gtk.FlowBoxChild):
    def __init__(self, category, is_all=False, active=False):
        super(Gtk.FlowBoxChild, self).__init__()

        self.category = category

        cat_name = category.name
        cat_icon = category.icon_name
        if is_all:
            cat_name = _("All")
            cat_icon = "mintinstall-all-symbolic"

        self.button = Gtk.ToggleButton(active=active)

        self.button.connect("clicked", self._activate_fb_child)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, valign=Gtk.Align.CENTER)
        image = Gtk.Image(icon_name=cat_icon, icon_size=Gtk.IconSize.MENU)
        label = Gtk.Label(label=cat_name)
        box.pack_start(image, False, False, 0)
        box.pack_start(label, False, False, 0)
        box.show_all()

        self.button.add(box)

        self.add(self.button)

    def _activate_fb_child(self, widget):
        self.activate()

class CategoryButton(Gtk.Button):
    def __init__(self, category):
        super(Gtk.Button, self).__init__()

        self.category = category

        self.set_can_focus(False)
        self.set_hexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, valign=Gtk.Align.CENTER)
        image = Gtk.Image(icon_name=category.icon_name, icon_size=Gtk.IconSize.MENU)
        label = Gtk.Label(label=category.name)
        box.pack_start(image, False, False, 0)
        box.pack_start(label, False, False, 0)
        box.show_all()

        self.add(box)

class DebChangeEntry:
    """Stand-in for a PackageKit package, so a local .deb can be listed in the changes confirmation."""
    def __init__(self, name):
        self.name = name

    def get_name(self):
        return self.name


class Application(Gtk.Application):
    (ACTION_TAB, PROGRESS_TAB, SPINNER_TAB) = list(range(3))

    PAGE_LANDING = "landing"
    PAGE_LIST = "list"
    PAGE_DETAILS = "details"
    PAGE_LOADING = "loading"
    PAGE_SEARCHING = "searching"
    PAGE_GENERATING_CACHE = "generating_cache"
    PAGE_PREFS = "prefs"
    PAGE_SOURCES = "sources"
    PAGE_DEB = "deb"

    def __init__(self):
        super(Application, self).__init__(application_id='com.linuxmint.mintinstall',
                                          flags=Gio.ApplicationFlags.HANDLES_OPEN | Gio.ApplicationFlags.HANDLES_COMMAND_LINE)

        self.gui_ready = False
        self.start_time = time.time()

        self.settings = Gio.Settings(schema_id="com.linuxmint.install")
        self.arch = platform.machine()

        print("MintInstall: Detected system architecture: '%s'" % self.arch)

        self.locale = os.getenv('LANGUAGE')
        if self.locale is None:
            self.locale = "C"
        else:
            self.locale = self.locale.split("_")[0]

        self.installer = installer.Installer()
        self.installer.connect("appstream-changed", self.on_appstream_changed)
        self.task_cancellable = None
        self.current_task = None
        self.recursion_buster = False

        self.install_on_startup_file = None

        self.review_cache = None
        self.current_pkginfo = None
        self.current_category = None

        self.flatpak_remote_categories = {}

        self.picks_tiles = []
        self.category_tiles = []

        # Pages with expensive contents are built on first use only.
        self.sources_page = None
        self.prefs_widget = None
        self.deb_page = None
        self.deb_files_window = None
        self.deb_files_temp_dir = None
        self.current_deb_path = None
        self.current_deb_metadata = None
        self.current_deb_package = None
        self.current_deb_version = None
        self.deb_icon_path = None
        self._update_check_running = False
        self._upgradable_hashes = set()
        self._installed_pkg_hashes = []

        self.one_package_idle_timer = 0
        self.installer_pulse_timer = 0
        self.search_changed_timer = 0
        self.search_idle_timer = 0

        self.action_button_signal_id = 0
        self.launch_button_signal_id = 0

        self.banner_app_name = None
        self.featured_app_names = []

        self.add_categories()

        self.main_window = None

    @print_timing
    def do_activate(self):
        if self.main_window is None:
            self.create_window(self.PAGE_LOADING)
            self.add_window(self.main_window)
            self.update_conditional_widgets()

            t = threading.Thread(target=self._init_installer_thread, args=[])
            t.start()

        self.main_window.present()

    def _init_installer_thread(self):
        if self.installer.init_sync():
            GLib.idle_add(self.on_installer_ready)
        else:
            self.page_stack.set_visible_child_name(self.PAGE_GENERATING_CACHE)
            self.installer.init(self.on_installer_ready)

    def do_command_line(self, command_line, data=None):
        Gtk.Application.do_command_line(self, command_line)
        args = command_line.get_arguments()

        num = len(args)

        if num > 1 and args[1] == "list":
            sys.exit(self.export_listing(flatpak_only=False))
        elif num > 1 and args[1] == "list-flatpak":
            sys.exit(self.export_listing(flatpak_only=True))
        elif num == 3 and args[1] == "install":
            if self.open_file_argument(args[2]):
                return 0

            print("MintInstall: file not found", args[2])
            sys.exit(1)
        elif num == 2 and args[1].endswith((".deb", ".flatpakref", ".flatpakrepo", ".metainfo.xml", ".appdata.xml")):
            if self.open_file_argument(args[1]):
                return 0

            print("MintInstall: file not found", args[1])
            sys.exit(1)
        elif num == 2 and args[1].startswith("appstream://"):
            self.open([Gio.File.new_for_uri(args[1])], "")
            self.activate()
            return 0
        elif num > 1:
            print("MintInstall: Unknown arguments", args[1:])
            sys.exit(1)

        self.activate()
        return 0

    def open_file_argument(self, argument):
        for try_method in (Gio.File.new_for_path, Gio.File.new_for_uri):
            file = try_method(argument)

            if file.query_exists(None):
                self.open([file], "")
                self.activate()
                return True

        return False

    def do_open(self, files, num, hint):
        if self.gui_ready:
            self.handle_command_line_install(files[0])
        else:
            self.install_on_startup_file = files[0]

    def handle_command_line_install(self, file):
        path = file.get_path()

        if path is None:
            uri = file.get_uri()

            if uri is not None and uri.startswith("appstream://"):
                self.show_appstream_id(uri[len("appstream://"):])

            return

        if path.endswith(".deb"):
            self.show_deb_page(path)
        elif path.endswith((".metainfo.xml", ".appdata.xml")):
            self.show_appstream_page(path)
        elif path.endswith(".flatpakrepo"):
            if self.installer.is_busy():
                dialog = Gtk.MessageDialog(self.main_window,
                                           Gtk.DialogFlags.MODAL,
                                           Gtk.MessageType.WARNING,
                                           Gtk.ButtonsType.OK,
                                           _("Cannot process this file while there are active operations.\nPlease try again after they finish."))
                res = dialog.run()
                dialog.destroy()
                return

            self.start_add_new_flatpak_remote(file)
        elif path.endswith(".flatpakref"):
            self.installer.get_pkginfo_from_ref_file(file, self.on_pkginfo_from_uri_complete)

    def build_deb_page(self):
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        content.set_border_width(24)
        content.set_valign(Gtk.Align.START)
        content.set_halign(Gtk.Align.CENTER)
        scrolled.add(content)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        inner.set_size_request(620, -1)
        content.pack_start(inner, False, False, 0)

        dependency_box = Gtk.Box(spacing=12)
        dependency_icon = Gtk.Image(icon_name="dialog-warning", icon_size=Gtk.IconSize.LARGE_TOOLBAR)
        dependency_icon.set_valign(Gtk.Align.START)

        self.deb_dependency_label = Gtk.Label(xalign=0)
        self.deb_dependency_label.set_line_wrap(True)
        self.deb_dependency_label.set_max_width_chars(70)
        self.deb_dependency_label.set_selectable(True)
        self.deb_dependency_label.get_style_context().add_class("error")

        dependency_box.pack_start(dependency_icon, False, False, 0)
        dependency_box.pack_start(self.deb_dependency_label, True, True, 0)
        dependency_box.set_no_show_all(True)
        inner.pack_start(dependency_box, False, False, 0)
        self.deb_dependency_box = dependency_box

        header = Gtk.Box(spacing=18)

        self.deb_icon = Gtk.Image()
        self.deb_icon.set_pixel_size(96)
        self.deb_icon.set_valign(Gtk.Align.START)
        header.pack_start(self.deb_icon, False, False, 0)

        header_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        header_text.set_valign(Gtk.Align.CENTER)

        self.deb_name_label = Gtk.Label(xalign=0)
        self.deb_name_label.set_line_wrap(True)
        self.deb_name_label.set_selectable(True)
        header_text.pack_start(self.deb_name_label, False, False, 0)

        self.deb_summary_label = Gtk.Label(xalign=0)
        self.deb_summary_label.set_line_wrap(True)
        self.deb_summary_label.set_max_width_chars(70)
        self.deb_summary_label.get_style_context().add_class("dim-label")
        header_text.pack_start(self.deb_summary_label, False, False, 0)

        header.pack_start(header_text, True, True, 0)

        self.deb_files_button = Gtk.Button(label=_("Included files"))
        self.deb_files_button.set_valign(Gtk.Align.CENTER)
        self.deb_files_button.connect("clicked", self.on_deb_files_clicked)
        header.pack_start(self.deb_files_button, False, False, 0)

        inner.pack_start(header, False, False, 0)

        inner.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)

        self.deb_info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        inner.pack_start(self.deb_info_box, False, False, 0)

        self.deb_description_label = Gtk.Label(xalign=0)
        self.deb_description_label.set_line_wrap(True)
        self.deb_description_label.set_max_width_chars(70)
        self.deb_description_label.set_selectable(True)
        inner.pack_start(self.deb_description_label, False, False, 0)

        warning_box = Gtk.Box(spacing=12)
        warning_icon = Gtk.Image(icon_name="dialog-information", icon_size=Gtk.IconSize.LARGE_TOOLBAR)
        warning_icon.set_valign(Gtk.Align.START)
        warning_label = Gtk.Label(xalign=0)
        warning_label.set_line_wrap(True)
        warning_label.set_max_width_chars(70)
        warning_label.set_label(_("Only install packages from sources you trust. Packages installed this way are not checked or reviewed by %s.") % get_os_name())
        warning_box.pack_start(warning_icon, False, False, 0)
        warning_box.pack_start(warning_label, True, True, 0)
        inner.pack_start(warning_box, False, False, 0)
        self.deb_warning_box = warning_box

        action_box = Gtk.Box(spacing=12)

        self.deb_install_button = Gtk.Button(label=_("Install"))
        self.deb_install_button.get_style_context().add_class("suggested-action")
        self.deb_install_button.connect("clicked", self.on_deb_install_clicked)
        action_box.pack_start(self.deb_install_button, False, False, 0)

        self.deb_remove_button = Gtk.Button(label=_("Remove"))
        self.deb_remove_button.get_style_context().add_class("destructive-action")
        self.deb_remove_button.connect("clicked", self.on_deb_remove_clicked)
        self.deb_remove_button.set_no_show_all(True)
        action_box.pack_start(self.deb_remove_button, False, False, 0)

        self.deb_spinner = Gtk.Spinner()
        self.deb_spinner.set_no_show_all(True)
        action_box.pack_start(self.deb_spinner, False, False, 0)

        self.deb_status_label = Gtk.Label(xalign=0)
        self.deb_status_label.set_no_show_all(True)
        self.deb_status_label.set_line_wrap(True)
        self.deb_status_label.set_max_width_chars(60)
        self.deb_status_label.get_style_context().add_class("dim-label")
        action_box.pack_start(self.deb_status_label, True, True, 0)

        inner.pack_start(action_box, False, False, 0)
        self.deb_action_box = action_box

        self.deb_page = scrolled
        self.page_stack.add_named(scrolled, self.PAGE_DEB)
        scrolled.show_all()
        self.deb_spinner.hide()
        self.deb_status_label.hide()

    def show_deb_page(self, path):
        if self.installer.is_busy():
            dialog = Gtk.MessageDialog(self.main_window,
                                       Gtk.DialogFlags.MODAL,
                                       Gtk.MessageType.WARNING,
                                       Gtk.ButtonsType.OK,
                                       _("Cannot process this file while there are active operations.\nPlease try again after they finish."))
            dialog.run()
            dialog.destroy()
            return

        metadata = debfile.read_metadata(path)

        if metadata is None:
            dialog = Gtk.MessageDialog(self.main_window,
                                       Gtk.DialogFlags.MODAL,
                                       Gtk.MessageType.ERROR,
                                       Gtk.ButtonsType.OK,
                                       _("'%s' could not be read as a Debian package.") % os.path.basename(path))
            dialog.run()
            dialog.destroy()
            self.finish_loading_visual()
            return

        if self.deb_page is None:
            self.build_deb_page()

        package = metadata.get("Package", os.path.basename(path))
        summary, description = debfile.split_description(metadata.get("Description", ""))

        self.current_deb_path = path
        self.current_deb_metadata = metadata
        self.current_deb_package = package
        self.current_deb_version = metadata.get("Version", "")

        self.deb_name_label.set_markup("<span size='x-large' weight='bold'>%s</span>" % GLib.markup_escape_text(package))
        self.deb_summary_label.set_label(summary)
        self.deb_summary_label.set_visible(summary != "")

        icon_path = debfile.find_icon(path, package)
        self.set_local_page_icon(icon_path, package)

        if description != "":
            self.deb_description_label.set_label(description)
            self.deb_description_label.show()
        else:
            self.deb_description_label.hide()

        self.deb_warning_box.show()
        self.deb_action_box.show()
        self.deb_files_button.show()
        self.deb_spinner.stop()
        self.deb_spinner.hide()
        self.deb_status_label.set_label("")
        self.deb_status_label.hide()
        self.deb_dependency_box.hide()

        self.refresh_deb_state()

        # apt has to resolve the dependencies, can take a moment: only do it when the page is open.
        threading.Thread(target=self._check_deb_dependencies_thread, args=(path,), daemon=True).start()

        self.current_pkginfo = None
        self.previous_page = self.PAGE_LANDING
        self.back_button.set_sensitive(True)
        self.page_stack.set_visible_child_name(self.PAGE_DEB)

    def build_deb_rows(self, installed_version):
        metadata = self.current_deb_metadata
        path = self.current_deb_path
        rows = []

        if metadata.get("Version"):
            rows.append((_("Version"), metadata["Version"]))

        if installed_version:
            rows.append((_("Installed version"), installed_version))

        if metadata.get("Architecture"):
            rows.append((_("Architecture"), metadata["Architecture"]))

        rows.append((_("File"), os.path.basename(path)))

        try:
            rows.append((_("Size"), get_size_for_display(os.path.getsize(path))))
        except OSError:
            pass

        if metadata.get("Maintainer"):
            rows.append((_("Maintainer"), metadata["Maintainer"]))

        if metadata.get("Homepage"):
            rows.append((_("Homepage"), metadata["Homepage"]))

        return rows

    def refresh_deb_state(self):
        """Re-read the installed state and set the rows and action buttons accordingly."""
        installed_version = debfile.get_installed_version(self.current_deb_package)

        self.set_local_page_rows(self.build_deb_rows(installed_version))

        self.deb_install_button.set_sensitive(True)
        self.deb_remove_button.set_sensitive(True)

        if installed_version is None:
            self.deb_install_button.set_label(_("Install"))
            self.deb_install_button.show()
            self.deb_remove_button.hide()
        else:
            if debfile.is_newer(self.current_deb_version, installed_version):
                self.deb_install_button.set_label(_("Update"))
                self.deb_install_button.show()
            else:
                self.deb_install_button.hide()

            self.deb_remove_button.show()

        return installed_version

    def _check_deb_dependencies_thread(self, path):
        unmet = debfile.get_unmet_dependencies(path)
        GLib.idle_add(self.on_deb_dependencies_ready, path, unmet)

    def on_deb_dependencies_ready(self, path, unmet):
        if path != self.current_deb_path:
            return False

        if unmet:
            title = GLib.markup_escape_text(_("Unmet dependencies"))
            dependencies = GLib.markup_escape_text(", ".join(unmet))
            self.deb_dependency_label.set_markup("<b>%s</b>\n%s" % (title, dependencies))
            self.deb_dependency_box.show()
        else:
            self.deb_dependency_box.hide()

        return False

    def on_deb_files_clicked(self, button):
        if self.current_deb_path is None:
            return

        if self.deb_files_window is None:
            self.build_deb_files_window()

        path = self.current_deb_path

        if self.deb_icon.get_pixbuf() is not None:
            self.deb_files_icon.set_from_pixbuf(self.deb_icon.get_pixbuf())
        else:
            self.deb_files_icon.set_from_icon_name("linuxmint-logo-badge-symbolic", Gtk.IconSize.DIALOG)

        self.deb_files_name_label.set_markup("<b>%s</b>" % GLib.markup_escape_text(self.current_deb_package or os.path.basename(path)))
        self.deb_files_count_label.set_label(_("Loading..."))
        self.deb_files_store.clear()
        self.deb_files_stack.set_visible_child_name("spinner")

        self.deb_files_window.show_all()
        self.deb_files_spinner.start()

        # The listing is only read when the window is actually opened.
        threading.Thread(target=self._load_deb_files_thread, args=(path,), daemon=True).start()

    def _load_deb_files_thread(self, path):
        entries = debfile.list_contents(path)
        GLib.idle_add(self.on_deb_files_ready, path, entries)

    def on_deb_files_ready(self, path, entries):
        if path != self.current_deb_path:
            return False

        self.deb_files_spinner.stop()
        self.deb_files_store.clear()

        # Only files are listed, directories are left out.
        files = [entry for entry in entries if not entry[2]]

        for member, size, is_dir in files:
            name = member[2:] if member.startswith("./") else member
            self.deb_files_store.append(["text-x-generic-symbolic", name, get_size_for_display(size), member, False])

        self.deb_files_count_label.set_label(gettext.ngettext("%d file", "%d files", len(files)) % len(files))
        self.deb_files_stack.set_visible_child_name("list")

        return False

    def on_deb_files_row_activated(self, view, tree_path, column):
        """Double click (or Enter) on a file: open it with the default application."""
        if self.current_deb_path is None:
            return

        row = self.deb_files_store[tree_path]
        member, is_dir = row[3], row[4]

        if is_dir:
            return

        if self.deb_files_temp_dir is None or not os.path.isdir(self.deb_files_temp_dir):
            self.deb_files_temp_dir = tempfile.mkdtemp(prefix="mintinstall-deb-files-")

        # A directory of its own per opened file, so equal names from different folders can't clash.
        directory = tempfile.mkdtemp(dir=self.deb_files_temp_dir)

        self.deb_files_window.get_window().set_cursor(Gdk.Cursor.new_from_name(Gdk.Display.get_default(), "wait"))
        threading.Thread(target=self._extract_deb_file_thread,
                         args=(self.current_deb_path, member, directory), daemon=True).start()

    def _extract_deb_file_thread(self, path, member, directory):
        extracted = debfile.extract_to_directory(path, member, directory)
        GLib.idle_add(self.on_deb_file_extracted, member, extracted)

    def on_deb_file_extracted(self, member, extracted):
        window = self.deb_files_window

        if window.get_window() is not None:
            window.get_window().set_cursor(None)

        error = None

        if extracted is None:
            error = _("Could not extract '%s' from the package.") % member
        else:
            try:
                # Uses the default application registered for the file type (XDG mime associations).
                Gtk.show_uri_on_window(window, Gio.File.new_for_path(extracted).get_uri(), Gtk.get_current_event_time())
            except GLib.Error as e:
                error = _("Could not open '%s': %s") % (os.path.basename(extracted), e.message)

        if error is not None:
            dialog = Gtk.MessageDialog(window,
                                       Gtk.DialogFlags.MODAL,
                                       Gtk.MessageType.ERROR,
                                       Gtk.ButtonsType.OK,
                                       error)
            dialog.run()
            dialog.destroy()

        return False

    def on_deb_files_window_delete(self, window, event):
        window.hide()
        return True

    def build_deb_files_window(self):
        window = Gtk.Window()
        window.set_title(_("Included files"))
        window.set_transient_for(self.main_window)
        window.set_destroy_with_parent(True)
        window.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
        window.set_default_size(560, 480)
        window.connect("delete-event", self.on_deb_files_window_delete)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_border_width(12)
        window.add(box)

        header = Gtk.Box(spacing=12)

        self.deb_files_icon = Gtk.Image()
        self.deb_files_icon.set_pixel_size(48)
        header.pack_start(self.deb_files_icon, False, False, 0)

        header_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        header_text.set_valign(Gtk.Align.CENTER)

        self.deb_files_name_label = Gtk.Label(xalign=0)
        self.deb_files_name_label.set_line_wrap(True)
        self.deb_files_name_label.set_selectable(True)
        header_text.pack_start(self.deb_files_name_label, False, False, 0)

        self.deb_files_count_label = Gtk.Label(xalign=0)
        self.deb_files_count_label.get_style_context().add_class("dim-label")
        header_text.pack_start(self.deb_files_count_label, False, False, 0)

        header.pack_start(header_text, True, True, 0)
        box.pack_start(header, False, False, 0)

        stack = Gtk.Stack()
        stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

        self.deb_files_spinner = Gtk.Spinner()
        self.deb_files_spinner.set_size_request(32, 32)
        self.deb_files_spinner.set_halign(Gtk.Align.CENTER)
        self.deb_files_spinner.set_valign(Gtk.Align.CENTER)
        stack.add_named(self.deb_files_spinner, "spinner")

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        # icon, displayed path, displayed size, member name inside the deb, is a directory
        self.deb_files_store = Gtk.ListStore(str, str, str, str, bool)
        view = Gtk.TreeView(model=self.deb_files_store)
        view.connect("row-activated", self.on_deb_files_row_activated)

        icon_renderer = Gtk.CellRendererPixbuf()
        view.append_column(Gtk.TreeViewColumn("", icon_renderer, icon_name=0))

        path_renderer = Gtk.CellRendererText()
        path_renderer.set_property("ellipsize", Pango.EllipsizeMode.MIDDLE)
        path_column = Gtk.TreeViewColumn(_("File"), path_renderer, text=1)
        path_column.set_expand(True)
        view.append_column(path_column)

        size_renderer = Gtk.CellRendererText()
        size_renderer.set_property("xalign", 1.0)
        view.append_column(Gtk.TreeViewColumn(_("Size"), size_renderer, text=2))

        scrolled.add(view)
        stack.add_named(scrolled, "list")

        box.pack_start(stack, True, True, 0)

        self.deb_files_stack = stack
        self.deb_files_window = window

    def set_local_page_icon(self, icon_path, icon_name=None):
        if icon_path is not None:
            if self.deb_icon_path is not None and self.deb_icon_path != icon_path:
                debfile.remove_temp_file(self.deb_icon_path)

            self.deb_icon_path = icon_path

            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file(icon_path)
                width, height = pixbuf.get_width(), pixbuf.get_height()

                if width > 96 or height > 96:
                    scale = min(96.0 / width, 96.0 / height)
                    pixbuf = pixbuf.scale_simple(max(1, int(width * scale)), max(1, int(height * scale)), GdkPixbuf.InterpType.BILINEAR)

                self.deb_icon.set_from_pixbuf(pixbuf)
                return
            except GLib.Error:
                pass

        if icon_name is not None and Gtk.IconTheme.get_default().has_icon(icon_name):
            self.deb_icon.set_from_icon_name(icon_name, Gtk.IconSize.DIALOG)
        else:
            self.deb_icon.set_from_icon_name("linuxmint-logo-badge-symbolic", Gtk.IconSize.DIALOG)

    def set_local_page_rows(self, rows):
        for child in self.deb_info_box.get_children():
            child.destroy()

        for caption, value in rows:
            row = Gtk.Box(spacing=12)

            caption_label = Gtk.Label(label=caption, xalign=0)
            caption_label.set_size_request(120, -1)
            caption_label.set_valign(Gtk.Align.START)
            caption_label.get_style_context().add_class("dim-label")
            row.pack_start(caption_label, False, False, 0)

            value_label = Gtk.Label(label=value, xalign=0)
            value_label.set_line_wrap(True)
            value_label.set_max_width_chars(60)
            value_label.set_selectable(True)
            row.pack_start(value_label, True, True, 0)

            self.deb_info_box.pack_start(row, False, False, 0)
            row.show_all()

    def show_appstream_id(self, component_id):
        pkginfo = appstreamfile.find_pkginfo_by_id(self.installer, component_id)
        clean_id = appstreamfile._parse_appstream_arg(component_id)[0] or component_id

        if pkginfo is None:
            dialog = Gtk.MessageDialog(self.main_window,
                                       Gtk.DialogFlags.MODAL,
                                       Gtk.MessageType.ERROR,
                                       Gtk.ButtonsType.OK,
                                       _("Could not find '%s' in the package catalog.") % clean_id)
            dialog.run()
            dialog.destroy()
            self.finish_loading_visual()
            return

        self.show_package(pkginfo, self.PAGE_LANDING)

    def show_appstream_page(self, path):
        metadata = appstreamfile.read_metadata(path, self.locale)

        if metadata is None:
            dialog = Gtk.MessageDialog(self.main_window,
                                       Gtk.DialogFlags.MODAL,
                                       Gtk.MessageType.ERROR,
                                       Gtk.ButtonsType.OK,
                                       _("'%s' could not be read as an AppStream file.") % os.path.basename(path))
            dialog.run()
            dialog.destroy()
            self.finish_loading_visual()
            return

        # If the component is in the catalog, open its regular package page so it can be installed.
        pkginfo = appstreamfile.find_pkginfo(self.installer, metadata)

        if pkginfo is not None:
            self.show_package(pkginfo, self.PAGE_LANDING)
            return

        if self.deb_page is None:
            self.build_deb_page()

        self.current_deb_path = None

        self.deb_name_label.set_markup("<span size='x-large' weight='bold'>%s</span>" % GLib.markup_escape_text(metadata["name"] or os.path.basename(path)))
        self.deb_summary_label.set_label(metadata["summary"])
        self.deb_summary_label.set_visible(metadata["summary"] != "")

        self.set_local_page_icon(metadata["icon_path"], metadata["icon_name"])

        rows = []

        if metadata["version"] != "":
            rows.append((_("Version"), metadata["version"]))

        if metadata["developer"] != "":
            rows.append((_("Developer"), metadata["developer"]))

        if metadata["license"] != "":
            rows.append((_("License"), metadata["license"]))

        if metadata["homepage"] != "":
            rows.append((_("Homepage"), metadata["homepage"]))

        if metadata["id"] != "":
            rows.append((_("Application ID"), metadata["id"]))

        rows.append((_("File"), os.path.basename(path)))

        self.set_local_page_rows(rows)

        if metadata["description"] != "":
            self.deb_description_label.set_label(metadata["description"])
            self.deb_description_label.show()
        else:
            self.deb_description_label.hide()

        self.deb_install_button.hide()
        self.deb_remove_button.hide()
        self.deb_warning_box.hide()
        self.deb_files_button.hide()
        self.deb_dependency_box.hide()
        self.deb_action_box.show()
        self.deb_spinner.stop()
        self.deb_spinner.hide()
        self.deb_status_label.set_label(_("This application is not available in the configured repositories."))
        self.deb_status_label.show()

        self.current_pkginfo = None
        self.previous_page = self.PAGE_LANDING
        self.back_button.set_sensitive(True)
        self.page_stack.set_visible_child_name(self.PAGE_DEB)

    def confirm_package_changes(self, package_names):
        """Confirm upgrading the given packages, with the window installs and upgrades use."""
        from mintcommon.installer.installer import InstallerTask
        from mintcommon.installer.pkgInfo import AptPkgInfo

        task = InstallerTask(
            pkginfo=None,
            installer=self.installer,
            client_info_ready_callback=None,
            client_info_error_callback=None,
            client_installer_finished_cb=None,
            client_installer_progress_cb=None,
            installer_cleanup_cb=None,
            installer_error_cleanup_cb=None,
            use_mainloop=True,
        )
        # The dialog lists apt changes only for packages coming from apt.
        task.pkginfo = AptPkgInfo(pkg_hash="apt:" + package_names[0])
        task.parent_window = self.main_window
        task.type = InstallerTask.UPDATE_TASK
        task.to_update = [DebChangeEntry(name) for name in package_names]

        dia = dialogs.ChangesConfirmDialog(None, task, parent=self.main_window)
        res = dia.run()
        dia.hide()
        dia.destroy()

        return res == Gtk.ResponseType.OK

    def on_deb_install_clicked(self, button):
        self.start_deb_action(update=(button.get_label() == _("Update")))

    def on_deb_remove_clicked(self, button):
        self.start_deb_action(remove=True)

    def start_deb_action(self, update=False, remove=False):
        if remove:
            if self.current_deb_package is None:
                return
        elif self.current_deb_path is None:
            return

        if update and not self.confirm_package_changes([self.current_deb_package]):
            return

        self.deb_install_button.set_sensitive(False)
        self.deb_remove_button.set_sensitive(False)
        self.deb_spinner.show()
        self.deb_spinner.start()
        self.deb_status_label.set_label(_("Removing...") if remove else _("Installing..."))
        self.deb_status_label.show()

        # apt can take a while, keep it off the UI thread.
        thread = threading.Thread(target=self._deb_action_thread, args=(remove, update), daemon=True)
        thread.start()

    def _deb_action_thread(self, remove, update):
        if remove:
            returncode, output = debfile.remove(self.current_deb_package)
        else:
            returncode, output = debfile.install(self.current_deb_path)

        GLib.idle_add(self.on_deb_action_finished, remove, update, returncode, output)

    def on_deb_action_finished(self, remove, update, returncode, output):
        self.deb_spinner.stop()
        self.deb_spinner.hide()

        self.refresh_deb_state()

        if returncode == 0:
            if remove:
                self.deb_status_label.set_label(_("Removed successfully"))
            elif update:
                self.deb_status_label.set_label(_("Updated successfully"))
            else:
                self.deb_status_label.set_label(_("Installed successfully"))
        elif returncode in (126, 127):
            self.deb_status_label.set_label(_("Action cancelled"))
        else:
            self.deb_status_label.set_label(_("The operation failed"))

            dialog = Gtk.MessageDialog(self.main_window,
                                       Gtk.DialogFlags.MODAL,
                                       Gtk.MessageType.ERROR,
                                       Gtk.ButtonsType.OK,
                                       _("The operation could not be completed."))
            dialog.format_secondary_text(output.strip()[-2000:] if output.strip() != "" else _("Unknown error"))
            dialog.run()
            dialog.destroy()

        return False

    def start_add_new_flatpak_remote(self, file):
        self.page_stack.set_visible_child_name(self.PAGE_GENERATING_CACHE)
        self.installer.add_remote_from_repo_file(file, self.add_new_flatpak_remote_finished)

    def add_new_flatpak_remote_finished(self, file=None, error=None):
        if error:
            if error == "exists":
                dialog = Gtk.MessageDialog(self.main_window,
                                           Gtk.DialogFlags.MODAL,
                                           Gtk.MessageType.WARNING,
                                           Gtk.ButtonsType.OK,
                                           _("The Flatpak repo you are trying to add already exists."))
                res = dialog.run()
                dialog.destroy()
            elif error == "error":
                dialog = Gtk.MessageDialog(self.main_window,
                                           Gtk.DialogFlags.MODAL,
                                           Gtk.MessageType.ERROR,
                                           Gtk.ButtonsType.OK,
                                           _("An error occurred attempting to add the Flatpak repo."))
                res = dialog.run()
                dialog.destroy()
            elif error == "no-flatpak-support":
                dialog = Gtk.MessageDialog(self.main_window,
                                           Gtk.DialogFlags.MODAL,
                                           Gtk.MessageType.ERROR,
                                           Gtk.ButtonsType.OK,
                                           _("Flatpak support is not currently available. Try installing flatpak."))
                res = dialog.run()
                dialog.destroy()
            elif error == "cancel":
                pass

            self.finish_loading_visual()
            return

        self.add_categories()
        self.installer.init(self.on_installer_ready)

    def on_pkginfo_from_uri_complete(self, pkginfo, error=None):
        if error:
            if error == "no-flatpak-support":
                dialog = Gtk.MessageDialog(self.main_window,
                                           Gtk.DialogFlags.MODAL,
                                           Gtk.MessageType.ERROR,
                                           Gtk.ButtonsType.OK,
                                           _("Flatpak support is not currently available. Try installing flatpak and gir1.2-flatpak-1.0."))
                res = dialog.run()
                dialog.destroy()
                self.finish_loading_visual()
                return
        if pkginfo:
            self.show_package(pkginfo, self.PAGE_LANDING)

    def set_default_window_size(self):
        display = Gdk.Display.get_default()
        pointer = display.get_default_seat().get_pointer()

        height = 9999

        if pointer:
            position = pointer.get_position()
            monitor = display.get_monitor_at_point(position.x, position.y)
            height = monitor.get_geometry().height

        # If it's less than our threshold than consider us 'low res'. The workarea being used is in
        # app pixels, so hidpi will also be affected here regardless of device resolution.
        if height < 800:
            print("MintInstall: low resolution detected (%dpx height), limiting window height." % (height))
            self.main_window.set_default_size(800, 550)
            return True

        return False

    def create_window(self, starting_page):
        if self.main_window is not None:
            print("MintInstall: create_window called, but we already had one!")
            return

        # Build the GUI
        self.builder = load_builder("mintinstall.glade")

        self.main_window = self.builder.get_object("main_window")
        self.main_window.set_title(_("Software Manager"))
        GLib.set_application_name(_("Software Manager"))
        self.set_default_window_size()

        self.main_window.set_icon_name("mintinstall")
        self.main_window.connect("delete_event", self.close_application)
        self.main_window.connect("key-press-event", self.on_keypress)
        self.main_window.connect("button-press-event", self.on_buttonpress)

        self.detail_view_icon = imaging.AsyncImage()
        self.detail_view_icon.show()
        self.builder.get_object("application_icon_holder").add(self.detail_view_icon)

        self.status_label = self.builder.get_object("label_ongoing")
        self.progressbar = self.builder.get_object("progressbar1")
        self.progress_box = self.builder.get_object("progress_box")
        self.action_button = self.builder.get_object("action_button")
        self.launch_button = self.builder.get_object("launch_button")
        self.single_update_button = self.builder.get_object("single_update_button")
        self.single_update_button.connect("clicked", self.on_single_update_clicked)
        self.unsafe_box = self.builder.get_object("unsafe_box")
        self.active_tasks_button = self.builder.get_object("active_tasks_button")
        self.active_tasks_spinner = self.builder.get_object("active_tasks_spinner")
        self.no_packages_found_label = self.builder.get_object("no_packages_found_label")

        self.no_packages_found_refresh_button = self.builder.get_object("no_packages_found_refresh_button")
        self.no_packages_found_refresh_button.connect("clicked", self.on_refresh_cache_clicked)

        self.progress_label = DottedProgressLabel()
        self.progress_box.pack_start(self.progress_label, False, False, 0)
        self.progress_label.show()

        box_reviews = self.builder.get_object("box_reviews")

        def list_header_func(row, before, user_data=None):
            if before and not row.get_header():
                row.set_header(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        box_reviews.set_header_func(list_header_func, None)

        # Build the menu
        submenu = Gtk.Menu()

        self.installed_menuitem = Gtk.MenuItem(label=_("Show installed applications"))
        self.installed_menuitem.connect("activate", self.show_installed_apps)
        self.installed_menuitem.show()
        submenu.append(self.installed_menuitem)

        separator = Gtk.SeparatorMenuItem()
        separator.show()
        submenu.append(separator)

        software_sources_menuitem = Gtk.MenuItem(label=_("Software sources"))
        software_sources_menuitem.connect("activate", self.open_software_sources)
        software_sources_menuitem.show()
        submenu.append(software_sources_menuitem)

        self.prefs_menuitem = Gtk.MenuItem(label=_("Preferences"))
        self.prefs_menuitem.connect("activate", self.on_prefs_clicked)
        self.prefs_menuitem.show()
        self.prefs_menuitem.set_sensitive(True)
        submenu.append(self.prefs_menuitem)

        separator = Gtk.SeparatorMenuItem()
        separator.show()
        submenu.append(separator)

        self.package_help_button = self.builder.get_object("package_help_button")
        self.package_help_button.connect("clicked", self.on_package_help_clicked)
        self.package_help_popover = Gtk.Popover(relative_to=self.package_help_button)
        self.package_help_popover.add(self.builder.get_object("package_help_content_box"))

        about_menuitem = Gtk.MenuItem(label=_("About"))
        about_menuitem.connect("activate", self.open_about)
        about_menuitem.show()
        submenu.append(about_menuitem)

        menu_button = self.builder.get_object("menu_button")
        menu_button.connect("clicked", self.on_menu_button_clicked, submenu)

        self.update_button = self.builder.get_object("update_button")
        self._update_available_count = 0
        self._high_priority_update = False
        self._update_button_spinner = None
        self._update_button_icon = Gtk.Image()
        self._update_button_icon.show()
        self.update_button.set_image(self._update_button_icon)
        self.update_button.set_always_show_image(True)
        self.update_button.set_tooltip_text(_("Updates"))

        # Stay disabled until the initial update check has finished, so it can't
        # be clicked while the application is still loading.
        self.update_button.set_sensitive(False)

        self._update_submenu = Gtk.Menu()

        self._check_updates_menuitem = Gtk.MenuItem(label=_("Check for updates"))
        self._check_updates_menuitem.connect("activate", self.on_apt_refresh_clicked)
        self._check_updates_menuitem.show()
        self._update_submenu.append(self._check_updates_menuitem)

        self._install_updates_menuitem = Gtk.MenuItem(label=_("Install updates"))
        self._install_updates_menuitem.connect("activate", self.on_update_all_clicked)
        self._install_updates_menuitem.show()
        self._update_submenu.append(self._install_updates_menuitem)

        self.update_button.connect("clicked", self._on_update_button_clicked)
        self._set_update_button_icon(0)

        flowbox = Gtk.FlowBox()
        flowbox.set_min_children_per_line(3)
        flowbox.set_max_children_per_line(10)
        flowbox.set_row_spacing(0)
        flowbox.set_column_spacing(0)
        flowbox.set_homogeneous(True)
        flowbox.connect("child-activated", self.on_app_row_activated, self.PAGE_LIST)
        flowbox.connect("selected-children-changed", self.navigate_flowbox, self.builder.get_object("scrolledwindow_applications"))
        self.flowbox_applications = flowbox

        # Built on demand in on_prefs_clicked - creating the settings widgets
        # up front only delays the first window.
        self.prefs_box = self.builder.get_object("box_prefs")
        self.prefs_warning_box = self.builder.get_object("box_unverified_warning")

        box = self.builder.get_object("box_cat_page")
        box.add(self.flowbox_applications)

        self.back_button = self.builder.get_object("back_button")
        self.back_button.connect("clicked", self.on_back_button_clicked)
        self.previous_page = self.PAGE_LANDING
        self.back_button.set_sensitive(False)

        self.searchentry = self.builder.get_object("search_entry")
        self.searchentry.connect("changed", self.on_entry_text_changed)
        self.searchentry.connect("activate", self.on_search_entry_activated)

        self.subsearch_toggle = self.builder.get_object("subsearch_toggle")
        self.subsearch_toggle.set_active(self.settings.get_boolean(prefs.SEARCH_IN_CATEGORY))
        self.subsearch_toggle.connect("toggled", self.on_subsearch_toggled)

        self.active_tasks_button.connect("clicked", self.on_active_tasks_button_clicked)
        self.update_activity_widgets()

        self.page_stack = self.builder.get_object("page_stack")

        # The sources page is created only when it is opened, see
        # open_software_sources().  Building it here reads the APT
        # configuration and runs gpg on every keyring, which must not delay
        # the start of the application.

        self.page_stack.set_visible_child_name(starting_page)

        self.addons_listbox = self.builder.get_object("box_addons")
        self.addons_listbox.set_header_func(list_header_func, None)
        self.package_details_listbox = self.builder.get_object("package_details_listbox")

        self.app_list_stack = self.builder.get_object("app_list_stack")

        self.flatpak_details_vgroup = XApp.VisibilityGroup.new(True, True,
            (
                self.builder.get_object("branch_row"),
                self.builder.get_object("remote_row")
            )
        )

        self.screenshot_controls_vgroup = XApp.VisibilityGroup.new(False, True,
            [
                self.builder.get_object("previous_ss_button"),
                self.builder.get_object("next_ss_button"),
            ]
        )

        self.search_tool_item = self.builder.get_object("search_tool_item")

        self.flowbox_featured = None
        self.flowbox_top_rated = None
        self.banner_tile = None
        self.banner_stack = None
        self.banner_dots_box = None
        self.banner_slideshow_timeout_id = 0

        self.package_type_store = Gtk.ListStore(int, str, str, str, object) # index, label, summary, icon-name, remotename, pkginfo

        box = Gtk.CellAreaBox(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        cell = Gtk.CellRendererPixbuf(stock_size=Gtk.IconSize.BUTTON)
        box.pack_start(cell, False, False, True)
        box.add_attribute(cell, "icon-name", PACKAGE_TYPE_COMBO_ICON_NAME)
        cell = Gtk.CellRendererText(xalign=0.0)
        box.pack_start(cell, False, False,  True)
        box.add_attribute(cell, "text", PACKAGE_TYPE_COMBO_LABEL)

        self.package_type_combo = NonScrollingComboBox(box)
        self.package_type_combo.set_model(self.package_type_store)
        self.package_type_combo.show_all()
        self.package_type_combo_container = self.builder.get_object("package_type_combo_container")
        self.package_type_combo_container.pack_start(self.package_type_combo, True, True, 0)
        self.single_version_package_type_box = self.builder.get_object("single_version_package_type_box")
        self.single_version_package_type_icon = self.builder.get_object("single_version_package_type_icon")
        self.single_version_package_type_label = self.builder.get_object("single_version_package_type_label")

        review_breakdown_grid = self.builder.get_object("review_breakdown_grid")
        self.star_bars = []

        for i in range(5, 0, -1):
            bar = SaneProgressBar()
            review_breakdown_grid.attach(bar, 1, i - 1, 1, 1)
            self.star_bars.append(bar)

        self.screenshot_stack = self.builder.get_object("screenshot_stack")
        self.screenshot_stack.connect("notify::visible-child", self.on_screenshot_shown)

        self.select_cursor = Gdk.Cursor.new_from_name(Gdk.Display.get_default(), "pointer")
        self.screenshot_window = None

        self.builder.get_object("previous_ss_button").connect("clicked", self.navigate_screenshot, Gtk.DirectionType.TAB_BACKWARD)
        self.builder.get_object("next_ss_button").connect("clicked", self.navigate_screenshot, Gtk.DirectionType.TAB_FORWARD)
        self.ss_swipe_handler = Gtk.GestureSwipe.new(self.screenshot_stack)
        self.ss_swipe_handler.connect("swipe", self.screenshot_stack_swiped, self.screenshot_stack)
        self.ss_swipe_handler.set_propagation_phase(Gtk.PropagationPhase.NONE)

        # This is only for the screenshot stack at the moment, as I can't get key events from the stack, even
        # with an event controller.
        self.main_window.connect("key-press-event", self.on_window_key_press)

        self.searchentry.grab_focus()

        box = self.builder.get_object("box_subcategories")

        self.subcat_flowbox = Gtk.FlowBox(homogeneous=True)
        self.subcat_flowbox.set_min_children_per_line(1)
        self.subcat_flowbox.set_max_children_per_line(4)
        self.subcat_flowbox.set_row_spacing(0)
        self.subcat_flowbox.set_column_spacing(0)

        box.pack_start(self.subcat_flowbox, True, True, 0)
        self.subcat_flowbox.connect("child-activated", self.on_subcategory_selected)

    def refresh_cache(self):
        self.page_stack.set_visible_child_name(self.PAGE_GENERATING_CACHE)

        self.installer.force_new_cache(self._on_refresh_cache_complete)

    def _on_refresh_cache_complete(self):
        self.add_categories()
        self.installer.init(self.on_installer_ready)

    def on_prefs_clicked(self, widget, data=None):
        if self.prefs_widget is None:
            self.prefs_widget = prefs.PrefsWidget(self.prefs_warning_box)
            self.prefs_box.pack_start(self.prefs_widget, True, True, 0)
            self.prefs_box.show_all()

        self.previous_page = self.PAGE_LANDING
        self.search_tool_item.set_sensitive(False)
        self.back_button.set_sensitive(True)
        self.page_stack.set_visible_child_name(self.PAGE_PREFS)

    def on_refresh_cache_clicked(self, widget, data=None):
        self.refresh_cache()

    def _on_update_button_clicked(self, button):
        if self._update_available_count > 0:
            self.on_menu_button_clicked(button, self._update_submenu)
        else:
            self.on_apt_refresh_clicked(button)

    def _set_update_button_icon(self, n_updates):
        if n_updates <= 0:
            icon_name = "update-none-symbolic"
        elif self._high_priority_update:
            icon_name = "update-high-symbolic"
        else:
            icon_name = "update-medium-symbolic"
        self._update_button_icon.set_from_icon_name(icon_name, Gtk.IconSize.BUTTON)
        if self.update_button.get_image() is not self._update_button_icon:
            self.update_button.set_image(self._update_button_icon)
        self.update_button.set_tooltip_text(_("Updates"))

    def _set_update_button_loading(self):
        # The header button shows its own spinner while the check runs, so it
        # never blocks or waits for the page content.
        if self._update_button_spinner is not None:
            return
        spinner = Gtk.Spinner(active=True, visible=True)
        spinner.set_size_request(16, 16)
        self._update_button_spinner = spinner
        self.update_button.set_image(spinner)
        self.update_button.set_tooltip_text(_("Checking for updates..."))

    def _clear_update_button_loading(self):
        spinner = self._update_button_spinner
        if spinner is None:
            return
        spinner.stop()
        self._update_button_spinner = None

    def _count_all_upgradable(self):
        """Returns (count, APT package names) of upgradable packages.

        This runs in a worker thread - it must not touch widgets.  It reads the
        existing package caches and never refreshes the package lists.
        """
        apt_names = []
        try:
            import apt as _apt_mod
            cache = _apt_mod.Cache()
            apt_names = [pkg.name for pkg in cache if pkg.is_upgradable]
        except Exception as e:
            print("MintInstall: could not count APT upgradable packages:", e)

        fp_pkginfos = []
        try:
            if self.installer.have_flatpak:
                fp_pkginfos = self.installer.list_updated_flatpak_pkginfos()
        except Exception as e:
            print("MintInstall: could not count Flatpak upgradable packages:", e)

        return len(apt_names) + len(fp_pkginfos), apt_names, fp_pkginfos

    def _start_update_check(self):
        self._refresh_update_button_state()
        return False

    def _refresh_update_button_state(self):
        # Keep the button disabled until the check is done, so it can't be
        # triggered before we know the update state.
        self.update_button.set_sensitive(False)

        if self._update_check_running:
            return

        self._update_check_running = True
        self._set_update_button_loading()

        def _worker():
            result = (0, [], [])
            try:
                result = self._count_all_upgradable()
            except Exception as e:
                print("MintInstall: could not check for updates:", e)
            GLib.idle_add(self._apply_update_button_state, result)
        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def _apply_update_button_state(self, result):
        n_updates, upgradable_names, fp_pkginfos = result
        self._update_check_running = False
        self._update_available_count = n_updates
        self._high_priority_update = any(
            name in ("linux-image-amd64", "linux-image-arm64")
            for name in upgradable_names
        )
        self._upgradable_hashes = set("apt:" + name for name in upgradable_names)
        self._upgradable_hashes.update(pkg.pkg_hash for pkg in fp_pkginfos)
        self._clear_update_button_loading()
        self._set_update_button_icon(n_updates)
        self._sync_upgradable_to_installed_category(upgradable_names, fp_pkginfos)
        self.update_button.set_sensitive(True)
        return False

    def _is_pkginfo_upgradable(self, pkginfo):
        if pkginfo is None:
            return False
        try:
            return pkginfo.pkg_hash in self._upgradable_hashes
        except AttributeError:
            return False

    def _sync_upgradable_to_installed_category(self, upgradable_names, fp_pkginfos):
        # Rebuild the installed list from the packages MintInstall knows about,
        # plus everything that has a pending update right now.  Rebuilding (and
        # not just appending) means apps disappear again as soon as their update
        # is applied, and deduplicating by pkg_hash keeps a single entry when an
        # app is both installed here and upgradable.
        try:
            pkginfos = []
            seen = set()

            hashes = list(self._installed_pkg_hashes)
            for name in upgradable_names:
                hashes.append("apt:" + name)
            for pkginfo in fp_pkginfos:
                hashes.append(pkginfo.pkg_hash)

            for pkg_hash in hashes:
                if pkg_hash in seen:
                    continue
                try:
                    pkginfo = self.installer.cache[pkg_hash]
                except KeyError:
                    continue
                seen.add(pkg_hash)
                pkginfos.append(pkginfo)

            self.installed_category.pkginfos = pkginfos
        except Exception as e:
            print("MintInstall: _sync_upgradable_to_installed_category error:", e)

        self._refresh_installed_view()

    def _refresh_installed_view(self):
        if not self.gui_ready:
            return
        if self.current_category == self.installed_category \
                and self.page_stack.get_visible_child_name() == self.PAGE_LIST:
            self.show_packages(self.installed_category.pkginfos, from_search=False)
        else:
            self.update_conditional_widgets()

    def on_apt_refresh_clicked(self, widget, data=None):
        self.update_button.set_sensitive(False)

        # Show the same "Generating cache" page used while the application
        # cache is being rebuilt.  Refreshing the APT lists can take a while,
        # and without this the window just sits on the old page and looks
        # frozen until the refresh finishes.
        self.page_stack.set_visible_child_name(self.PAGE_GENERATING_CACHE)

        def _do_refresh():
            try:
                import gi
                gi.require_version('PackageKitGlib', '1.0')
                from gi.repository import PackageKitGlib as pk
                client = pk.Task()
                client.refresh_cache_sync(False, None, lambda *a: None, None)
            except Exception as e:
                print("MintInstall: apt refresh error:", e)
            GLib.idle_add(self._on_apt_refresh_done)

        t = threading.Thread(target=_do_refresh, daemon=True)
        t.start()

    def _on_apt_refresh_done(self):
        self._refresh_update_button_state()
        self.refresh_cache()
        return False

    def on_update_all_clicked(self, widget, data=None):
        """Install all available updates (APT + Flatpak) via PackageKit/Flatpak, without a terminal."""
        try:
            from gi.repository import PackageKitGlib as pk

            # Hide the header button while the installation runs: the active
            # tasks spinner takes its place, and the button can't be hovered
            # for a stale "Checking for updates" tooltip meanwhile.
            self.update_button.hide()
            self.update_button.set_sensitive(False)

            # Refresh the APT lists first (like 'Check for updates' does), then
            # fetch the updates that are actually available afterwards.
            def _get_updates_and_run():
                try:
                    client = pk.Task()
                    client.refresh_cache_sync(False, None, lambda *a: None, None)
                    res = client.get_updates_sync(pk.FilterEnum.NONE, None, lambda *a: None, None)
                    sack = res.get_package_sack()
                    pk_pkgs = sack.get_array()
                except Exception as e:
                    print("MintInstall: PackageKit get_updates error:", e)
                    pk_pkgs = []
                GLib.idle_add(self._on_pk_updates_ready, pk_pkgs)

            t = threading.Thread(target=_get_updates_and_run, daemon=True)
            t.start()
        except Exception as e:
            print("MintInstall: on_update_all_clicked error:", e)

    def _on_pk_updates_ready(self, pk_pkgs):
        """Called in the main thread once the APT updates were fetched from PackageKit."""
        try:
            self._clear_update_button_loading()

            # Collect the Flatpak updates (synchronous - this call is fast)
            fp_pkginfos = []
            if self.installer.have_flatpak:
                try:
                    fp_pkginfos = self.installer.list_updated_flatpak_pkginfos()
                except Exception as e:
                    print("MintInstall: could not list flatpak updates:", e)

            if not pk_pkgs and not fp_pkginfos:
                self.update_button.show()
                self.update_button.set_sensitive(True)
                self._set_update_button_icon(self._update_available_count)
                return False

            # --- Simple confirmation dialog listing all updates ---
            dia = Gtk.Dialog(title=_("Updates"), transient_for=self.main_window, modal=True)
            dia.set_default_size(450, 380)
            dia.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
            dia.add_button(_("Update"), Gtk.ResponseType.OK)
            dia.set_default_response(Gtk.ResponseType.OK)

            content = dia.get_content_area()
            content.set_spacing(6)
            content.set_border_width(12)

            lbl = Gtk.Label()
            lbl.set_markup("<b><big>%s</big></b>\n\n%s" % (
                _("Updates are available"),
                _("The following packages will be upgraded:")
            ))
            lbl.set_xalign(0)
            lbl.set_line_wrap(True)
            content.pack_start(lbl, False, False, 0)

            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            scroll.set_min_content_height(200)

            store = Gtk.ListStore(str, str)  # name, type
            if pk_pkgs:
                for p in pk_pkgs:
                    store.append([p.get_name(), "APT"])
            if fp_pkginfos:
                for p in fp_pkginfos:
                    store.append([p.name, "Flatpak"])

            tv = Gtk.TreeView(model=store)
            tv.set_headers_visible(True)
            tv.append_column(Gtk.TreeViewColumn(_("Package"),
                Gtk.CellRendererText(), text=0))
            tv.append_column(Gtk.TreeViewColumn(_("Type"),
                Gtk.CellRendererText(), text=1))
            scroll.add(tv)
            content.pack_start(scroll, True, True, 0)

            content.show_all()
            res = dia.run()
            dia.hide()
            dia.destroy()

            if res != Gtk.ResponseType.OK:
                self.update_button.show()
                self.update_button.set_sensitive(True)
                self._set_update_button_icon(self._update_available_count)
                return False

            # Start the installation - counter to wait for both tasks to finish
            pending = [0]
            if pk_pkgs:
                pending[0] += 1
            if fp_pkginfos:
                pending[0] += 1

            self.update_button.set_sensitive(False)
            self.active_tasks_button.show()
            self.active_tasks_spinner.start()

            def _one_done(_task=None):
                pending[0] -= 1
                if pending[0] <= 0:
                    self._on_upgrade_all_done()

            self._fp_update_done_cb = _one_done

            # --- APT via PackageKit ---
            if pk_pkgs:
                def _apt_done(task=None):
                    if task is not None and getattr(task, "error_message", None):
                        _one_done(task)
                        return
                    # Clean up packages the update left behind before the
                    # list is refreshed, like 'apt autoremove -y' does.
                    self._run_autoremove(lambda: _one_done(task))

                self._execute_apt_updates(pk_pkgs, _apt_done)

            # --- Flatpak via the installer's built-in pipeline ---
            if fp_pkginfos:
                self.installer.select_flatpak_updates(
                    [],                            # [] = update everything available
                    self._on_fp_update_info_ready, # info_ready -> confirm, then execute
                    self._on_fp_update_skipped,    # info_error
                    _one_done,                     # finished
                    self._on_upgrade_progress,     # progress
                )

        except Exception as e:
            print("MintInstall: _on_pk_updates_ready error:", e)
            self.update_button.show()

        return False

    def _execute_apt_updates(self, pk_pkgs, done_callback):
        """Run a PackageKit APT update transaction for the given PkPackages."""
        from gi.repository import PackageKitGlib as pk
        from mintcommon.installer.installer import InstallerTask
        from mintcommon.installer.pkgInfo import AptPkgInfo

        # Create lightweight pkginfos to display in the "active tasks" view
        self._pending_apt_pkginfos = []
        for p in pk_pkgs:
            info = AptPkgInfo(pkg_hash="apt:" + p.get_name())
            info.name = p.get_name()
            info.display_name = p.get_name().capitalize()
            info.summary = ""
            self._pending_apt_pkginfos.append(info)

        apt_task = InstallerTask(
            pkginfo=None,
            installer=self.installer,
            client_info_ready_callback=None,
            client_info_error_callback=None,
            client_installer_finished_cb=done_callback,
            client_installer_progress_cb=self._on_upgrade_progress,
            installer_cleanup_cb=self.installer._task_finished,
            installer_error_cleanup_cb=self.installer._task_error,
        )
        apt_task.type = InstallerTask.UPDATE_TASK
        apt_task.to_update = list(pk_pkgs)
        apt_task.info_ready_status = InstallerTask.STATUS_OK
        pkg_ids = [p.get_id() for p in pk_pkgs]

        def _apt_execute():
            def _worker():
                try:
                    upgrade_client = pk.Task()
                    upgrade_client.update_packages_sync(pkg_ids, None, lambda *a: None, None)
                except Exception as e:
                    print("MintInstall: PackageKit update_packages error:", e)
                    apt_task.error_message = str(e)
                if apt_task.error_message:
                    apt_task.call_error_cleanup_callback()
                else:
                    apt_task.call_finished_cleanup_callback()
            threading.Thread(target=_worker, daemon=True).start()

        apt_task.confirm = lambda: True  # the confirmation is asked for before calling this
        apt_task.execute = _apt_execute
        apt_task.cancel = lambda: None
        self.installer.execute_task(apt_task)

    def _run_autoremove(self, finished_callback=None):
        """Remove automatically installed packages that are no longer needed.

        This is the PackageKit equivalent of 'apt autoremove -y': the list of
        unused packages is read from the APT cache (libapt decides what is
        garbage), and PackageKit performs the removal.  Failures are ignored.
        """
        def _worker():
            names = []
            try:
                import apt as _apt_mod
                cache = _apt_mod.Cache()
                names = [pkg.name for pkg in cache
                         if pkg.is_installed and pkg.is_auto_removable]
            except Exception as e:
                print("MintInstall: could not compute autoremove packages:", e)

            if names:
                try:
                    from gi.repository import PackageKitGlib as pk
                    client = pk.Task()
                    resolved = client.resolve_sync(pk.FilterEnum.INSTALLED, names,
                                                   None, lambda *a: None, None)
                    ids = [pkg.get_id() for pkg in resolved.get_package_array()
                           if pkg.get_name() in names]
                    if ids:
                        print("MintInstall: autoremove: %s" % ", ".join(sorted(names)))
                        client.remove_packages_sync(ids, True, True,
                                                    None, lambda *a: None, None)
                except Exception as e:
                    print("MintInstall: autoremove failed, continuing:", e)

            if finished_callback is not None:
                GLib.idle_add(finished_callback)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_fp_update_info_ready(self, task):
        """Flatpak updates are ready - confirm the changes, then execute."""
        task.parent_window = self.main_window

        if task.info_ready_status != task.STATUS_OK:
            self._on_fp_update_skipped(task)
            return

        # Same confirmation dialog the system packages use (installs, upgrades,
        # removals and disk usage).
        if not self.installer.confirm_task(task):
            self._on_fp_update_skipped(task)
            return

        self.installer.execute_task(task)

    def _on_fp_update_skipped(self, task):
        if task.error_message:
            dialogs.show_error(task.error_message, self.main_window)

        callback = getattr(self, "_fp_update_done_cb", None)
        self._fp_update_done_cb = None
        if callback is not None:
            callback(task)

    def _on_upgrade_progress(self, pkginfo, progress, estimating, status_text=None):
        if not estimating and progress > 0:
            GLib.idle_add(XApp.set_window_progress, self.main_window, int(progress))

    def _on_upgrade_all_done(self, task=None):
        self._pending_apt_pkginfos = []
        XApp.set_window_progress(self.main_window, 0)
        self.active_tasks_button.hide()
        self.active_tasks_spinner.stop()
        self.update_button.show()
        self._refresh_update_button_state()
        self.refresh_cache()
        return False

    def on_single_update_clicked(self, button):
        self.update_single_package(self.current_pkginfo)

    def update_single_package(self, pkginfo):
        """Update only the given package (APT through PackageKit, or Flatpak)."""
        if pkginfo is None:
            return

        if pkginfo.pkg_hash.startswith("f"):
            self._update_single_flatpak(pkginfo)
        else:
            self._update_single_apt(pkginfo)

    def _update_single_flatpak(self, pkginfo):
        self.active_tasks_button.show()
        self.active_tasks_spinner.start()

        def info_ready(task):
            task.parent_window = self.main_window

            if task.info_ready_status != task.STATUS_OK:
                self._on_single_update_failed(task)
                return

            # Same confirmation window as the system packages.
            if not self.installer.confirm_task(task):
                self._on_upgrade_all_done()
                return

            self.installer.execute_task(task)

        def info_error(task):
            self._on_single_update_failed(task)

        self.installer.select_flatpak_updates([pkginfo.refid],
                                              info_ready, info_error,
                                              self._on_upgrade_all_done,
                                              self.on_installer_progress)

    def _update_single_apt(self, pkginfo):
        name = pkginfo.name.split(":")[0]

        self.active_tasks_button.show()
        self.active_tasks_spinner.start()

        def _worker():
            pk_pkgs = []
            try:
                from gi.repository import PackageKitGlib as pk
                client = pk.Task()
                res = client.get_updates_sync(pk.FilterEnum.NONE, None, lambda *a: None, None)
                for pkg in res.get_package_sack().get_array():
                    if pkg.get_name() == name:
                        pk_pkgs.append(pkg)
            except Exception as e:
                print("MintInstall: PackageKit single update error:", e)

            GLib.idle_add(self._on_pk_single_ready, pkginfo, pk_pkgs)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_pk_single_ready(self, pkginfo, pk_pkgs):
        if not pk_pkgs:
            # The update is gone (already applied, or no longer offered).
            self.active_tasks_button.hide()
            self.active_tasks_spinner.stop()
            self.update_button.show()
            self._refresh_update_button_state()
            return False

        # Same confirmation window the system packages show for installs and upgrades.
        if not self.confirm_package_changes([p.get_name() for p in pk_pkgs]):
            self._on_upgrade_all_done()
            return False

        def _done(task=None):
            self._run_autoremove(self._on_upgrade_all_done)

        self._execute_apt_updates(pk_pkgs, _done)
        return False

    def _on_single_update_failed(self, task):
        if task.error_message:
            dialogs.show_error(task.error_message, self.main_window)
        self._on_upgrade_all_done()

    def on_appstream_changed(self, installer):
        for tile in self.picks_tiles:
            tile.repopulate_tile()
        if self.banner_tile is not None:
            self.banner_tile.repopulate_tile()

    def on_installer_ready(self):
        self.page_stack.set_visible_child_name(self.PAGE_LOADING)
        try:
            self.process_matching_packages()

            self.apply_aliases()

            self.review_cache = reviews.ReviewCache()
            self.review_cache.connect("reviews-updated", self.load_landing_apps)
            self.load_landing_apps()
            self.load_categories_on_landing()

            self.sync_installed_apps()
            self.update_conditional_widgets()

            GLib.idle_add(self.finished_loading_packages)

            # Can take some time, don't block for it (these are categorizing packages based on apt info, not our listings)
            GLib.idle_add(self.process_unmatched_packages)

            housekeeping.run()

            self.print_startup_time()
        except Exception as e:
            print("Loading error: %s" % e)
            traceback.print_tb(e.__traceback__)
            GLib.idle_add(self.refresh_cache)

    def print_startup_time(self):
        end_time = time.time()
        print('Mintinstall startup took %0.3f ms' % ((end_time - self.start_time) * 1000.0,))

    @print_timing
    def load_banner(self):
        """
        Load and configure the banner display with navigation controls.
        The banner shows featured applications in a slideshow format.
        """
        # Get the main banner container
        box = self.builder.get_object("box_banner")

        # Clear existing content
        for child in box.get_children():
            child.destroy()

        # Setup main container and stack
        overlay = Gtk.Overlay()
        box.pack_start(overlay, True, True, 0)

        self.banner_stack = Gtk.Stack()
        self.banner_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.banner_stack.set_transition_duration(BANNER_TIMER)
        overlay.add(self.banner_stack)

        # Create navigation buttons
        left_arrow = Gtk.Button()
        right_arrow = Gtk.Button()
        left_image = Gtk.Image.new_from_icon_name("xsi-go-previous-symbolic", Gtk.IconSize.SMALL_TOOLBAR)
        right_image = Gtk.Image.new_from_icon_name("xsi-go-next-symbolic", Gtk.IconSize.SMALL_TOOLBAR)

        # Setup button styling
        button_style_override = """
            button {
                background-color: transparent;
                border: none;
                padding: 0;
                margin: 0;
                min-height: 16px;
                min-width: 16px;
            }
            button:hover image {
                color: rgb(255, 255, 255);               
            }
            button image {
                color: rgba(255, 255, 255, 0.6);
            }
        """
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(str.encode(button_style_override))

        # Apply styling to navigation elements
        for widget in (left_arrow, right_arrow, left_image, right_image):
            context = widget.get_style_context()
            context.add_provider(css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        # Configure navigation buttons
        left_arrow.add(left_image)
        right_arrow.add(right_image)

        for button in (left_arrow, right_arrow):
            button.set_relief(Gtk.ReliefStyle.NONE)

        # Set navigation directions
        left_arrow.direction = -1
        right_arrow.direction = 1

        # Connect button signals
        left_arrow.connect("clicked", self.on_arrow_clicked, self.banner_stack)
        right_arrow.connect("clicked", self.on_arrow_clicked, self.banner_stack)

        # Create dots container (centered)
        self.banner_dots_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                       spacing=4,
                                       halign=Gtk.Align.CENTER,
                                       valign=Gtk.Align.CENTER)

        # Create a background frame for navigation
        dots_frame = Gtk.EventBox()
        dots_frame.set_name("dots-frame")
        
        # Add CSS styling for the frame
        frame_box_css = """
            #dots-frame {
                background-color: rgba(0, 0, 0, 0.25);
                border-radius: 12px;
            }
        """
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(frame_box_css.encode())
        dots_frame.get_style_context().add_provider(css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        
        # Create navigation container with arrows and dots
        nav_container = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                spacing=8,
                                halign=Gtk.Align.CENTER,
                                valign=Gtk.Align.CENTER)
        
        # Add padding around navigation
        nav_container.set_margin_start(7)
        nav_container.set_margin_end(7)
        nav_container.set_margin_top(4)
        nav_container.set_margin_bottom(4)
        
        # Pack everything together
        nav_container.pack_start(left_arrow, False, False, 0)
        nav_container.pack_start(self.banner_dots_box, True, False, 0)
        nav_container.pack_start(right_arrow, False, False, 0)
        
        dots_frame.add(nav_container)
        
        frame_container = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                  halign=Gtk.Align.END,
                                  valign=Gtk.Align.END,
                                  margin_bottom=7,
                                  margin_right=8)
        frame_container.pack_start(dots_frame, True, False, 0)
        overlay.add_overlay(frame_container)

        self.dots = []
        self.current_dot_index = 0

        # Load featured applications
        json_array = json.load(open("/usr/share/linuxmint/mintinstall/featured/featured.json", "r"))
        random.shuffle(json_array)

        selected_apps = set()
        num_selected = 0

        # Process featured applications
        for app_json in json_array:
            if num_selected >= 5:
                break

            name = app_json["name"]
            background = app_json["background"]
            color = app_json["text_color"]

            if name in selected_apps:
                continue

            # Handle Flatpak and regular applications
            if name.startswith("flatpak:"):
                name = name.replace("flatpak:", "")
                pkginfo = self.installer.find_pkginfo(name, installer.PKG_TYPE_FLATPAK)
                if pkginfo is None or not pkginfo.verified:
                    continue
                is_flatpak = True
            else:
                pkginfo = self.installer.find_pkginfo(name, installer.PKG_TYPE_APT)
                is_flatpak = False

            if pkginfo is None:
                continue

            # Add application to banner
            selected_apps.add(name)
            num_selected += 1

            flowbox = Gtk.FlowBox()
            flowbox.set_min_children_per_line(1)
            flowbox.set_max_children_per_line(1)
            flowbox.set_row_spacing(0)
            flowbox.set_column_spacing(0)
            flowbox.set_homogeneous(True)
            flowbox.connect("child-activated", self.on_flowbox_child_activated, self.PAGE_LANDING)

            tile = BannerTile(pkginfo, self.installer, name, background, color, is_flatpak, app_json, self.on_banner_clicked)
            flowbox.insert(tile, -1)
            flowbox.show_all()
            self.banner_stack.add_named(flowbox, str(len(self.banner_stack.get_children())))

            # Create dot indicator
            dot = Gtk.DrawingArea()
            dot.set_size_request(10, 10)
            dot.index = len(self.dots)  # Store index as a property
            dot.connect("draw", self.draw_dot)
            self.dots.append(dot)
            self.banner_dots_box.pack_start(dot, False, False, 0)

        # Display the banner
        box.show_all()
        self.update_dots(0)
        self.start_slideshow_timer()

    def draw_dot(self, widget, cr):
        """
        Draw a circular dot indicator with outline
        """
        # Get the dot's dimensions
        width = widget.get_allocated_width()
        height = widget.get_allocated_height()
        
        # Calculate center and radius
        center_x = width / 2
        center_y = height / 2
        radius = min(width, height) / 2 - 1
        
        # Draw outline circle
        cr.set_line_width(1)
        cr.arc(center_x, center_y, radius, 0, 2 * math.pi)
        cr.set_source_rgba(0, 0, 0, 0.25)  # Semi-transparent black outline
        cr.stroke_preserve()
        
        # Fill circle
        if widget.index == self.current_dot_index:
            cr.set_source_rgba(1, 1, 1, 1)  # Active dot: solid white
        else:
            cr.set_source_rgba(1, 1, 1, 0.40) # Inactive dot: semi-transparent white
        
        cr.fill()
        return False

    def update_dots(self, current_index):
        """
        Update the appearance of dots based on the current banner index
        """
        self.current_dot_index = current_index
        for dot in self.dots:
            dot.queue_draw()

    def on_arrow_clicked(self, button, banner_stack):
        current_index = int(self.banner_stack.get_visible_child_name())
        direction = getattr(button, "direction", 1)

        if direction == 1:  # next
            self.banner_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT)
            new_index = (current_index + 1) % len(self.banner_stack.get_children())
        else:  # previous
            self.banner_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_RIGHT)
            new_index = (current_index - 1) % len(self.banner_stack.get_children())
            
        self.banner_stack.set_visible_child_name(str(new_index))
        self.update_dots(new_index)
        self.start_slideshow_timer()

    def start_slideshow_timer(self):
        self.stop_slideshow_timer()
        self.banner_slideshow_timeout_id = GLib.timeout_add_seconds(5, self.on_slideshow_timeout)

    def stop_slideshow_timer(self):
        if self.banner_slideshow_timeout_id > 0:
            GLib.source_remove(self.banner_slideshow_timeout_id)
            self.banner_slideshow_timeout_id = 0

    def on_slideshow_timeout(self):
        current_index = int(self.banner_stack.get_visible_child_name())
        self.banner_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT)
        new_index = (current_index + 1) % len(self.banner_stack.get_children())
        self.banner_stack.set_visible_child_name(str(new_index))
        self.update_dots(new_index)
        return True

    def on_banner_clicked(self, button, pkginfo):
        self.show_package(pkginfo, self.PAGE_LANDING)

    @print_timing
    def load_top_rated(self):
        box = self.builder.get_object("box_top_rated")

        label = self.builder.get_object("label_top_rated")
        label.set_text(_("Top Rated"))
        label.show()

        if self.flowbox_top_rated is None:
            flowbox = Gtk.FlowBox()
            flowbox.set_min_children_per_line(3)
            flowbox.set_max_children_per_line(3)
            flowbox.set_row_spacing(0)
            flowbox.set_column_spacing(0)
            flowbox.set_homogeneous(False)
            flowbox.connect("child-activated", self.on_flowbox_child_activated, self.PAGE_LANDING)
            flowbox.connect("selected-children-changed", self.navigate_flowbox, self.builder.get_object("scrolledwindow_landing"))
            self.flowbox_top_rated = flowbox
            box.add(flowbox)

        for child in self.flowbox_top_rated:
            child.destroy()

        apps = []
        for info in (self.all_category.pkginfos + self.flatpak_category.pkginfos):
            if info.refid == "" or info.refid.startswith("app"):
                if not info.verified:
                    continue

                if info.name != self.banner_app_name and info.name not in self.featured_app_names:
                    if info.get_icon(imaging.FEATURED_ICON_SIZE) is not None:
                        apps.append(info)
        apps = self.sort_packages(apps, attrgetter("installed", "score_desc", "name"))
        apps = apps[0:30]
        random.shuffle(apps)

        size_group = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)
        for pkginfo in apps:
            if self.review_cache and pkginfo.verified:
                review_info = self.review_cache[pkginfo.name]
            else:
                review_info = None
            tile = PackageTile(pkginfo, self.installer, show_package_type=True, review_info=review_info,
                           upgradable=self._is_pkginfo_upgradable(pkginfo))
            size_group.add_widget(tile)
            self.flowbox_top_rated.insert(tile, -1)
            self.picks_tiles.append(tile)
        box.show_all()

    @print_timing
    def load_featured(self):
        box = self.builder.get_object("box_featured")

        label = self.builder.get_object("label_featured")
        label.set_text(_("Featured"))
        label.show()

        if self.flowbox_featured is None:
            flowbox = Gtk.FlowBox()
            flowbox.set_min_children_per_line(3)
            flowbox.set_max_children_per_line(3)
            flowbox.set_row_spacing(0)
            flowbox.set_column_spacing(0)
            flowbox.set_homogeneous(False)
            flowbox.connect("child-activated", self.on_flowbox_child_activated, self.PAGE_LANDING)
            flowbox.connect("selected-children-changed", self.navigate_flowbox, self.builder.get_object("scrolledwindow_landing"))
            self.flowbox_featured = flowbox
            box.add(flowbox)

        for child in self.flowbox_featured:
            child.destroy()

        apps = []
        featured_list = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/picks.list")
        for name in featured_list:
            if name.startswith("flatpak:"):
                name = name.replace("flatpak:", "")
                pkginfo = self.installer.find_pkginfo(name, installer.PKG_TYPE_FLATPAK)
                if pkginfo is None or not pkginfo.verified:
                    continue
            else:
                pkginfo = self.installer.find_pkginfo(name, installer.PKG_TYPE_APT)
            if pkginfo is None:
                continue
            if pkginfo.name == self.banner_app_name:
                continue
            if self.installer.pkginfo_is_installed(pkginfo):
                continue
            if pkginfo.refid == "" or pkginfo.refid.startswith("app"):
                apps.append(pkginfo)

        random.shuffle(apps)
        apps = apps[0:9]

        size_group = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)
        self.featured_app_names = []
        for pkginfo in apps:
            if self.review_cache and pkginfo.verified:
                review_info = self.review_cache[pkginfo.name]
            else:
                review_info = None
            tile = PackageTile(pkginfo, self.installer, show_package_type=True, review_info=review_info,
                           upgradable=self._is_pkginfo_upgradable(pkginfo))
            size_group.add_widget(tile)
            self.flowbox_featured.insert(tile, -1)
            self.picks_tiles.append(tile)
            self.featured_app_names.append(pkginfo.name)
        box.show_all()

    @print_timing
    def load_categories_on_landing(self):
        box = self.builder.get_object("box_categories")
        for child in box.get_children():
            child.destroy()

        label = self.builder.get_object("label_categories_landing")
        label.set_text(_("Categories"))
        label.show()

        flowbox = Gtk.FlowBox()
        flowbox.set_min_children_per_line(4)
        flowbox.set_max_children_per_line(4)
        flowbox.set_row_spacing(0)
        flowbox.set_column_spacing(0)
        flowbox.set_homogeneous(True)
        flowbox.connect("selected-children-changed", self.navigate_flowbox, self.builder.get_object("scrolledwindow_landing"))

        for name in sorted(self.root_categories.keys()):
            category = self.root_categories[name]
            button = CategoryButton(category)
            button.connect("clicked", self.category_button_clicked, category)
            flowbox.insert(button, -1)

        if self.installer.list_flatpak_remotes():
            # Add flatpaks
            button = CategoryButton(self.flatpak_category)
            button.connect("clicked", self.category_button_clicked, self.flatpak_category)
            flowbox.insert(button, -1)

        button = CategoryButton(self.all_category)
        button.connect("clicked", self.category_button_clicked, self.all_category)
        flowbox.insert(button, -1)

        box.pack_start(flowbox, True, True, 0)
        box.show_all()

    def load_landing_apps(self, rcache=None):
        self.picks_tiles = []
        self.load_banner()
        self.load_featured()
        self.load_top_rated()

    def open_software_sources(self, _widget):
        # Shows the APT repositories and their signing keys in this window.
        # Saving asks for authorization (pkexec) only when it is needed.
        if self.sources_page is None:
            # Deferred from create_window(): reading the sources and describing
            # the keyrings with gpg is slow and only needed on this page.
            self.sources_page = apt_sources.SourcesPage()
            self.sources_page.connect("saved", self.on_sources_saved)
            self.page_stack.add_named(self.sources_page, self.PAGE_SOURCES)
        else:
            self.sources_page.reload()
        self.previous_page = self.PAGE_LANDING
        self.search_tool_item.set_sensitive(False)
        self.back_button.set_sensitive(True)
        self.page_stack.set_visible_child_name(self.PAGE_SOURCES)

    def on_sources_saved(self, dialog):
        self.refresh_cache()

    def should_show_pkginfo(self, pkginfo):
        if pkginfo is None:
            return False
        if pkginfo.pkg_hash.startswith("apt"):
            return True

        if not self.settings.get_boolean(prefs.ALLOW_UNVERIFIED_FLATPAKS):
            return pkginfo.verified

        return pkginfo.refid.startswith("app/")

    def update_conditional_widgets(self):
        if not self.gui_ready:
            self.installed_menuitem.set_sensitive(False)
            self.subsearch_toggle.set_sensitive(False)
            return

        sensitive = len(self.installed_category.pkginfos) > 0 \
                    and not ((self.page_stack.get_visible_child_name() == self.PAGE_LIST) \
                    and (self.current_category == self.installed_category))

        self.installed_menuitem.set_sensitive(sensitive)

        sensitive = self.current_category is not None \
                    and self.page_stack.get_visible_child_name() == self.PAGE_LIST

        self.subsearch_toggle.set_sensitive(sensitive)

    def update_activity_widgets(self):
        num_tasks = self.installer.get_task_count()

        if num_tasks > 0:
            self.active_tasks_button.show()

            text = gettext.ngettext("%d task running", "%d tasks running", num_tasks) % num_tasks

            self.active_tasks_button.set_tooltip_text(text)
            self.active_tasks_spinner.start()
        else:
            self.active_tasks_button.hide()
            self.active_tasks_spinner.stop()

        if self.current_category == self.active_tasks_category \
                                    and self.page_stack.get_visible_child_name() == self.PAGE_LIST:
            self.show_active_tasks() # Refresh the view, remove old items

    def update_state(self, pkginfo):
        self.update_activity_widgets()

        installed_packages = self.settings.get_strv(prefs.INSTALLED_APPS)
        if self.installer.pkginfo_is_installed(pkginfo):
            if pkginfo.pkg_hash not in installed_packages:
                installed_packages.append(pkginfo.pkg_hash)
                if pkginfo not in self.installed_category.pkginfos:
                    self.installed_category.pkginfos.append(pkginfo)
        else:
            if pkginfo.pkg_hash in installed_packages:
                installed_packages.remove(pkginfo.pkg_hash)
                for iter_package in self.installed_category.pkginfos:
                    if iter_package.pkg_hash == pkginfo.pkg_hash:
                        self.installed_category.pkginfos.remove(iter_package)

        self.settings.set_strv(prefs.INSTALLED_APPS, installed_packages)
        self._installed_pkg_hashes = list(installed_packages)

        if self.current_pkginfo is not None and self.current_pkginfo.pkg_hash == pkginfo.pkg_hash:
            # flatpaks added by flatpakref files auto-remove their remotes when uninstalled
            # (this doesn't apply to flatpakref files that were refs off of an already-existing
            # remote - like those installed from flathub, for instance.)  So, we can't assume
            # the remote still exists, and will get errors if we try to display the app.  We will
            # just remove it from the cache at this point.
            can_show = False
            if pkginfo.pkg_hash.startswith("f"):
                remotes = self.installer.list_flatpak_remotes()
                for remote in remotes:
                    if remote.name == pkginfo.remote:
                        can_show = True
                        break
            else:
                can_show = True

            if can_show:
                if self.recursion_buster:
                    self.recursion_buster = False
                    return
                self.show_package(self.current_pkginfo, self.previous_page)
            else:
                del self.installer.cache[pkginfo.pkg_hash]
                self.previous_page = self.PAGE_LANDING
                self.go_back_action()

        for tile in (self.picks_tiles + self.category_tiles):
            if tile.pkginfo == pkginfo:
                tile.refresh_state()

        for tile in self.flowbox_applications.get_children():
            try:
                tile.refresh_state()
            except Exception as e:
                print(e)

    def modernize_installed_list(self, packages):
        """
        We can not rely on just the name of a package to guarantee uniqueness.
        This works for apt but not flatpaks.  So we need to upgrade existing keys
        to store pkg_hashes rather than simple names.
        """
        return_list = []

        for item in packages:
            if item.startswith(("apt:", "fp:")):
                # pkg_hashes start with apt: or fp:, if items have this, they're up-to-date.
                return_list.append(item)
                continue

            # Must be an old one, look it up by name (possibly incorrectly if there have been multiple remotes added)
            pkginfo = self.installer.find_pkginfo(item)

            if pkginfo:
                return_list.append(pkginfo.pkg_hash)
                continue

        return return_list

    def sync_installed_apps(self):
        """ garbage collect any stale packages in this list (uninstalled somewhere else) """

        installed_packages = self.installer.cache.get_manually_installed_packages()
        if not installed_packages:
            installed_packages = self.settings.get_strv(prefs.INSTALLED_APPS)
            installed_packages = self.modernize_installed_list(installed_packages)

        new_installed_packages = []
        for pkg_hash in installed_packages:
            try:
                pkginfo = self.installer.cache[pkg_hash]
            except KeyError:
                continue

            if self.installer.pkginfo_is_installed(pkginfo):
                if pkginfo not in self.installed_category.pkginfos:
                    self.installed_category.pkginfos.append(pkginfo)
                new_installed_packages.append(pkg_hash)
            else:
                try:
                    self.installed_category.pkginfos.remove(pkginfo)
                except ValueError:
                    pass

        self.settings.set_strv(prefs.INSTALLED_APPS, new_installed_packages)
        self._installed_pkg_hashes = new_installed_packages

    def show_installed_apps(self, menuitem):
        self.show_category(self.installed_category)

    def add_screenshots(self, pkginfo):
        ss_dir = Path(imaging.SCREENSHOT_DIR)

        n = 0
        for ss_path in ss_dir.glob("%s_*.png" % pkginfo.name):
            n += 1
            self.add_screenshot(pkginfo, ss_path, n)

        if n == 0:
            downloadScreenshots = imaging.ScreenshotDownloader(self, pkginfo, self.main_window.get_scale_factor())

    def add_screenshot(self, pkginfo, ss_path, n):
        if pkginfo != self.current_pkginfo:
            return

        try:
            self.screenshot_stack.get_child_by_name("spinner").destroy()
        except AttributeError:
            pass

        if ss_path is None:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, valign=Gtk.Align.CENTER)
            image = Gtk.Image(icon_name="xsi-face-uncertain-symbolic", icon_size=Gtk.IconSize.DIALOG)
            label = Gtk.Label(label=_("No screenshots available"))
            box.pack_start(image, False, False, 0)
            box.pack_start(label, False, False, 0)
            box.show_all()
            self.screenshot_stack.add_named(box, "no-screenshots")
            self.screenshot_stack.get_window().set_cursor(None)
            return

        screenshot = imaging.get_image_for_screenshot(str(ss_path), imaging.SCREENSHOT_WIDTH, imaging.SCREENSHOT_HEIGHT)

        self.screenshot_stack.add_named(screenshot, str(n))
        self.screenshot_stack.last = n
        self.screenshot_stack.show_all()
        self.ss_swipe_handler.set_propagation_phase(Gtk.PropagationPhase.BUBBLE)
        self.screenshot_controls_vgroup.set_visible(n > 1)
        self.screenshot_stack.get_window().set_cursor(self.select_cursor)

    def on_screenshot_shown(self, stack, pspec):
        screenshot = stack.get_visible_child()

    def navigate_screenshot(self, button, direction):
        new = current = int(self.screenshot_stack.get_visible_child_name())

        if direction == Gtk.DirectionType.TAB_BACKWARD:
            new = current - 1 if current > 1 else self.screenshot_stack.last
            trans = Gtk.StackTransitionType.SLIDE_RIGHT
        elif direction == Gtk.DirectionType.TAB_FORWARD:
            new = current + 1 if current < self.screenshot_stack.last else 1
            trans = Gtk.StackTransitionType.SLIDE_LEFT

        self.screenshot_stack.set_visible_child_full(str(new), trans)

    def screenshot_stack_swiped(self, handler, vx, vy, stack):
        if vx == 0 and vy == 0:
            if self.screenshot_window is None or not self.screenshot_window.get_visible():
                self.enlarge_screenshot(stack.get_visible_child())
            return

        if vx < 0:
            self.navigate_screenshot(None, Gtk.DirectionType.TAB_FORWARD)
        elif vx > 0:
            self.navigate_screenshot(None, Gtk.DirectionType.TAB_BACKWARD)

    def on_window_key_press(self, stack, event, data=None):
        if self.page_stack.get_visible_child_name() != self.PAGE_DETAILS:
            return Gdk.EVENT_PROPAGATE
        if not self.screenshot_controls_vgroup.get_visible():
            return Gdk.EVENT_PROPAGATE

        got_keyval, keyval = event.get_keyval()
        direction = None

        if got_keyval:
            if keyval in (Gdk.KEY_Left, Gdk.KEY_KP_Left):
                direction = Gtk.DirectionType.TAB_BACKWARD
            elif keyval in (Gdk.KEY_Right, Gdk.KEY_KP_Right):
                direction = Gtk.DirectionType.TAB_FORWARD

        if direction is not None:
            self.navigate_screenshot(None, direction)
            return Gdk.EVENT_STOP

        return Gdk.EVENT_PROPAGATE

    def get_screenshot_source_from_metadata(self, screenshot):
        file = Gio.File.new_for_path(screenshot.path)

        try:
            info = file.query_info("metadata::mintinstall-screenshot-source-url", Gio.FileQueryInfoFlags.NONE, None)
            url = info.get_attribute_string("metadata::mintinstall-screenshot-source-url")
            if url is not None:
                return url
        except GLib.Error as e:
            print("Could not retrieve source metadata for screenshot (%s): %s" % (ss_path, e.message))

        return None

    def enlarge_screenshot(self, screenshot):
        source_url = self.get_screenshot_source_from_metadata(screenshot)
        if source_url is not None:
            image_location = source_url
        else:
            image_location = screenshot.path

        if self.screenshot_window is not None:
            if self.screenshot_window.has_image(source_url):
                self.screenshot_window.show_all()
                self.screenshot_window.present()
                return
        else:
            multiple_images = len(self.installer.get_screenshots(self.current_pkginfo)) > 1 or \
                                  self.screenshot_stack.last > 1
            self.screenshot_window = ScreenshotWindow(self.main_window, multiple_images)
            self.screenshot_window.connect("next-image", self.next_enlarged_screenshot_requested)
            self.screenshot_window.connect("destroy", self.enlarged_screenshot_window_destroyed)

        monitor = Gdk.Display.get_default().get_monitor_at_window(self.main_window.get_window())

        work_area = monitor.get_workarea()
        enlarged = imaging.get_image_for_screenshot(image_location, work_area.width * .8, work_area.height * .8)
        enlarged.connect("image-loaded", self.enlarged_image_ready)
        enlarged.connect("image-failed", self.enlarged_image_failed)
        return Gdk.EVENT_STOP

    def enlarged_image_ready(self, image):
        self.screenshot_window.add_image(image, image.path)

    def enlarged_image_failed(self, image):
        # AsyncImage will be trying to load a fallback image next, make sure we don't get signaled for it.
        image.disconnect_by_func(self.enlarged_image_ready)
        image.destroy()

        self.screenshot_window.set_busy(False)

        # If a screenshot failed and it's the first one, there's an empty, invisible screenshot window
        # in front of the main window, so destroy it.
        if not self.screenshot_window.any_images():
            self.screenshot_window.destroy()

    def enlarged_screenshot_window_destroyed(self, window):
        self.screenshot_window = None

    def next_enlarged_screenshot_requested(self, window, direction):
        if len(self.screenshot_stack.get_children()) < 2:
            self.screenshot_window.destroy()
            return False

        self.navigate_screenshot(None, direction)
        screenshot = self.screenshot_stack.get_visible_child()
        source_url = self.get_screenshot_source_from_metadata(screenshot)

        if source_url is not None:
            image_location = source_url
        else:
            image_location = screenshot.path

        if self.screenshot_window.has_image(image_location):
            self.screenshot_window.show_image(image_location)
            return False

        self.enlarge_screenshot(screenshot)
        return True

    def destroy_screenshot_window(self):
        if self.screenshot_window is not None:
            self.screenshot_window.destroy()
            self.screenshot_window = None

    def category_button_clicked(self, button, category):
        self.show_category(category)

    def on_menu_button_clicked(self, button, menu):
        menu.popup_at_pointer(None)

    def on_subsearch_toggled(self, button):
        self.settings.set_boolean(prefs.SEARCH_IN_CATEGORY, button.get_active())

        if button.get_active():
            return
        else:
            self.on_search_changed(self.searchentry)

    def on_search_entry_activated(self, searchentry):
        terms = searchentry.get_text()

        if terms != "":
            self.show_search_results(terms)

    def on_entry_text_changed(self, entry):
        if self.search_changed_timer > 0:
            GLib.source_remove(self.search_changed_timer)
            self.search_changed_timer = 0

        self.search_changed_timer = GLib.timeout_add(175, self.on_search_changed, entry)

    def on_search_changed(self, searchentry):
        terms = searchentry.get_text()

        if self.subsearch_toggle.get_active() and self.current_category is not None and terms == "":
            self.show_category(self.current_category)
        elif terms != "" and len(terms) >= 3:
            self.show_search_results(terms)

        self.search_changed_timer = 0
        return False

    def set_search_filter(self, checkmenuitem, key):
        self.settings.set_boolean(key, checkmenuitem.get_active())

        terms = self.searchentry.get_text()

        if (self.searchentry.get_text() != ""):
            self.show_search_results(terms)

    def set_package_type_preference(self, radiomenuitem, value):
        if radiomenuitem.get_active():
            self.settings.set_string(prefs.PACKAGE_TYPE_PREFERENCE, value)

            terms = self.searchentry.get_text()
            if terms != "":
                self.show_search_results(terms)

    def on_package_help_clicked(self, button):
        self.package_help_popover.popup()

    def open_about(self, widget):
        dlg = Gtk.AboutDialog()
        dlg.set_transient_for(self.main_window)
        dlg.set_title(_("About"))
        dlg.set_program_name("mintinstall")
        dlg.set_comments(_("Software Manager"))
        try:
            with open('/usr/share/common-licenses/GPL', 'r') as h:
                gpl = h.read()
            dlg.set_license(gpl)
        except Exception as e:
            print(e)

        dlg.set_version("__DEB_VERSION__")
        dlg.set_icon_name("mintinstall")
        dlg.set_logo_icon_name("mintinstall")

        def close(w, res):
            if res == Gtk.ResponseType.CANCEL or res == Gtk.ResponseType.DELETE_EVENT:
                w.hide()
        dlg.connect("response", close)
        dlg.show()

    def export_listing(self, flatpak_only=False):
        if not flatpak_only:
            for filename in os.listdir("/var/lib/apt/lists/"):
                if "i18n" in filename and not filename.endswith("-en"):
                    print("Your APT cache is localized. Please remove all translations first.")
                    print("sudo rm -rf /var/lib/apt/lists/*Translation%s" % filename[-3:])
                    return 1
        if (os.getenv('LANGUAGE') != "C"):
            print("Please prefix this command with LANGUAGE=C, to prevent content from being translated in the host's locale.")
            return 1
        self.locale = "C"

        self.installer = installer.Installer()

        from mintcommon.installer import cache

        self.installer.cache = cache.PkgCache(None, None, self.installer.have_flatpak)
        self.installer.cache._generate_cache_thread()

        self.installer.backend_table = {}

        self.installer.initialize_appstream()
        self.installer.generate_uncached_pkginfos()

        self.add_categories()
        self.process_matching_packages()
        self.process_unmatched_packages()

        if flatpak_only:
            pkginfos = self.installer.cache.get_subset_of_type("f")
        else:
            pkginfos = self.installer.cache

        for pkg_hash in pkginfos.keys():
            pkginfo = self.installer.cache[pkg_hash]

            description = self.installer.get_description(pkginfo)
            description = description.replace("\r\n", "<br>")
            description = description.replace("\n", "<br>")

            summary = pkginfo.get_summary()
            url = ""
            try:
                url = self.installer.get_homepage_url(pkginfo)
            except:
                pass

            categories = []
            for category in pkginfo.categories:
                categories.append(category.name)

            try:
                output = "#~#".join([pkginfo.name, url, summary, description, ":::".join(categories)])
            except Exception as e:
                print (e)
                print(pkginfo.name, url, summary, description)
                return 1
            print(output)

        return 0

    def close_application(self, window, event=None):
        if self.installer.is_busy():
            dialog = Gtk.MessageDialog(self.main_window,
                                       Gtk.DialogFlags.MODAL,
                                       Gtk.MessageType.WARNING,
                                       Gtk.ButtonsType.YES_NO,
                                       _("There are currently active operations.\nAre you sure you want to quit?"))
            res = dialog.run()
            dialog.destroy()
            if res == Gtk.ResponseType.NO:
                return True

        if self.deb_files_temp_dir is not None:
            shutil.rmtree(self.deb_files_temp_dir, ignore_errors=True)

        # kill -9 won't kill mp subprocesses, we have to do them ourselves.
        housekeeping.kill()
        if self.review_cache:
            self.review_cache.kill()

        # Not happy with Python when it comes to closing threads, so here's a radical method to get what we want.
        os.system("kill -9 %s &" % os.getpid())

    def on_action_button_clicked(self, button, task):
        if task.info_ready_status == task.STATUS_UNKNOWN:
            self.show_package(self.current_pkginfo, self.previous_page)
            return

        if not self.installer.confirm_task(task):
            return

        self.on_installer_progress(task.pkginfo, 0, True)

        self.installer.execute_task(task)

        self.update_activity_widgets()

    def on_launch_button_clicked(self, button, task):
        if task.exec_string is not None:
            exec_array = task.exec_string.split()
            for element in exec_array:
                if element.startswith('%'):
                    exec_array.remove(element)
            if "sh" in exec_array:
                print("Launching app with OS: " % " ".join(exec_array))
                os.system("%s &" % " ".join(exec_array))
            else:
                print("Launching app with Popen: %s" % " ".join(exec_array))
                subprocess.Popen(exec_array)

    def file_to_array(self, filename):
        array = []

        with open(filename) as f:
            for line in f:
                line = line.replace("\n", "").replace("\r", "").strip()
                if line != "":
                    array.append(line)

        return array

    @print_timing
    def add_categories(self):
        self.categories = []
        self.sections = {}
        self.root_categories = {}

        self.installed_category = Category(_("Installed Applications"), None, self.categories)
        self.installed_category.matchingPackages = self.settings.get_strv(prefs.INSTALLED_APPS)

        self.active_tasks_category = Category(_("Currently working on the following packages"), None, None)

        self.flatpak_category = Category("Flatpak", None, self.categories, "mintinstall-package-flatpak-symbolic")

        # INTERNET
        category = Category(_("Internet"), None, self.categories, "mintinstall-web-symbolic")

        subcat = Category(_("Web"), category, self.categories, "mintinstall-web-symbolic")
        self.sections["web"] = subcat
        self.sections["net"] = subcat
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/internet-web.list")

        subcat = Category(_("Email"), category, self.categories, "mintinstall-email-symbolic")
        self.sections["mail"] = subcat
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/internet-email.list")

        subcat = Category(_("Chat"), category, self.categories, "mintinstall-chat-symbolic")
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/internet-chat.list")

        subcat = Category(_("File sharing"), category, self.categories, "mintinstall-share-symbolic")
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/internet-filesharing.list")

        self.root_categories[category.name] = category

        # SOUND AND VIDEO
        category = Category(_("Sound and video"), None, self.categories, "mintinstall-music-symbolic")
        category.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/sound-video.list")
        subcat = Category(_("Sound"), category, self.categories, "mintinstall-music-symbolic")
        self.sections["sound"] = subcat
        subcat = Category(_("Video"), category, self.categories, "mintinstall-video-symbolic")
        self.sections["video"] = subcat
        self.root_categories[category.name] = category

        # GRAPHICS
        category = Category(_("Graphics"), None, self.categories, "mintinstall-drawing-symbolic")
        self.sections["graphics"] = category
        category.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/graphics.list")

        subcat = Category(_("3D"), category, self.categories, "mintinstall-3d-symbolic")
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/graphics-3d.list")
        subcat = Category(_("Drawing"), category, self.categories, "mintinstall-drawing-symbolic")
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/graphics-drawing.list")
        subcat = Category(_("Photography"), category, self.categories, "mintinstall-photo-symbolic")
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/graphics-photography.list")
        subcat = Category(_("Publishing"), category, self.categories, "mintinstall-publishing-symbolic")
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/graphics-publishing.list")
        subcat = Category(_("Scanning"), category, self.categories, "mintinstall-scanning-symbolic")
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/graphics-scanning.list")
        subcat = Category(_("Viewers"), category, self.categories, "mintinstall-viewers-symbolic")
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/graphics-viewers.list")
        self.root_categories[category.name] = category

        # OFFICE
        category = Category(_("Office"), None, self.categories, "mintinstall-office-symbolic")
        self.sections["office"] = category
        self.sections["editors"] = category
        self.root_categories[category.name] = category

        # GAMES
        category = Category(_("Games"), None, self.categories, "mintinstall-games-symbolic")
        self.sections["games"] = category
        category.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/games.list")

        subcat = Category(_("Board games"), category, self.categories, "mintinstall-board-symbolic")
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/games-board.list")
        subcat = Category(_("First-person"), category, self.categories, "mintinstall-fps-symbolic")
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/games-fps.list")
        subcat = Category(_("Real-time strategy"), category, self.categories, "mintinstall-rts-symbolic")
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/games-rts.list")
        subcat = Category(_("Turn-based strategy"), category, self.categories, "mintinstall-tbs-symbolic")
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/games-tbs.list")
        subcat = Category(_("Emulators"), category, self.categories, "mintinstall-emulator-symbolic")
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/games-emulators.list")
        subcat = Category(_("Simulation and racing"), category, self.categories, "mintinstall-sim-symbolic")
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/games-simulations.list")
        self.root_categories[category.name] = category

        # ACCESSORIES
        category = Category(_("Accessories"), None, self.categories, "mintinstall-accessories-symbolic")
        self.sections["accessories"] = category
        self.sections["utils"] = category
        self.root_categories[category.name] = category

        # SYSTEM TOOLS
        category = Category(_("System tools"), None, self.categories, "mintinstall-system-symbolic")
        self.sections["system"] = category
        self.sections["admin"] = category
        category.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/system-tools.list")
        self.root_categories[category.name] = category

        # FONTS
        category = Category(_("Fonts"), None, self.categories, "mintinstall-fonts-symbolic")
        self.sections["fonts"] = category
        category.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/fonts.list")
        self.root_categories[category.name] = category

        # EDUCATION
        category = Category(_("Science and Education"), None, self.categories, "mintinstall-science-symbolic")
        subcat = Category(_("Science"), category, self.categories, "mintinstall-science-symbolic")
        self.sections["science"] = subcat
        subcat = Category(_("Maths"), category, self.categories, "mintinstall-maths-symbolic")
        self.sections["math"] = subcat
        subcat = Category(_("Education"), category, self.categories, "mintinstall-education-symbolic")
        self.sections["education"] = subcat
        subcat = Category(_("Electronics"), category, self.categories, "mintinstall-electronic-symbolic")
        self.sections["electronics"] = subcat
        category.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/education.list")
        self.root_categories[category.name] = category

        # PROGRAMMING
        category = Category(_("Programming"), None, self.categories, "mintinstall-programming-symbolic")
        self.sections["devel"] = category
        subcat = Category(_("Java"), category, self.categories, "mintinstall-java-symbolic")
        self.sections["java"] = subcat
        subcat = Category(_("PHP"), category, self.categories, "mintinstall-php-symbolic")
        self.sections["php"] = subcat
        subcat = Category(_("Python"), category, self.categories, "mintinstall-python-symbolic")
        self.sections["python"] = subcat
        subcat = Category(_("Essentials"), category, self.categories, "xsi-favorites-app-symbolic")
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/development-essentials.list")
        self.root_categories[category.name] = category

        # ALL
        self.all_category = Category(_("All Applications"), None, self.categories, "mintinstall-all-symbolic")
        for cat in self.categories:
            self.all_category.matchingPackages.extend(cat.matchingPackages)
        sorted(self.all_category.matchingPackages)

    def add_pkginfo_to_category(self, pkginfo, category):
            try:
                if category not in pkginfo.categories:
                    pkginfo.categories.append(category)
                    category.pkginfos.append(pkginfo)

                    if category.parent:
                        self.add_pkginfo_to_category(pkginfo, category.parent)
            except AttributeError:
                pass

    def finished_loading_packages(self):
        self.finish_loading_visual()
        self.start_slideshow_timer()

        self.gui_ready = True
        self.update_conditional_widgets()

        # The update check runs on its own thread and only updates the header
        # button - start it once the landing page is on screen so it can't
        # delay any of the page content.
        GLib.timeout_add(500, self._start_update_check)

        if self.install_on_startup_file is not None:
            self.handle_command_line_install(self.install_on_startup_file)

        return False

    def get_installed_package_hashes(self):
        if self.installer.have_flatpak:
            installed_fp_refs = installer._flatpak.get_fp_sys().list_installed_refs(None)
            fp_hashes = [installer._flatpak.make_pkg_hash(ref) for ref in installed_fp_refs]
        else:
            fp_hashes = []

        apt_cache = installer._apt.get_apt_cache()
        apt_hashes = [installer._apt.make_pkg_hash(pkg) for pkg in apt_cache if pkg.installed]

        return apt_hashes + fp_hashes

    @print_timing
    def process_matching_packages(self):
        # Process matching packages
        for category in self.categories:
            for package_name in category.matchingPackages:
                if package_name.startswith("fp"):
                    continue
                pkginfo = self.installer.find_pkginfo(package_name, installer.PKG_TYPE_APT)

                self.add_pkginfo_to_category(pkginfo, category)

        for package_name in self.installed_category.matchingPackages:
            if not package_name.startswith("fp"):
                continue
            pkginfo = self.installer.find_pkginfo(package_name, installer.PKG_TYPE_FLATPAK)
            self.add_pkginfo_to_category(pkginfo,
                                         self.installed_category)

        self.flatpak_remote_categories = {}
        self.flatpak_category.subcategories = []

        for key in self.installer.cache.get_subset_of_type("f"):
            remote_name = self.installer.cache[key].remote
            remote_info = self.installer.cache.flatpak_remote_infos[remote_name]

            self.add_pkginfo_to_category(self.installer.cache[key],
                                         self.flatpak_category)

            # Remotes marked noenumerate don't get a category, their apps show only in
            # the installed category and the main flatpak category.  They are auto-removed
            # then the app is uninstalled generally (usually they're -origin remotes, only added
            # when a .flatpakref file is installed.)  However, their addition/removal, purposely,
            # will not trigger a rebuild of the cache, so we don't want to be caught showing an
            # empty category as a reuslt.
            if remote_info.noenumerate:
                continue

            if remote_name not in self.flatpak_remote_categories.keys():
                self.flatpak_remote_categories[remote_name] = Category(remote_info.title, self.flatpak_category, None)

            self.add_pkginfo_to_category(self.installer.cache[key],
                                         self.flatpak_remote_categories[remote_name])

    @print_timing
    def process_unmatched_packages(self):
        cache_sections = self.installer.cache.sections

        for section in self.sections.keys():
            if section in cache_sections.keys():
                for pkg_hash in cache_sections[section]:
                    self.add_pkginfo_to_category(self.installer.cache[pkg_hash],
                                                 self.sections[section])

    def apply_aliases(self):
        for pkg_name in ALIASES.keys():
            pkginfo = self.installer.cache.find_pkginfo(pkg_name, installer.PKG_TYPE_APT) # aliases currently only apply to apt

            if pkginfo:
                # print("Applying aliases: ", ALIASES[pkg_name], self.installer.get_display_name(pkginfo))
                pkginfo.display_name = ALIASES[pkg_name]

    def finish_loading_visual(self):
        if self.page_stack.get_visible_child_name() != self.PAGE_LANDING:
            self.page_stack.set_visible_child_name(self.PAGE_LANDING)

    #Copied from the Cinnamon Project cinnamon-settings.py
    #Goes back when the Backspace or Home key on the keyboard is typed
    def on_keypress(self, widget, event):
        if self.main_window.get_focus() != self.searchentry and (event.keyval in [Gdk.KEY_BackSpace, Gdk.KEY_Home]):
            self.go_back_action()
            return True
        return False

    #Copied from the Cinnamon Project cinnamon-settings.py
    #Goes back when the back button on the mouse is clicked
    def on_buttonpress(self, widget, event):
        if event.button == MOUSE_BACK_BUTTON:
            self.go_back_action()
            return True
        return False

    def reset_scroll_view(self, scrolledwindow):
        adjustment = scrolledwindow.get_vadjustment()
        adjustment.set_value(adjustment.get_lower())

    def on_active_tasks_button_clicked(self, button):
        self.show_active_tasks()

    def show_active_tasks(self):
        self.current_pkginfo = None

        pkginfos = [p for p in self.installer.get_active_pkginfos() if p is not None]

        # Add the pkginfos of the APT updates (pkginfo=None in the task, kept separately)
        pending_apt = getattr(self, "_pending_apt_pkginfos", [])
        for info in pending_apt:
            if info not in pkginfos:
                pkginfos.append(info)

        self.active_tasks_category.pkginfos = pkginfos

        self.show_category(self.active_tasks_category)

    def on_back_button_clicked(self, button):
        self.go_back_action()

    def go_back_action(self):
        XApp.set_window_progress(self.main_window, 0)
        self.stop_progress_pulse()

        # If we're still loading details (and simulating), there's no task yet,
        # but we can cancel it via cancellable the installer gave us initially.
        if self.task_cancellable is not None:
            self.task_cancellable.cancel()
            self.task_cancellable = None

        # If we have a task, we're viewing a package and it's been 'loaded' fully.
        # Cancel it directly.
        elif self.current_task:
            if not self.installer.task_running(self.current_task):
                self.installer.cancel_task(self.current_task)
            self.current_task = None

        if self.page_stack.get_visible_child_name() in (self.PAGE_PREFS, self.PAGE_SOURCES):
            self.search_tool_item.set_sensitive(True)

        self.current_pkginfo = None
        self.page_stack.set_visible_child_name(self.previous_page)
        if self.previous_page == self.PAGE_LANDING:
            self.back_button.set_sensitive(False)
            self.searchentry.grab_focus()
            self.searchentry.set_text("")
            self.current_category = None
            if self.one_package_idle_timer > 0:
                GLib.source_remove(self.one_package_idle_timer)
                self.one_package_idle_timer = 0
            try:
                tile = self.flowbox_top_rated.get_selected_children()[0]
                tile.grab_focus()
            except IndexError:
                pass

            self.start_slideshow_timer()

        if self.previous_page == self.PAGE_LIST:
            self.previous_page = self.PAGE_LANDING
            if self.current_category == self.installed_category:
                # special case, when going back to the installed-category, refresh it in case we removed something
                self.show_category(self.installed_category)
            elif self.current_category == self.active_tasks_category:
                self.show_active_tasks()
            else:
                try:
                    tile = self.flowbox_applications.get_selected_children()[0]
                    tile.grab_focus()
                except IndexError:
                    pass

        if self.screenshot_stack.get_realized():
            self.screenshot_stack.get_window().set_cursor(None)
        self.update_conditional_widgets()

    def show_category(self, category):
        self.current_pkginfo = None

        cat_box = self.builder.get_object("box_cat_label")
        label = self.builder.get_object("label_cat_name")

        self.current_category = category

        self.page_stack.set_visible_child_name(self.PAGE_LIST)
        self.previous_page = self.PAGE_LANDING
        self.back_button.set_sensitive(True)

        label.set_text(self.current_category.name)

        if category.parent:
            self.show_subcategories(category.parent)
        else:
            self.show_subcategories(category)

        label.show()
        cat_box.show()

        self.show_packages(category.pkginfos, from_search=False)

        self.update_conditional_widgets()

    def show_subcategories(self, category):
        # Load subcategories
        for child in self.subcat_flowbox.get_children():
            child.destroy()

        if category == self.flatpak_category or len(category.subcategories) == 0:
            self.subcat_flowbox.hide()
            return

        child = SubcategoryFlowboxChild(category, is_all=True, active=self.current_category == category)
        self.subcat_flowbox.add(child)

        for cat in category.subcategories:
            if len(cat.pkginfos) > 0:
                child = SubcategoryFlowboxChild(cat, is_all=False, active=self.current_category == cat)
                self.subcat_flowbox.add(child)

        subcat_box = self.builder.get_object("box_subcategories")
        subcat_box.show()
        self.subcat_flowbox.show_all()

    def on_subcategory_selected(self, flowbox, child, data=None):
        self.show_category(child.category)

    def get_application_icon_string(self, pkginfo, size):
        string = pkginfo.get_icon(size, self.installer.get_appstream_pkg_for_pkginfo(pkginfo))

        if not string:
            string = imaging.FALLBACK_PACKAGE_ICON_PATH

        return string

    def get_application_icon(self, pkginfo, size):
        icon_string = self.get_application_icon_string(pkginfo, size)

        return imaging.get_icon(icon_string, size)

    @print_timing
    def show_search_results(self, terms):
        if not self.gui_ready:
            return False

        label = self.builder.get_object("box_cat_label")
        label.hide()

        XApp.set_window_progress(self.main_window, 0)
        self.stop_progress_pulse()
        self.current_pkginfo = None

        for child in self.flowbox_applications.get_children():
            self.flowbox_applications.remove(child)

        if self.subsearch_toggle.get_active()  \
            and self.current_category is not None \
                and self.page_stack.get_visible_child_name() == self.PAGE_LIST:
            listing = self.current_category.pkginfos
        else:
            listing = self.installer.cache.values()
            self.current_category = None

        subcat_box = self.builder.get_object("box_subcategories")
        subcat_box.hide()
        self.back_button.set_sensitive(True)
        self.previous_page = self.PAGE_LANDING
        if self.page_stack.get_visible_child_name() != self.PAGE_SEARCHING:
            self.page_stack.set_visible_child_name(self.PAGE_SEARCHING)

        termsUpper = terms.upper()
        termsSplit = re.split(r'\W+', termsUpper)

        searched_packages = []

        if self.search_idle_timer > 0:
            GLib.source_remove(self.search_idle_timer)
            self.search_idle_timer = 0

        search_in_summary = self.settings.get_boolean(prefs.SEARCH_IN_SUMMARY)
        search_in_description = self.settings.get_boolean(prefs.SEARCH_IN_DESCRIPTION)

        package_type_preference = self.settings.get_string(prefs.PACKAGE_TYPE_PREFERENCE)
        hidden_packages = set()

        def idle_search_one_package(pkginfos):
            try:
                pkginfo = pkginfos.pop(0)
            except IndexError:
                self.search_idle_timer = 0
                return False

            flatpak = pkginfo.pkg_hash.startswith("f")
            is_match = False

            while True:
                if not self.should_show_pkginfo(pkginfo):
                    break

                if all(piece in pkginfo.name.upper() for piece in termsSplit):
                    is_match = True
                    pkginfo.search_tier = 0
                    break
                # pkginfo.name for flatpaks is their id (org.foo.BarMaker), which
                # may not actually contain the app's name. In this case their display
                # names are better. The 'name' is still checked first above, because
                # it's static - get_display_name() may involve a lookup with appstream.
                if flatpak and all(piece in pkginfo.get_display_name().upper() for piece in termsSplit):
                    is_match = True
                    pkginfo.search_tier = 0
                    break

                if termsUpper in pkginfo.get_keywords().upper():
                    is_match = True
                    pkginfo.search_tier = 50
                    break

                if (search_in_summary and termsUpper in pkginfo.get_summary().upper()):
                    is_match = True
                    pkginfo.search_tier = 100
                    break
                if(search_in_description and termsUpper in self.installer.get_description(pkginfo).upper()):
                    is_match = True
                    pkginfo.search_tier = 200
                    break
                break

            if is_match:
                searched_packages.append(pkginfo)
                if package_type_preference == prefs.PACKAGE_TYPE_PREFERENCE_APT and not flatpak:
                    hidden_packages.add(FLATPAK_EQUIVS.get(pkginfo.name))
                elif package_type_preference == prefs.PACKAGE_TYPE_PREFERENCE_FLATPAK and flatpak:
                    hidden_packages.add(DEB_EQUIVS.get(pkginfo.name))

            # Repeat until empty
            if len(pkginfos) > 0:
                return True

            self.search_idle_timer = 0

            if package_type_preference == prefs.PACKAGE_TYPE_PREFERENCE_APT:
                results = [p for p in searched_packages if not (p.pkg_hash.startswith("f") and p.name in hidden_packages)]
            elif package_type_preference == prefs.PACKAGE_TYPE_PREFERENCE_FLATPAK:
                results = [p for p in searched_packages if not (p.pkg_hash.startswith("a") and p.name in hidden_packages)]
            else:
                results = searched_packages

            GLib.idle_add(self.on_search_results_complete, results)
            return False

        self.search_idle_timer = GLib.idle_add(idle_search_one_package, list(listing))

    def on_search_results_complete(self, results):
        self.page_stack.set_visible_child_name(self.PAGE_LIST)
        self.show_packages(results, from_search=True)

    def on_app_row_activated(self, listbox, row, previous_page):
        self.show_package(row.pkginfo, previous_page)

    def on_flowbox_item_clicked(self, tile, data=None):
        # This ties the GtkButton.clicked signal for the Tile class
        # to the flowbox mechanics.  Clicks would be handled by
        # GtkFlowBox.child-activated if we weren't using a GtkButton
        # as each flowbox entry.  This could probably fixed eventually
        # but we like the button styling and highlighting.
        tile.get_parent().activate()

    def on_flowbox_child_activated(self, flowbox, child, previous_page):
        flowbox.select_child(child)

        self.show_package(child.pkginfo, previous_page)

    def navigate_flowbox(self, flowbox, scrolled_window):
        try:
            selected = flowbox.get_selected_children()[0]
        except IndexError:
            return

        adj = scrolled_window.get_vadjustment()
        current = adj.get_value()
        sel_box = selected.get_allocation()
        fb_box = flowbox.get_allocation()
        sw_box = scrolled_window.get_allocation()

        unit = sel_box.height
        if (sel_box.y + sw_box.y + fb_box.y + unit) > (current + sw_box.height):
            adj.set_value((sel_box.y + fb_box.y + unit) - sw_box.height)
        elif sel_box.y + fb_box.y < current:
            adj.set_value(sel_box.y + fb_box.y)

    def capitalize(self, string):
        if len(string) > 1:
            return (string[0].upper() + string[1:])
        else:
            return (string)

    @print_timing
    def sort_packages(self, pkgs, key_func):
        sort_pkgs = []
        installed_hashes = self.get_installed_package_hashes()

        for pkg in pkgs:
            sort_pkg = SortPackage(pkg)
            sort_pkg.installed = pkg.pkg_hash in installed_hashes

            # A flatpak's 'name' may not even have the app's name in it.
            # It's better to compare by their display names
            if pkg.pkg_hash.startswith("f"):
                sort_pkg.name = pkg.get_display_name()

            if self.review_cache and pkg.name in self.review_cache:
                sort_pkg.score_desc = -self.review_cache[pkg.name].score

            sort_pkgs.append(sort_pkg)

        sort_pkgs.sort(key=key_func)

        return [pkg.pkg for pkg in sort_pkgs]

    def show_packages(self, pkginfos, from_search=False):
        self.stop_slideshow_timer()

        if self.one_package_idle_timer > 0:
            GLib.source_remove(self.one_package_idle_timer)
            self.one_package_idle_timer = 0

        for child in self.flowbox_applications.get_children():
            self.flowbox_applications.remove(child)

        self.category_tiles = []
        if len(pkginfos) == 0:
            self.app_list_stack.set_visible_child_name("no-results")

            if self.current_category == self.active_tasks_category:
                text = _("All operations complete")
                self.no_packages_found_refresh_button.hide()
            else:
                if from_search:
                    text = _("No matching packages found")
                    self.no_packages_found_refresh_button.hide()
                else:
                    text = _("No packages to show.\nThis may indicate a problem - try refreshing the cache.")
                    self.no_packages_found_refresh_button.show()

            self.no_packages_found_label.set_markup("<big><b>%s</b></big>" % text)
        else:
            self.app_list_stack.set_visible_child_name("results")

        if self.current_category == self.installed_category:
            # Installed category we want to show all apps even if they're 'unverified'.
            # Keep a single entry per package, and put apps with a pending update first.
            unique = []
            seen = set()
            for info in pkginfos:
                if info.pkg_hash in seen:
                    continue
                seen.add(info.pkg_hash)
                unique.append(info)

            apps = [info for info in unique if info.refid == "" or info.refid.startswith("app")]
            apps = self.sort_packages(apps, lambda sort_pkg: (0 if sort_pkg.pkg.pkg_hash in self._upgradable_hashes else 1, sort_pkg.name))
        else:
            if from_search:
                apps = [info for info in pkginfos] # should_show_pkginfo was applied during search matching
                apps = self.sort_packages(apps, attrgetter("unverified", "search_tier", "score_desc", "name"))
            else:
                apps = [info for info in pkginfos if self.should_show_pkginfo(info)]
                apps = self.sort_packages(apps, attrgetter("unverified", "score_desc", "name"))
            apps = apps[0:201]

        # Identify name collisions (to show more info when multiple apps have the same name)
        package_titles = []
        collisions = []

        bad_ones = []
        for pkginfo in apps:
            try:
                title = pkginfo.get_display_name().lower()
                if title in package_titles and title not in collisions:
                    collisions.append(title)
                package_titles.append(title)
            except:
                bad_ones.append(pkginfo)

        for bad in bad_ones:
            apps.remove(bad)

        self.one_package_idle_timer = GLib.idle_add(self.idle_show_one_package,
                                                    apps,
                                                    collisions)

        self.flowbox_applications.show_all()

    def idle_show_one_package(self, pkginfos, collisions):
        try:
            pkginfo = pkginfos.pop(0)
        except IndexError:
            self.one_package_idle_timer = 0
            return False

        icon = self.get_application_icon(pkginfo, imaging.LIST_ICON_SIZE)

        summary = pkginfo.get_summary()

        if self.review_cache:
            review_info = self.review_cache[pkginfo.name]
        else:
            review_info = None

        tile = PackageTile(pkginfo, self.installer, show_package_type=True, review_info=review_info,
                           upgradable=self._is_pkginfo_upgradable(pkginfo))
        self.flowbox_applications.insert(tile, -1)
        self.category_tiles.append(tile)

        # Repeat until empty
        if len(pkginfos) > 0:
            return True

        self.reset_scroll_view(self.builder.get_object("scrolledwindow_applications"))
        self.one_package_idle_timer = 0
        return False

    def on_tile_keypress(self, row, event, data=None):
        if event.keyval in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab):
            self.searchentry.grab_focus()
            return Gdk.EVENT_STOP

        return Gdk.EVENT_PROPAGATE

    def package_type_combo_changed(self, combo):
        iter = combo.get_active_iter()
        if iter:
            pkginfo = combo.get_model().get_value(iter, PACKAGE_TYPE_COMBO_PKGINFO)
            self.show_package(pkginfo, self.previous_page)

    @print_timing
    def show_package(self, pkginfo, previous_page):
        self.page_stack.set_visible_child_name(self.PAGE_DETAILS)
        self.stop_slideshow_timer()
        self.builder.get_object("details_notebook").set_current_page(0)
        self.previous_page = previous_page
        self.back_button.set_sensitive(True)

        self.update_conditional_widgets()

        # Reset the position of our scrolled window back to the top
        self.reset_scroll_view(self.builder.get_object("scrolled_details"))

        self.current_pkginfo = pkginfo
        is_flatpak = pkginfo.pkg_hash.startswith("fp:")

        # Set to busy while the installer figures out what to do
        self.builder.get_object("notebook_progress").set_current_page(self.SPINNER_TAB)

        # Set source-agnostic things

        icon_string = self.get_application_icon_string(pkginfo, imaging.DETAILS_ICON_SIZE)
        self.detail_view_icon.set_icon_string(icon_string)

        self.package_type_store.clear()
        self.package_type_combo.set_button_sensitivity(Gtk.SensitivityType.AUTO)

        try:
            self.package_type_combo.disconnect_by_func(self.package_type_combo_changed)
        except TypeError:
            pass

        self.package_type_store.clear()

        i = 0
        to_use_iter = None
        row_pkginfo = None
        row = None
        tooltip = None

        # add system if this is a system package, or one exists in our match table.
        if not is_flatpak:
            row_pkginfo = pkginfo
        else:
            match = self.get_deb_for_flatpak(pkginfo)
            if match is not None:
                row_pkginfo = match

        if row_pkginfo:
            row = [i, _("System Package"), _("Your system's package manager"), "linuxmint-logo-badge-symbolic", row_pkginfo]
            iter = self.package_type_store.append(row)
            if pkginfo == row_pkginfo:
                to_use_iter = iter
                tooltip = row[PACKAGE_TYPE_COMBO_SUMMARY]
            i += 1

        if is_flatpak or self.get_flatpak_for_deb(pkginfo) is not None:
            a_flatpak = self.get_flatpak_for_deb(pkginfo) or pkginfo
            for remote in self.installer.list_flatpak_remotes():
                row_pkginfo = self.installer.find_pkginfo(a_flatpak.name, installer.PKG_TYPE_FLATPAK, remote=remote.name)
                if row_pkginfo:
                    row = [i, _("Flatpak (%s)") % remote.title, remote.summary, "mintinstall-package-flatpak-symbolic", row_pkginfo]
                    iter = self.package_type_store.append(row)
                    if pkginfo == row_pkginfo:
                        to_use_iter = iter
                        tooltip = row[PACKAGE_TYPE_COMBO_SUMMARY]
                    i += 1

        if i == 1:
            self.package_type_combo.hide()
            self.single_version_package_type_box.show()
            self.single_version_package_type_label.set_label(row[PACKAGE_TYPE_COMBO_LABEL])
            self.single_version_package_type_icon.set_from_icon_name(row[PACKAGE_TYPE_COMBO_ICON_NAME], Gtk.IconSize.BUTTON)
            self.single_version_package_type_box.set_tooltip_text(row[PACKAGE_TYPE_COMBO_SUMMARY])
        else:
            self.single_version_package_type_box.hide()
            self.package_type_combo.show()
            self.package_type_combo.set_active_iter(to_use_iter)
            self.package_type_combo.set_tooltip_text(tooltip)

        self.package_help_button.set_visible(i > 1 or is_flatpak)

        self.unsafe_box.hide()
        self.builder.get_object("application_dev_name").set_label("")

        if is_flatpak:
            self.flatpak_details_vgroup.show()
            # We don't know flatpak versions until the task reports back, apt we know immediately.
            self.builder.get_object("application_version").set_label("")

            dev_name = self.installer.get_developer(pkginfo)
            if dev_name != "":
                self.builder.get_object("application_dev_name").set_label(_("by %s") % dev_name)
            else:
                self.builder.get_object("application_dev_name").set_label(_("Unknown maintainer"))

            if not pkginfo.verified:
                self.unsafe_box.show()
                self.builder.get_object("application_dev_name").set_label("")

        else:
            self.flatpak_details_vgroup.hide()
            self.builder.get_object("application_version").set_label(self.installer.get_version(pkginfo))

        self.package_type_combo.connect("changed", self.package_type_combo_changed)

        app_name = pkginfo.get_display_name()

        self.builder.get_object("application_name").set_label(app_name)
        self.builder.get_object("application_summary").set_label(pkginfo.get_summary())
        self.builder.get_object("application_package").set_label(pkginfo.name)
        self.builder.get_object("application_size").set_markup("")
        self.builder.get_object("application_remote").set_markup("")
        self.builder.get_object("application_branch").set_markup("")

        homepage_url = self.installer.get_homepage_url(pkginfo)
        if homepage_url not in ('', None):
            self.builder.get_object("application_homepage").show()
            homepage_label = _("Homepage")
            self.builder.get_object("application_homepage").set_markup("<a href='%s'>%s</a>" % (homepage_url, homepage_label))
            self.builder.get_object("application_homepage").set_tooltip_text(homepage_url)
        else:
            self.builder.get_object("application_homepage").hide()

        helppage_url = self.installer.get_help_url(pkginfo)
        if helppage_url not in ('', None):
            self.builder.get_object("application_help_page").show()
            helppage_label = _("Documentation")
            self.builder.get_object("application_help_page").set_markup("<a href='%s'>%s</a>" % (helppage_url, helppage_label))
            self.builder.get_object("application_help_page").set_tooltip_text(helppage_url)
        else:
            self.builder.get_object("application_help_page").hide()

        description = self.installer.get_description(pkginfo)

        if self.settings.get_boolean(prefs.HAMONIKR_SCREENSHOTS):
            try:
                from bs4 import BeautifulSoup
                hamonikrpkgname = pkginfo.name.replace("-","_")
                page = BeautifulSoup(urllib.request.urlopen("https://hamonikr.org/%s" % hamonikrpkgname, timeout=5), "lxml")
                texts = page.find("div","xe_content")
                text = texts.get_text()
                if text is not None:
                    description = text
            except Exception as e:
                pass

        app_description = self.builder.get_object("application_description")

        if description not in (None, ''):
            app_description.set_label(description)
            app_description.show()
        else:
            app_description.hide()

        box_reviews = self.builder.get_object("box_reviews")

        for child in box_reviews.get_children():
            box_reviews.remove(child)

        if not is_flatpak or pkginfo.verified:
            review_info = self.review_cache[pkginfo.name]

            label_num_reviews = self.builder.get_object("application_num_reviews")

            # TRANSLATORS: showing specific number of reviews in the list view and the header of the package details.
            review_text = gettext.ngettext("%d Review", "%d Reviews", review_info.num_reviews) % review_info.num_reviews
            label_num_reviews.set_label(review_text)

            self.builder.get_object("application_avg_rating").set_label(str(review_info.avg_rating))

            box_stars = self.builder.get_object("box_stars")
            for child in box_stars.get_children():
                box_stars.remove(child)
            rating = review_info.avg_rating
            remaining_stars = 5
            while rating >= 1.0:
                box_stars.pack_start(Gtk.Image(icon_name="xsi-starred-symbolic", pixel_size=16), False, False, 0)
                rating -= 1
                remaining_stars -= 1
            if rating > 0.0:
                box_stars.pack_start(Gtk.Image(icon_name="xsi-semi-starred-symbolic", pixel_size=16), False, False, 0)
                remaining_stars -= 1
            for i in range(remaining_stars):
                box_stars.pack_start(Gtk.Image(icon_name="xsi-non-starred-symbolic", pixel_size=16), False, False, 0)

            box_stars.show_all()

            for i in range(0, 5):
                self.star_bars[i].set_fraction(0.0)
                self.builder.get_object("stars_count_%d" % (i + 1)).set_label("")

            reviews = review_info.reviews
            reviews.sort(key=lambda x: x.date, reverse=True)

            stars = [0, 0, 0, 0, 0]
            n_reviews = len(reviews)

            if n_reviews > 0:
                # TRANSLATORS: reviews heading in package details view
                # label_reviews.set_text(_("Reviews"))
                i = 0
                for review in reviews:
                    if i < 10:
                        comment = review.comment.strip()
                        comment = comment.replace("'", "\'")
                        comment = comment.replace('"', '\"')
                        comment = self.capitalize(comment)
                        review_date = datetime.fromtimestamp(review.date).strftime("%Y.%m.%d")
                        tile = ReviewTile(review.username, review_date, comment, review.rating)
                        box_reviews.add(tile)
                        i = i +1

                    stars[review.rating - 1] += 1

                for i in range(0, 5):
                    widget_idx = i + 1
                    label = self.builder.get_object("stars_count_%s" % widget_idx)

                    label.set_label(str(stars[i]))
                    self.star_bars[i].set_fraction(stars[i] / n_reviews)

            add_your_own = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            add_your_own.set_margin_start(12)
            add_your_own.set_margin_end(12)
            add_your_own.set_margin_top(12)
            add_your_own.set_margin_bottom(12)

            community_link = "https://community.linuxmint.com/software/view/%s" % pkginfo.name
            label = Gtk.Label(xalign=0.0, use_markup=True, label=_("Click <a href='%s'>here</a> to add your own review.") % community_link)
            add_your_own.pack_start(label, True, True, 0)
            box_reviews.add(add_your_own)
            box_reviews.show_all()
            self.builder.get_object("reviews_page").show()
            self.builder.get_object("details_review_box").show()
        else:
            self.builder.get_object("reviews_page").hide()
            self.builder.get_object("details_review_box").hide()

        # Screenshots
        self.destroy_screenshot_window()
        for child in self.screenshot_stack.get_children():
            child.destroy()

        self.ss_swipe_handler.set_propagation_phase(Gtk.PropagationPhase.NONE)
        self.screenshot_stack.last = 0
        self.screenshot_stack.add_named(Gtk.Spinner(active=True), "spinner")
        self.screenshot_controls_vgroup.set_visible(False)
        self.add_screenshots(pkginfo)
        self.screenshot_stack.show_all()
        self.screenshot_stack.grab_focus()

        # Call the installer to get the rest of the information
        self.task_cancellable = self.installer.select_pkginfo(pkginfo,
                                                              self.on_installer_info_ready, self.on_installer_info_error,
                                                              self.on_installer_finished, self.on_installer_progress,
                                                              use_mainloop=True)

        self.populate_addons(pkginfo)

    def on_package_type_button_clicked(self, button, pkginfo):
        self.show_package(pkginfo, self.previous_page)

    def get_flatpak_for_deb(self, pkginfo):
        try:
            fp_name = FLATPAK_EQUIVS[pkginfo.name]
            flatpak_pkginfo = self.installer.find_pkginfo(fp_name, installer.PKG_TYPE_FLATPAK)
            if self.should_show_pkginfo(flatpak_pkginfo):
                return flatpak_pkginfo
        except:
            return None

    def get_deb_for_flatpak(self, pkginfo):
        try:
            deb_name = DEB_EQUIVS[pkginfo.name]
            return self.installer.find_pkginfo(deb_name, installer.PKG_TYPE_APT)
        except:
            return None

    def on_installer_info_error(self, task):
        if networking_available():
            if task.info_ready_status != task.STATUS_FORBIDDEN:
                dialogs.show_error(task.error_message)
        else:
            dialogs.show_error(_("Unable to communicate with servers. Check your Internet connection and try again."))

        self.recursion_buster = True
        # The error ui changes can be handled in the normal callback
        self.on_installer_info_ready(task)

    def on_installer_info_ready(self, task):
        self.current_task = task
        self.task_cancellable = None

        pkginfo = task.pkginfo

        if pkginfo != self.current_pkginfo and (not self.installer.task_running(task)):
            return

        if self.installer.task_running(task):
            self.builder.get_object("notebook_progress").set_current_page(self.PROGRESS_TAB)
        else:
            self.builder.get_object("notebook_progress").set_current_page(self.ACTION_TAB)
            task.parent_window = self.main_window

        # Load package info
        style_context = self.action_button.get_style_context()

        action_button_description = ""
        action_button_icon = None

        if task.info_ready_status == task.STATUS_OK:
            if task.type == "remove":
                action_button_label = _("Remove")
                action_button_icon = None
                style_context.remove_class("suggested-action")
                style_context.add_class("destructive-action")
                action_button_description = _("Installed")
                self.action_button.set_sensitive(True)
                self.progress_label.set_text(_("Removing"))
            else:
                action_button_label = _("Install")
                if pkginfo.pkg_hash.startswith("f"):
                    action_button_icon = "mintinstall-package-flatpak-symbolic"
                else:
                    action_button_icon = "linuxmint-logo-badge-symbolic"

                style_context.remove_class("destructive-action")
                style_context.add_class("suggested-action")
                action_button_description = _("Not installed")
                self.action_button.set_sensitive(True)
                self.progress_label.set_text(_("Installing"))

        else:
            if task.info_ready_status == task.STATUS_FORBIDDEN:
                if task.type == "remove":
                    action_button_label = _("Cannot remove")
                    action_button_description = _("Removing this package could cause irreparable damage to your system.")
                else:
                    action_button_label = _("Cannot install")
                    action_button_description = _("Installing this package could cause irreparable damage to your system.")

                    style_context.remove_class("suggested-action")
                    style_context.add_class("destructive-action")

                self.action_button.set_sensitive(False)
                self.progress_label.set_text("")
            elif task.info_ready_status == task.STATUS_BROKEN:
                action_button_label = _("Not available")
                style_context.remove_class("destructive-action")
                style_context.remove_class("suggested-action")
                if task.type == "install":
                    action_button_description = _("Please use apt-get to install this package.")
                else:
                    action_button_description = _("Use apt-get to remove this package.")

                self.action_button.set_sensitive(False)
            elif task.info_ready_status == task.STATUS_UNKNOWN:
                action_button_label = _("Try again")
                style_context.remove_class("destructive-action")
                style_context.add_class("suggested-action")
                action_button_description = _("Something went wrong. Click to try again.")
                self.action_button.set_sensitive(True)
                self.progress_label.set_text("")
            action_button_icon = None

        self.action_button.set_label(action_button_label)
        self.action_button.set_tooltip_text(action_button_description)

        # While a package can be updated, the Update action takes the place of
        # Launch instead of being shown as an additional button.
        has_update = (task.info_ready_status == task.STATUS_OK
                      and self.installer.pkginfo_is_installed(pkginfo)
                      and self._is_pkginfo_upgradable(pkginfo))
        self.single_update_button.set_visible(has_update)

        try:
            self.builder.get_object("application_remote").set_label(self.flatpak_remote_categories[task.remote].name)
        except (KeyError, AttributeError):
            self.builder.get_object("application_remote").set_label(task.remote)

        self.builder.get_object("application_branch").set_label(task.branch)

        try:
            self.builder.get_object("application_version").set_label(task.version)
        except TypeError:
            self.builder.get_object("application_version").set_label("")

        sizeinfo = ""

        if self.installer.pkginfo_is_installed(pkginfo):
            if task.freed_size > 0:
                sizeinfo = get_size_for_display(task.freed_size)
            elif task.install_size > 0:
                sizeinfo = _("%(localSize)s of disk space required") \
                                 % {'localSize': get_size_for_display(task.install_size)}
        else:
            if task.freed_size > 0:
                sizeinfo = _("%(downloadSize)s to download, %(localSize)s of disk space freed") \
                               % {'downloadSize': get_size_for_display(task.download_size), 'localSize': get_size_for_display(task.freed_size)}
            else:
                sizeinfo = _("%(downloadSize)s to download, %(localSize)s of disk space required") \
                               % {'downloadSize': get_size_for_display(task.download_size), 'localSize': get_size_for_display(task.install_size)}

        if task.info_ready_status != task.STATUS_UNKNOWN:
            self.builder.get_object("application_size").set_label(sizeinfo)
            self.flatpak_details_vgroup.set_visible(task.branch != "")


        if self.action_button_signal_id > 0:
            self.action_button.disconnect(self.action_button_signal_id)
            self.action_button_signal_id = 0

        self.action_button_signal_id = self.action_button.connect("clicked",
                                                                  self.on_action_button_clicked,
                                                                  task)

        bin_name = pkginfo.name.replace(":i386", "")
        exec_string = None

        if self.installer.pkginfo_is_installed(pkginfo):
            if pkginfo.pkg_hash.startswith("a"):
                for desktop_file in [
                    # foo.desktop
                    "/usr/share/applications/%s.desktop" % bin_name,
                    # foo in foo-bar.desktop or foo_bar.desktop
                    "/usr/share/applications/%s.desktop" % bin_name.split("-")[0],
                    "/usr/share/applications/%s.desktop" % bin_name.split("_")[0],
                    # foo-bar package with foo_bar.desktop
                    "/usr/share/applications/%s.desktop" % bin_name.replace("-", "_"),
                    # foo in org.bar.Foo.desktop
                    "/usr/share/applications/%s.desktop" % bin_name.split(".")[-1],
                    "/usr/share/app-install/desktop/%s:%s.desktop" % (bin_name, bin_name)
                    ]:

                    if os.path.exists(desktop_file):
                        try:
                            info = Gio.DesktopAppInfo.new_from_filename(desktop_file)
                            exec_string = info.get_commandline()
                            if exec_string is not None:
                                break
                        except Exception as e:
                            print(e)
                if exec_string is None and os.path.exists("/usr/bin/%s" % bin_name):
                    exec_string = "/usr/bin/%s" % bin_name
            else:
                launchables = self.installer.get_flatpak_launchables(pkginfo)
                if launchables:
                    for desktop_id in launchables:
                        desktop_file = os.path.join(self.installer.get_flatpak_root_path(), "exports/share/applications", desktop_id)
                        try:
                            info = Gio.DesktopAppInfo.new_from_filename(desktop_file)
                        except TypeError:
                            info = Gio.DesktopAppInfo.new_from_filename(desktop_file + ".desktop")
                        exec_string = info.get_commandline()
                        break
                else:
                    desktop_file = os.path.join(self.installer.get_flatpak_root_path(), "exports/share/applications", pkginfo.name)
                    info = None
                    try:
                        info = Gio.DesktopAppInfo.new_from_filename(desktop_file)
                    except TypeError:
                        try:
                            info = Gio.DesktopAppInfo.new_from_filename(desktop_file + ".desktop")
                        except:
                            pass
                    if info is not None:
                        exec_string = info.get_commandline()

        if exec_string is not None:
            task.exec_string = exec_string

            if self.launch_button_signal_id > 0:
                self.launch_button.disconnect(self.launch_button_signal_id)
                self.launch_button_signal_id = 0

            self.launch_button_signal_id = self.launch_button.connect("clicked",
                                                                      self.on_launch_button_clicked,
                                                                      task)

        # Launch is only shown when there is something to launch and no update
        # is waiting, since the Update button replaces it in that case.
        self.launch_button.set_visible(exec_string is not None and not has_update)

    def populate_addons(self, pkginfo):
        for row in self.addons_listbox.get_children():
            row.destroy()

        addons = self.installer.get_addons(pkginfo)
        if addons is None:
            self.builder.get_object("addons_page").hide()
            return

        name_size_group = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)
        button_size_group = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)

        first = True
        for addon in addons:
            print("Discovered addon: %s" % addon.name)
            first = False

            row = FlatpakAddonRow(self, pkginfo, addon, name_size_group, button_size_group)
            self.addons_listbox.insert(row, -1)
            self.builder.get_object("addons_page").show_all()

    def on_installer_progress(self, pkginfo, progress, estimating, status_text=None):
        if self.current_pkginfo is not None and self.current_pkginfo.name == pkginfo.name:
            self.builder.get_object("notebook_progress").set_current_page(self.PROGRESS_TAB)

            if estimating:
                self.start_progress_pulse()
            else:
                self.stop_progress_pulse()

                self.builder.get_object("application_progress").set_fraction(progress / 100.0)
                XApp.set_window_progress(self.main_window, progress)
                self.progress_label.tick()

    def on_installer_finished(self, task):
        if self.current_pkginfo is not None and self.current_pkginfo.name == task.pkginfo.name:
            self.stop_progress_pulse()

            self.builder.get_object("notebook_progress").set_current_page(self.ACTION_TAB)
            self.builder.get_object("application_progress").set_fraction(0 / 100.0)
            XApp.set_window_progress(self.main_window, 0)

        self.update_state(task.pkginfo)

    def start_progress_pulse(self):
        if self.installer_pulse_timer > 0:
            return

        self.builder.get_object("application_progress").pulse()
        self.installer_pulse_timer = GLib.timeout_add(1050, self.installer_pulse_tick)

    def installer_pulse_tick(self):
        p = self.builder.get_object("application_progress")

        p.pulse()

        return GLib.SOURCE_CONTINUE

    def stop_progress_pulse(self):
        if self.installer_pulse_timer > 0:
            GLib.source_remove(self.installer_pulse_timer)
            self.installer_pulse_timer = 0

class DottedProgressLabel(Gtk.Fixed):
    """
    Centers a label's base text, adds ... as a progress/
    activity indicator, without the text getting repositioned.
    """
    def __init__(self):
        super(DottedProgressLabel, self).__init__()

        self.real_text = ""
        self.label = Gtk.Label()
        self.num_dots = 0

        self.add(self.label)
        self.label.show()

    def set_text(self, text):
        self.real_text = text

        self.label.set_text(text)
        self._adjust_position()

    def tick(self):
        if self.num_dots < 5:
            self.num_dots += 1
        else:
            self.num_dots = 0

        new_string = self.real_text

        i = 0

        while i < self.num_dots:
            new_string += "."
            i += 1

        self.label.set_text(new_string)

    def _adjust_position(self):
        layout = self.label.create_pango_layout()

        layout.set_text(self.real_text, -1)
        w, h = layout.get_pixel_size()

        parent_width = self.get_allocated_width()

        x_offset = (parent_width - w) / 2

        self.move(self.label, x_offset, 0)

if __name__ == "__main__":
    os.system("mkdir -p %s" % imaging.SCREENSHOT_DIR)

    if os.environ.get("RAYON_NUM_THREADS") is None:
        os.environ["RAYON_NUM_THREADS"] = "2"

    app = Application()
    app.run(sys.argv)
