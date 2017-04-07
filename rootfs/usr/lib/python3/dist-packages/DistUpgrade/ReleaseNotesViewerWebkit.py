# ReleaseNotesViewer.py
# -*- Mode: Python; indent-tabs-mode: nil; tab-width: 4; coding: utf-8 -*-
#
#  Copyright (c) 2011 Canonical
#
#  Author: Michael Vogt <mvo@ubutnu.com>
#
#  This modul provides an inheritance of the Gtk.TextView that is
#  aware of http URLs and allows to open them in a browser.
#  It is based on the pygtk-demo "hypertext".
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License as
#  published by the Free Software Foundation; either version 2 of the
#  License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA 02111-1307
#  USA

from __future__ import absolute_import

from gi.repository import Gtk
from gi.repository import WebKit

from .ReleaseNotesViewer import open_url


class ReleaseNotesViewerWebkit(WebKit.WebView):
    def __init__(self, notes_url):
        super(ReleaseNotesViewerWebkit, self).__init__()
        self.load_uri(notes_url)
        self.connect("navigation-policy-decision-requested",
                     self._on_navigation_policy_decision_requested)

    def _on_navigation_policy_decision_requested(self, view, frame, request,
                                                 action, policy):
        open_url(request.get_uri())
        policy.ignore()
        return True


if __name__ == "__main__":
    win = Gtk.Window()
    win.set_size_request(600, 400)
    scroll = Gtk.ScrolledWindow()
    rv = ReleaseNotesViewerWebkit("http://archive.ubuntu.com/ubuntu/dists/"
                                  "natty/main/dist-upgrader-all/0.150/"
                                  "ReleaseAnnouncement.html")
    scroll.add(rv)
    win.add(scroll)
    win.show_all()
    Gtk.main()
