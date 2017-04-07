# DistUpgradeQuirks.py
#
#  Copyright (c) 2004-2010 Canonical
#
#  Author: Michael Vogt <michael.vogt@ubuntu.com>
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

import apt
import atexit
import glob
import logging
import os
import re
import hashlib
import shutil
import sys
import subprocess
from subprocess import PIPE, Popen

from .utils import get_arch

from .DistUpgradeGettext import gettext as _
from .janitor.plugincore.manager import PluginManager


class DistUpgradeQuirks(object):
    """
    This class collects the various quirks handlers that can
    be hooked into to fix/work around issues that the individual
    releases have
    """

    def __init__(self, controller, config):
        self.controller = controller
        self._view = controller._view
        self.config = config
        self.uname = Popen(["uname", "-r"], stdout=PIPE,
                           universal_newlines=True).communicate()[0].strip()
        self.arch = get_arch()
        self.plugin_manager = PluginManager(self.controller, ["./plugins"])
        self._poke = None

    # the quirk function have the name:
    #  $Name (e.g. PostUpgrade)
    #  $todist$Name (e.g. intrepidPostUpgrade)
    #  $from_$fromdist$Name (e.g. from_dapperPostUpgrade)
    def run(self, quirksName):
        """
        Run the specific quirks handler, the follow handlers are supported:
        - PreCacheOpen: run *before* the apt cache is opened the first time
                        to set options that affect the cache
        - PostInitialUpdate: run *before* the sources.list is rewritten but
                             after a initial apt-get update
        - PostDistUpgradeCache: run *after* the dist-upgrade was calculated
                                in the cache
        - StartUpgrade: before the first package gets installed (but the
                        download is finished)
        - PostUpgrade: run *after* the upgrade is finished successfully and
                       packages got installed
        - PostCleanup: run *after* the cleanup (orphaned etc) is finished
        """
        # we do not run any quirks in partialUpgrade mode
        if self.controller._partialUpgrade:
            logging.info("not running quirks in partialUpgrade mode")
            return
        to_release = self.config.get("Sources", "To")
        from_release = self.config.get("Sources", "From")
        # first check for matching plugins
        for condition in [
            quirksName,
            "%s%s" % (to_release, quirksName),
            "from_%s%s" % (from_release, quirksName)
                ]:
            for plugin in self.plugin_manager.get_plugins(condition):
                logging.debug("running quirks plugin %s" % plugin)
                plugin.do_cleanup_cruft()

        # run the handler that is common to all dists
        funcname = "%s" % quirksName
        func = getattr(self, funcname, None)
        if func is not None:
            logging.debug("quirks: running %s" % funcname)
            func()

        # run the quirksHandler to-dist
        funcname = "%s%s" % (to_release, quirksName)
        func = getattr(self, funcname, None)
        if func is not None:
            logging.debug("quirks: running %s" % funcname)
            func()

        # now run the quirksHandler from_${FROM-DIST}Quirks
        funcname = "from_%s%s" % (from_release, quirksName)
        func = getattr(self, funcname, None)
        if func is not None:
            logging.debug("quirks: running %s" % funcname)
            func()

    # individual quirks handler that run *before* the cache is opened
    def PreCacheOpen(self):
        """ run before the apt cache is opened the first time """
        logging.debug("running Quirks.PreCacheOpen")

    def oneiricPreCacheOpen(self):
        logging.debug("running Quirks.oneiricPreCacheOpen")
        # enable i386 multiach temporarely during the upgrade if on amd64
        # this needs to be done very early as libapt caches the result
        # of the "getArchitectures()" call in aptconfig and its not possible
        # currently to invalidate this cache
        if apt.apt_pkg.config.find("Apt::Architecture") == "amd64":
            logging.debug(
                "multiarch: enabling i386 as a additional architecture")
            apt.apt_pkg.config.set("Apt::Architectures::", "i386")
            # increase case size to workaround bug in natty apt that
            # may cause segfault on cache grow
            apt.apt_pkg.config.set("APT::Cache-Start", str(48*1024*1024))

    # individual quirks handler when the dpkg run is finished ---------
    def PostCleanup(self):
        " run after cleanup "
        logging.debug("running Quirks.PostCleanup")

    # quirks when run when the initial apt-get update was run ----------------
    def from_lucidPostInitialUpdate(self):
        """ Quirks that are run before the sources.list is updated to the
            new distribution when upgrading from a lucid system (either
            to maverick or the new LTS)
        """
        logging.debug("running %s" % sys._getframe().f_code.co_name)
        # systems < i686 will not upgrade
        self._test_and_fail_on_non_i686()
        self._test_and_warn_on_i8xx()

    def from_precisePostInitialUpdate(self):
        if self.arch in ['i386', 'amd64']:
            self._checkPae()
        self._test_and_warn_for_unity_3d_support()

    def oneiricPostInitialUpdate(self):
        self._test_and_warn_on_i8xx()

    def lucidPostInitialUpdate(self):
        """ quirks that are run before the sources.list is updated to lucid """
        logging.debug("running %s" % sys._getframe().f_code.co_name)
        # upgrades on systems with < arvm6 CPUs will break
        self._test_and_fail_on_non_arm_v6()
        # vserver+upstart are problematic
        self._test_and_warn_if_vserver()
        # fglrx dropped support for some cards
        self._test_and_warn_on_dropped_fglrx_support()

    def nattyPostDistUpgradeCache(self):
        """
        this function works around quirks in the
        maverick -> natty cache upgrade calculation
        """
        self._add_kdegames_card_extra_if_installed()

    def maverickPostDistUpgradeCache(self):
        """
        this function works around quirks in the
        lucid->maverick upgrade calculation
        """
        self._add_extras_repository()
        self._gutenprint_fixup()

    # run right before the first packages get installed
    def StartUpgrade(self):
        self._applyPatches()
        self._removeOldApportCrashes()
        self._killUpdateNotifier()
        self._killKBluetooth()
        self._killScreensaver()
        self._pokeScreensaver()
        self._stopDocvertConverter()

    def oneiricStartUpgrade(self):
        logging.debug("oneiric StartUpgrade quirks")
        # fix grub issue
        if (os.path.exists("/usr/sbin/update-grub") and
                not os.path.exists("/etc/kernel/postinst.d/zz-update-grub")):
            # create a version of zz-update-grub to avoid depending on
            # the upgrade order. if that file is missing, we may end
            # up generating a broken grub.cfg
            targetdir = "/etc/kernel/postinst.d"
            if not os.path.exists(targetdir):
                os.makedirs(targetdir)
            logging.debug("copying zz-update-grub into %s" % targetdir)
            shutil.copy("zz-update-grub", targetdir)
            os.chmod(os.path.join(targetdir, "zz-update-grub"), 0o755)
        # enable multiarch permanently
        if apt.apt_pkg.config.find("Apt::Architecture") == "amd64":
            self._enable_multiarch(foreign_arch="i386")

    def from_hardyStartUpgrade(self):
        logging.debug("from_hardyStartUpgrade quirks")
        self._stopApparmor()

    # helpers
    def _get_pci_ids(self):
        """ return a set of pci ids of the system (using lspci -n) """
        lspci = set()
        try:
            p = subprocess.Popen(["lspci", "-n"], stdout=subprocess.PIPE,
                                 universal_newlines=True)
        except OSError:
            return lspci
        for line in p.communicate()[0].split("\n"):
            if line:
                lspci.add(line.split()[2])
        return lspci

    def _test_and_warn_for_unity_3d_support(self):
        UNITY_SUPPORT_TEST = "/usr/lib/nux/unity_support_test"
        if (not os.path.exists(UNITY_SUPPORT_TEST) or
                not "DISPLAY" in os.environ):
            return
        # see if there is a running unity, that service is used by both 2d,3d
        return_code = subprocess.call(
            ["ps", "-C", "unity-panel-service"], stdout=open(os.devnull, "w"))
        if return_code != 0:
            logging.debug(
                "_test_and_warn_for_unity_3d_support: no unity running")
            return
        # if we are here, we need to test and warn
        return_code = subprocess.call([UNITY_SUPPORT_TEST])
        logging.debug(
            "_test_and_warn_for_unity_3d_support '%s' returned '%s'" % (
                UNITY_SUPPORT_TEST, return_code))
        if return_code != 0:
            res = self._view.askYesNoQuestion(
                _("Your graphics hardware may not be fully supported in "
                  "Ubuntu 14.04."),
                _("Running the 'unity' desktop environment is not fully "
                  "supported by your graphics hardware. You will maybe end "
                  "up in a very slow environment after the upgrade. Our "
                  "advice is to keep the LTS version for now. For more "
                  "information see "
                  "https://wiki.ubuntu.com/X/Bugs/"
                  "UpdateManagerWarningForUnity3D "
                  "Do you still want to continue with the upgrade?")
                )
            if not res:
                self.controller.abort()

    def _test_and_warn_on_i8xx(self):
        I8XX_PCI_IDS = ["8086:7121",  # i810
                        "8086:7125",  # i810e
                        "8086:1132",  # i815
                        "8086:3577",  # i830
                        "8086:2562",  # i845
                        "8086:3582",  # i855
                        "8086:2572",  # i865
                        ]
        lspci = self._get_pci_ids()
        if set(I8XX_PCI_IDS).intersection(lspci):
            res = self._view.askYesNoQuestion(
                _("Your graphics hardware may not be fully supported in "
                  "Ubuntu 12.04 LTS."),
                _("The support in Ubuntu 12.04 LTS for your Intel "
                  "graphics hardware is limited "
                  "and you may encounter problems after the upgrade. "
                  "For more information see "
                  "https://wiki.ubuntu.com/X/Bugs/UpdateManagerWarningForI8xx "
                  "Do you want to continue with the upgrade?")
                )
            if not res:
                self.controller.abort()

    def _test_and_warn_on_dropped_fglrx_support(self):
        """
        Some cards are no longer supported by fglrx. Check if that
        is the case and warn
        """
        # this is to deal with the fact that support for some of the cards
        # that fglrx used to support got dropped
        if (self._checkVideoDriver("fglrx") and
                not self._supportInModaliases("fglrx")):
            res = self._view.askYesNoQuestion(
                _("Upgrading may reduce desktop "
                  "effects, and performance in games "
                  "and other graphically intensive "
                  "programs."),
                _("This computer is currently using "
                  "the AMD 'fglrx' graphics driver. "
                  "No version of this driver is "
                  "available that works with your "
                  "hardware in Ubuntu 10.04 LTS.\n\n"
                  "Do you want to continue?"))
            if not res:
                self.controller.abort()
            # if the user wants to continue we remove the fglrx driver
            # here because its no use (no support for this card)
            removals = [
                "xorg-driver-fglrx",
                "xorg-driver-fglrx-envy",
                "fglrx-kernel-source",
                "fglrx-amdcccle",
                "xorg-driver-fglrx-dev",
                "libamdxvba1"
                ]
            logging.debug("remove %s" % ", ".join(removals))
            l = self.controller.config.getlist("Distro", "PostUpgradePurge")
            for remove in removals:
                l.append(remove)
            self.controller.config.set("Distro", "PostUpgradePurge",
                                       ",".join(l))

    def _test_and_fail_on_non_i686(self):
        """
        Test and fail if the cpu is not i686 or more or if its a newer
        CPU but does not have the cmov feature (LP: #587186)
        """
        # check on i386 only
        if self.arch == "i386":
            logging.debug("checking for i586 CPU")
            if not self._cpu_is_i686_and_has_cmov():
                logging.error("not a i686 or no cmov")
                summary = _("No i686 CPU")
                msg = _("Your system uses an i586 CPU or a CPU that does "
                        "not have the 'cmov' extension. "
                        "All packages were built with "
                        "optimizations requiring i686 as the "
                        "minimal architecture. It is not possible to "
                        "upgrade your system to a new Ubuntu release "
                        "with this hardware.")
                self._view.error(summary, msg)
                self.controller.abort()

    def _cpu_is_i686_and_has_cmov(self, cpuinfo_path="/proc/cpuinfo"):
        if not os.path.exists(cpuinfo_path):
            logging.error("cannot open %s ?!?" % cpuinfo_path)
            return True
        cpuinfo = open(cpuinfo_path).read()
        # check family
        if re.search("^cpu family\s*:\s*[345]\s*", cpuinfo, re.MULTILINE):
            logging.debug("found cpu family [345], no i686+")
            return False
        # check flags for cmov
        match = re.search("^flags\s*:\s*(.*)", cpuinfo, re.MULTILINE)
        if match:
            if not "cmov" in match.group(1).split():
                logging.debug("found flags '%s'" % match.group(1))
                logging.debug("can not find cmov in flags")
                return False
        return True

    def _test_and_fail_on_non_arm_v6(self):
        """
        Test and fail if the cpu is not a arm v6 or greater,
        from 9.10 on we do no longer support those CPUs
        """
        if self.arch == "armel":
            if not self._checkArmCPU():
                self._view.error(
                    _("No ARMv6 CPU"),
                    _("Your system uses an ARM CPU that is older "
                      "than the ARMv6 architecture. "
                      "All packages in karmic were built with "
                      "optimizations requiring ARMv6 as the "
                      "minimal architecture. It is not possible to "
                      "upgrade your system to a new Ubuntu release "
                      "with this hardware."))
                self.controller.abort()

    def _test_and_warn_if_vserver(self):
        """
        upstart and vserver environments are not a good match, warn
        if we find one
        """
        # verver test (LP: #454783), see if there is a init around
        try:
            os.kill(1, 0)
        except:
            logging.warn("no init found")
            res = self._view.askYesNoQuestion(
                _("No init available"),
                _("Your system appears to be a virtualised environment "
                  "without an init daemon, e.g. Linux-VServer. "
                  "Ubuntu 10.04 LTS cannot function within this type of "
                  "environment, requiring an update to your virtual "
                  "machine configuration first.\n\n"
                  "Are you sure you want to continue?"))
            if not res:
                self.controller.abort()
            self._view.processEvents()

    def _checkArmCPU(self):
        """
        parse /proc/cpuinfo and search for ARMv6 or greater
        """
        logging.debug("checking for ARM CPU version")
        if not os.path.exists("/proc/cpuinfo"):
            logging.error("cannot open /proc/cpuinfo ?!?")
            return False
        cpuinfo = open("/proc/cpuinfo")
        if re.search("^Processor\s*:\s*ARMv[45]", cpuinfo.read(),
                     re.MULTILINE):
            return False
        return True

    def _stopApparmor(self):
        """ /etc/init.d/apparmor stop (see bug #559433)"""
        if os.path.exists("/etc/init.d/apparmor"):
            logging.debug("/etc/init.d/apparmor stop")
            subprocess.call(["/etc/init.d/apparmor", "stop"])

    def _stopDocvertConverter(self):
        " /etc/init.d/docvert-converter stop (see bug #450569)"
        if os.path.exists("/etc/init.d/docvert-converter"):
            logging.debug("/etc/init.d/docvert-converter stop")
            subprocess.call(["/etc/init.d/docvert-converter", "stop"])

    def _killUpdateNotifier(self):
        "kill update-notifier"
        # kill update-notifier now to suppress reboot required
        if os.path.exists("/usr/bin/killall"):
            logging.debug("killing update-notifier")
            subprocess.call(["killall", "-q", "update-notifier"])

    def _killKBluetooth(self):
        """killall kblueplugd kbluetooth (riddel requested it)"""
        if os.path.exists("/usr/bin/killall"):
            logging.debug("killing kblueplugd kbluetooth4")
            subprocess.call(["killall", "-q", "kblueplugd", "kbluetooth4"])

    def _killScreensaver(self):
        """killall gnome-screensaver """
        if os.path.exists("/usr/bin/killall"):
            logging.debug("killing gnome-screensaver")
            subprocess.call(["killall", "-q", "gnome-screensaver"])

    def _pokeScreensaver(self):
        if (os.path.exists("/usr/bin/xdg-screensaver") and
                os.environ.get('DISPLAY')):
            logging.debug("setup poke timer for the scrensaver")
            cmd = "while true;"
            cmd += " do /usr/bin/xdg-screensaver reset >/dev/null 2>&1;"
            cmd += " sleep 30; done"
            try:
                self._poke = subprocess.Popen(cmd, shell=True)
                atexit.register(self._stopPokeScreensaver)
            except:
                logging.exception("failed to setup screensaver poke")

    def _stopPokeScreensaver(self):
        res = False
        if self._poke is not None:
            try:
                self._poke.terminate()
                res = self._poke.wait()
            except:
                logging.exception("failed to stop screensaver poke")
            self._poke = None
        return res

    def _removeOldApportCrashes(self):
        " remove old apport crash files and whoopsie control files "
        try:
            for ext in ['.crash', '.upload', '.uploaded']:
                for f in glob.glob("/var/crash/*%s" % ext):
                    logging.debug("removing old %s file '%s'" % (ext, f))
                    os.unlink(f)
        except Exception as e:
            logging.warning("error during unlink of old crash files (%s)" % e)

    def _checkPae(self):
        " check PAE in /proc/cpuinfo "
        # upgrade from Precise will fail if PAE is not in cpu flags
        logging.debug("_checkPae")
        pae = 0
        cpuinfo = open('/proc/cpuinfo').read()
        if re.search("^flags\s+:.* pae ", cpuinfo, re.MULTILINE):
            pae = 1
        if not pae:
            logging.error("no pae in /proc/cpuinfo")
            summary = _("PAE not enabled")
            msg = _("Your system uses a CPU that does not have PAE enabled. "
                    "Ubuntu only supports non-PAE systems up to Ubuntu "
                    "12.04. To upgrade to a later version of Ubuntu, you "
                    "must enable PAE (if this is possible) see:\n"
                    "http://help.ubuntu.com/community/EnablingPAE")
            self._view.error(summary, msg)
            self.controller.abort()

    def _checkVideoDriver(self, name):
        " check if the given driver is in use in xorg.conf "
        XORG = "/etc/X11/xorg.conf"
        if not os.path.exists(XORG):
            return False
        for line in open(XORG):
            s = line.split("#")[0].strip()
            # check for fglrx driver entry
            if (s.lower().startswith("driver") and
                    s.endswith('"%s"' % name)):
                return True
        return False

    def _applyPatches(self, patchdir="./patches"):
        """
        helper that applies the patches in patchdir. the format is
        _path_to_file.md5sum and it will apply the diff to that file if the
        md5sum matches
        """
        if not os.path.exists(patchdir):
            logging.debug("no patchdir")
            return
        for f in os.listdir(patchdir):
            # skip, not a patch file, they all end with .$md5sum
            if not "." in f:
                logging.debug("skipping '%s' (no '.')" % f)
                continue
            logging.debug("check if patch '%s' needs to be applied" % f)
            (encoded_path, md5sum, result_md5sum) = f.rsplit(".", 2)
            # FIXME: this is not clever and needs quoting support for
            #        filenames with "_" in the name
            path = encoded_path.replace("_", "/")
            logging.debug("target for '%s' is '%s' -> '%s'" % (
                f, encoded_path, path))
            # target does not exist
            if not os.path.exists(path):
                logging.debug("target '%s' does not exist" % path)
                continue
            # check the input md5sum, this is not strictly needed as patch()
            # will verify the result md5sum and discard the result if that
            # does not match but this will remove a misleading error in the
            # logs
            md5 = hashlib.md5()
            with open(path, "rb") as fd:
                md5.update(fd.read())
            if md5.hexdigest() == result_md5sum:
                logging.debug("already at target hash, skipping '%s'" % path)
                continue
            elif md5.hexdigest() != md5sum:
                logging.warn("unexpected target md5sum, skipping: '%s'" % path)
                continue
            # patchable, do it
            from .DistUpgradePatcher import patch
            try:
                patch(path, os.path.join(patchdir, f), result_md5sum)
                logging.info("applied '%s' successfully" % f)
            except Exception:
                logging.exception("ed failed for '%s'" % f)

    def _supportInModaliases(self, pkgname, lspci=None):
        """
        Check if pkgname will work on this hardware

        This helper will check with the modaliasesdir if the given
        pkg will work on this hardware (or the hardware given
        via the lspci argument)
        """
        # get lspci info (if needed)
        if not lspci:
            lspci = self._get_pci_ids()
        # get pkg
        if (not pkgname in self.controller.cache or
                not self.controller.cache[pkgname].candidate):
            logging.warn("can not find '%s' in cache")
            return False
        pkg = self.controller.cache[pkgname]
        for (module, pciid_list) in \
                self._parse_modaliases_from_pkg_header(pkg.candidate.record):
            for pciid in pciid_list:
                m = re.match("pci:v0000(.+)d0000(.+)sv.*", pciid)
                if m:
                    matchid = "%s:%s" % (m.group(1), m.group(2))
                    if matchid.lower() in lspci:
                        logging.debug("found system pciid '%s' in modaliases"
                                      % matchid)
                        return True
        logging.debug("checking for %s support in modaliases but none found"
                      % pkgname)
        return False

    def _parse_modaliases_from_pkg_header(self, pkgrecord):
        """ return a list of (module1, (pciid, ...), ...)"""
        if not "Modaliases" in pkgrecord:
            return []
        # split the string
        modules = []
        for m in pkgrecord["Modaliases"].split(")"):
            m = m.strip(", ")
            if not m:
                continue
            (module, pciids) = m.split("(")
            modules.append((module, [x.strip() for x in pciids.split(",")]))
        return modules

    def _add_extras_repository(self):
        logging.debug("_add_extras_repository")
        cache = self.controller.cache
        if not "ubuntu-extras-keyring" in cache:
            logging.debug("no ubuntu-extras-keyring, no need to add repo")
            return
        if not (cache["ubuntu-extras-keyring"].marked_install or
                cache["ubuntu-extras-keyring"].installed):
            logging.debug("ubuntu-extras-keyring not installed/marked_install")
            return
        try:
            import aptsources.sourceslist
            sources = aptsources.sourceslist.SourcesList()
            for entry in sources:
                if "extras.ubuntu.com" in entry.uri:
                    logging.debug("found extras.ubuntu.com, no need to add it")
                    break
            else:
                logging.info("no extras.ubuntu.com, adding it to sources.list")
                sources.add("deb", "http://extras.ubuntu.com/ubuntu",
                            self.controller.toDist, ["main"],
                            "Third party developers repository")
                sources.save()
        except:
            logging.exception("error adding extras.ubuntu.com")

    def _gutenprint_fixup(self):
        """ foomatic-db-gutenprint get removed during the upgrade,
            replace it with the compressed ijsgutenprint-ppds
            (context is foomatic-db vs foomatic-db-compressed-ppds)
        """
        try:
            cache = self.controller.cache
            if ("foomatic-db-gutenprint" in cache and
                    cache["foomatic-db-gutenprint"].marked_delete and
                    "ijsgutenprint-ppds" in cache):
                logging.info("installing ijsgutenprint-ppds")
                cache.mark_install(
                    "ijsgutenprint-ppds",
                    "foomatic-db-gutenprint -> ijsgutenprint-ppds rule")
        except:
            logging.exception("_gutenprint_fixup failed")

    def _enable_multiarch(self, foreign_arch="i386"):
        """ enable multiarch via /etc/dpkg/dpkg.cfg.d/multiarch """
        cfg = "/etc/dpkg/dpkg.cfg.d/multiarch"
        if not os.path.exists(cfg):
            try:
                os.makedirs("/etc/dpkg/dpkg.cfg.d/")
            except OSError:
                pass
            open(cfg, "w").write("foreign-architecture %s\n" % foreign_arch)

    def _add_kdegames_card_extra_if_installed(self):
        """ test if kdegames-card-data is installed and if so,
            add kdegames-card-data-extra so that users do not
            loose functionality (LP: #745396)
        """
        try:
            cache = self.controller.cache
            if not ("kdegames-card-data" in cache or
                    "kdegames-card-data-extra" in cache):
                return
            if (cache["kdegames-card-data"].is_installed or
                    cache["kdegames-card-data"].marked_install):
                cache.mark_install(
                    "kdegames-card-data-extra",
                    "kdegames-card-data -> k-c-d-extra transition")
        except:
            logging.exception("_add_kdegames_card_extra_if_installed failed")

    def ensure_recommends_are_installed_on_desktops(self):
        """ ensure that on a desktop install recommends are installed
            (LP: #759262)
        """
        import apt
        if not self.controller.serverMode:
            if not apt.apt_pkg.config.find_b("Apt::Install-Recommends"):
                msg = "Apt::Install-Recommends was disabled,"
                msg += " enabling it just for the upgrade"
                logging.warn(msg)
                apt.apt_pkg.config.set("Apt::Install-Recommends", "1")
