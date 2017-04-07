# DistUpgradeFetcherKDE.py
# -*- Mode: Python; indent-tabs-mode: nil; tab-width: 4; coding: utf-8 -*-
#
#  Copyright (c) 2008 Canonical Ltd
#
#  Author: Jonathan Riddell <jriddell@ubuntu.com>
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
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import absolute_import

from PyKDE4.kdecore import ki18n, KAboutData, KCmdLineOptions, KCmdLineArgs
from PyKDE4.kdeui import KIcon, KMessageBox, KApplication, KStandardGuiItem
from PyQt4.QtCore import QDir, QTimer
from PyQt4.QtGui import QDialog, QDialogButtonBox
from PyQt4 import uic

import apt_pkg
import sys

from .utils import inhibit_sleep, allow_sleep
from .DistUpgradeFetcherCore import DistUpgradeFetcherCore
from gettext import gettext as _
try:
    from urllib.request import urlopen
    from urllib.error import HTTPError
except ImportError:
    from urllib2 import urlopen, HTTPError
import os

from .MetaRelease import MetaReleaseCore
import apt


class DistUpgradeFetcherKDE(DistUpgradeFetcherCore):
    """A small application run by Adept to download, verify
    and run the dist-upgrade tool"""

    def __init__(self, useDevelopmentRelease=False, useProposed=False):
        self.useDevelopmentRelease = useDevelopmentRelease
        self.useProposed = useProposed
        metaRelease = MetaReleaseCore(useDevelopmentRelease, useProposed)
        metaRelease.downloaded.wait()
        if metaRelease.new_dist is None and __name__ == "__main__":
            sys.exit()
        elif metaRelease.new_dist is None:
            return

        self.progressDialogue = QDialog()
        if os.path.exists("fetch-progress.ui"):
            self.APPDIR = QDir.currentPath()
        else:
            self.APPDIR = "/usr/share/ubuntu-release-upgrader"

        uic.loadUi(self.APPDIR + "/fetch-progress.ui", self.progressDialogue)
        self.progressDialogue.setWindowIcon(KIcon("system-software-update"))
        self.progressDialogue.setWindowTitle(_("Upgrade"))
        self.progress = KDEAcquireProgressAdapter(
            self.progressDialogue.installationProgress,
            self.progressDialogue.installingLabel,
            None)
        DistUpgradeFetcherCore.__init__(self, metaRelease.new_dist,
                                        self.progress)

    def error(self, summary, message):
        KMessageBox.sorry(None, message, summary)

    def runDistUpgrader(self):
        inhibit_sleep()
        # now run it with sudo
        if os.getuid() != 0:
            os.execv("/usr/bin/kdesudo",
                     ["kdesudo",
                      self.script + " --frontend=DistUpgradeViewKDE"])
        else:
            os.execv(self.script,
                     [self.script] + ["--frontend=DistUpgradeViewKDE"] +
                     self.run_options)
        # we shouldn't come to this point, but if we do, undo our
        # inhibit sleep
        allow_sleep()

    def showReleaseNotes(self):
        # FIXME: care about i18n! (append -$lang or something)
        self.dialogue = QDialog()
        uic.loadUi(self.APPDIR + "/dialog_release_notes.ui", self.dialogue)
        upgradeButton = self.dialogue.buttonBox.button(QDialogButtonBox.Ok)
        upgradeButton.setText(_("Upgrade"))
        upgradeButton.setIcon(KIcon("dialog-ok"))
        cancelButton = self.dialogue.buttonBox.button(QDialogButtonBox.Cancel)
        cancelButton.setIcon(KIcon("dialog-cancel"))
        self.dialogue.setWindowTitle(_("Release Notes"))
        self.dialogue.show()
        if self.new_dist.releaseNotesURI is not None:
            uri = self._expandUri(self.new_dist.releaseNotesURI)
            # download/display the release notes
            # FIXME: add some progress reporting here
            result = None
            try:
                release_notes = urlopen(uri)
                notes = release_notes.read().decode("UTF-8", "replace")
                self.dialogue.scrolled_notes.setText(notes)
                result = self.dialogue.exec_()
            except HTTPError:
                primary = "<span weight=\"bold\" size=\"larger\">%s</span>" % \
                          _("Could not find the release notes")
                secondary = _("The server may be overloaded. ")
                KMessageBox.sorry(None, primary + "<br />" + secondary, "")
            except IOError:
                primary = "<span weight=\"bold\" size=\"larger\">%s</span>" % \
                          _("Could not download the release notes")
                secondary = _("Please check your internet connection.")
                KMessageBox.sorry(None, primary + "<br />" + secondary, "")
            # user clicked cancel
            if result == QDialog.Accepted:
                self.progressDialogue.show()
                return True
        if __name__ == "__main__":
            KApplication.kApplication().exit(1)
        if self.useDevelopmentRelease or self.useProposed:
            #FIXME why does KApplication.kApplication().exit() crash but
            # this doesn't?
            sys.exit()
        return False


class KDEAcquireProgressAdapter(apt.progress.base.AcquireProgress):
    def __init__(self, progress, label, parent):
        self.progress = progress
        self.label = label
        self.parent = parent

    def start(self):
        self.label.setText(_("Downloading additional package files..."))
        self.progress.setValue(0)

    def stop(self):
        pass

    def pulse(self, owner):
        apt.progress.base.AcquireProgress.pulse(self, owner)
        self.progress.setValue((self.current_bytes + self.current_items) /
                               float(self.total_bytes + self.total_items))
        current_item = self.current_items + 1
        if current_item > self.total_items:
            current_item = self.total_items
        label_text = _("Downloading additional package files...")
        if self.current_cps > 0:
            label_text += _("File %s of %s at %sB/s") % (
                self.current_items, self.total_items,
                apt_pkg.size_to_str(self.current_cps))
        else:
            label_text += _("File %s of %s") % (
                self.current_items, self.total_items)
        self.label.setText(label_text)
        KApplication.kApplication().processEvents()
        return True

    def mediaChange(self, medium, drive):
        msg = _("Please insert '%s' into the drive '%s'") % (medium, drive)
        #change = QMessageBox.question(None, _("Media Change"), msg,
        #                              QMessageBox.Ok, QMessageBox.Cancel)
        change = KMessageBox.questionYesNo(None, _("Media Change"),
                                           _("Media Change") + "<br>" + msg,
                                           KStandardGuiItem.ok(),
                                           KStandardGuiItem.cancel())
        if change == KMessageBox.Yes:
            return True
        return False

if __name__ == "__main__":

    appName = "dist-upgrade-fetcher"
    catalog = ""
    programName = ki18n("Dist Upgrade Fetcher")
    version = "0.3.4"
    description = ki18n("Dist Upgrade Fetcher")
    license = KAboutData.License_GPL
    copyright = ki18n("(c) 2008 Canonical Ltd")
    text = ki18n("none")
    homePage = "https://launchpad.net/ubuntu-release-upgrader"
    bugEmail = ""

    aboutData = KAboutData(appName, catalog, programName, version, description,
                           license, copyright, text, homePage, bugEmail)

    aboutData.addAuthor(ki18n("Jonathan Riddell"), ki18n("Author"))

    options = KCmdLineOptions()

    KCmdLineArgs.init(sys.argv, aboutData)
    KCmdLineArgs.addCmdLineOptions(options)

    app = KApplication()
    fetcher = DistUpgradeFetcherKDE()
    QTimer.singleShot(10, fetcher.run)

    app.exec_()
