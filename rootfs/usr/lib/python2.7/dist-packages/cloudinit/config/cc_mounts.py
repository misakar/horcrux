# vi: ts=4 expandtab
#
#    Copyright (C) 2009-2010 Canonical Ltd.
#    Copyright (C) 2012 Hewlett-Packard Development Company, L.P.
#
#    Author: Scott Moser <scott.moser@canonical.com>
#    Author: Juerg Haefliger <juerg.haefliger@hp.com>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License version 3, as
#    published by the Free Software Foundation.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.

from string import whitespace  # pylint: disable=W0402

import logging
import os.path
import re

from cloudinit import type_utils
from cloudinit import util

# Shortname matches 'sda', 'sda1', 'xvda', 'hda', 'sdb', xvdb, vda, vdd1, sr0
DEVICE_NAME_FILTER = r"^([x]{0,1}[shv]d[a-z][0-9]*|sr[0-9]+)$"
DEVICE_NAME_RE = re.compile(DEVICE_NAME_FILTER)
WS = re.compile("[%s]+" % (whitespace))
FSTAB_PATH = "/etc/fstab"

LOG = logging.getLogger(__name__)


def is_meta_device_name(name):
    # return true if this is a metadata service name
    if name in ["ami", "root", "swap"]:
        return True
    # names 'ephemeral0' or 'ephemeral1'
    # 'ebs[0-9]' appears when '--block-device-mapping sdf=snap-d4d90bbc'
    for enumname in ("ephemeral", "ebs"):
        if name.startswith(enumname) and name.find(":") == -1:
            return True
    return False


def _get_nth_partition_for_device(device_path, partition_number):
    potential_suffixes = [str(partition_number), 'p%s' % (partition_number,),
                          '-part%s' % (partition_number,)]
    for suffix in potential_suffixes:
        potential_partition_device = '%s%s' % (device_path, suffix)
        if os.path.exists(potential_partition_device):
            return potential_partition_device
    return None


def _is_block_device(device_path, partition_path=None):
    device_name = os.path.realpath(device_path).split('/')[-1]
    sys_path = os.path.join('/sys/block/', device_name)
    if partition_path is not None:
        sys_path = os.path.join(
            sys_path, os.path.realpath(partition_path).split('/')[-1])
    return os.path.exists(sys_path)


def sanitize_devname(startname, transformer, log):
    log.debug("Attempting to determine the real name of %s", startname)

    # workaround, allow user to specify 'ephemeral'
    # rather than more ec2 correct 'ephemeral0'
    devname = startname
    if devname == "ephemeral":
        devname = "ephemeral0"
        log.debug("Adjusted mount option from ephemeral to ephemeral0")

    device_path, partition_number = util.expand_dotted_devname(devname)

    if is_meta_device_name(device_path):
        orig = device_path
        device_path = transformer(device_path)
        if not device_path:
            return None
        if not device_path.startswith("/"):
            device_path = "/dev/%s" % (device_path,)
        log.debug("Mapped metadata name %s to %s", orig, device_path)
    else:
        if DEVICE_NAME_RE.match(startname):
            device_path = "/dev/%s" % (device_path,)

    partition_path = None
    if partition_number is None:
        partition_path = _get_nth_partition_for_device(device_path, 1)
    else:
        partition_path = _get_nth_partition_for_device(device_path,
                                                       partition_number)
        if partition_path is None:
            return None

    if _is_block_device(device_path, partition_path):
        if partition_path is not None:
            return partition_path
        return device_path
    return None


def handle(_name, cfg, cloud, log, _args):
    # fs_spec, fs_file, fs_vfstype, fs_mntops, fs-freq, fs_passno
    defvals = [None, None, "auto", "defaults,nobootwait", "0", "2"]
    defvals = cfg.get("mount_default_fields", defvals)

    # these are our default set of mounts
    defmnts = [["ephemeral0", "/mnt", "auto", defvals[3], "0", "2"],
               ["swap", "none", "swap", "sw", "0", "0"]]

    cfgmnt = []
    if "mounts" in cfg:
        cfgmnt = cfg["mounts"]

    for i in range(len(cfgmnt)):
        # skip something that wasn't a list
        if not isinstance(cfgmnt[i], list):
            log.warn("Mount option %s not a list, got a %s instead",
                     (i + 1), type_utils.obj_name(cfgmnt[i]))
            continue

        start = str(cfgmnt[i][0])
        sanitized = sanitize_devname(start, cloud.device_name_to_device, log)
        if sanitized is None:
            log.debug("Ignorming nonexistant named mount %s", start)
            continue

        if sanitized != start:
            log.debug("changed %s => %s" % (start, sanitized))
        cfgmnt[i][0] = sanitized

        # in case the user did not quote a field (likely fs-freq, fs_passno)
        # but do not convert None to 'None' (LP: #898365)
        for j in range(len(cfgmnt[i])):
            if cfgmnt[i][j] is None:
                continue
            else:
                cfgmnt[i][j] = str(cfgmnt[i][j])

    for i in range(len(cfgmnt)):
        # fill in values with defaults from defvals above
        for j in range(len(defvals)):
            if len(cfgmnt[i]) <= j:
                cfgmnt[i].append(defvals[j])
            elif cfgmnt[i][j] is None:
                cfgmnt[i][j] = defvals[j]

        # if the second entry in the list is 'None' this
        # clears all previous entries of that same 'fs_spec'
        # (fs_spec is the first field in /etc/fstab, ie, that device)
        if cfgmnt[i][1] is None:
            for j in range(i):
                if cfgmnt[j][0] == cfgmnt[i][0]:
                    cfgmnt[j][1] = None

    # for each of the "default" mounts, add them only if no other
    # entry has the same device name
    for defmnt in defmnts:
        start = defmnt[0]
        sanitized = sanitize_devname(start, cloud.device_name_to_device, log)
        if sanitized is None:
            log.debug("Ignoring nonexistant default named mount %s", start)
            continue
        if sanitized != start:
            log.debug("changed default device %s => %s" % (start, sanitized))
        defmnt[0] = sanitized

        cfgmnt_has = False
        for cfgm in cfgmnt:
            if cfgm[0] == defmnt[0]:
                cfgmnt_has = True
                break

        if cfgmnt_has:
            log.debug(("Not including %s, already"
                       " previously included"), start)
            continue
        cfgmnt.append(defmnt)

    # now, each entry in the cfgmnt list has all fstab values
    # if the second field is None (not the string, the value) we skip it
    actlist = []
    for x in cfgmnt:
        if x[1] is None:
            log.debug("Skipping non-existent device named %s", x[0])
        else:
            actlist.append(x)

    if len(actlist) == 0:
        log.debug("No modifications to fstab needed.")
        return

    comment = "comment=cloudconfig"
    cc_lines = []
    needswap = False
    dirs = []
    for line in actlist:
        # write 'comment' in the fs_mntops, entry,  claiming this
        line[3] = "%s,%s" % (line[3], comment)
        if line[2] == "swap":
            needswap = True
        if line[1].startswith("/"):
            dirs.append(line[1])
        cc_lines.append('\t'.join(line))

    fstab_lines = []
    for line in util.load_file(FSTAB_PATH).splitlines():
        try:
            toks = WS.split(line)
            if toks[3].find(comment) != -1:
                continue
        except:
            pass
        fstab_lines.append(line)

    fstab_lines.extend(cc_lines)
    contents = "%s\n" % ('\n'.join(fstab_lines))
    util.write_file(FSTAB_PATH, contents)

    if needswap:
        try:
            util.subp(("swapon", "-a"))
        except:
            util.logexc(log, "Activating swap via 'swapon -a' failed")

    for d in dirs:
        try:
            util.ensure_dir(d)
        except:
            util.logexc(log, "Failed to make '%s' config-mount", d)

    try:
        util.subp(("mount", "-a"))
    except:
        util.logexc(log, "Activating mounts via 'mount -a' failed")
