#!/usr/bin/env python3
# Copyright 2015 Canonical, Ltd.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import argparse
import logging
import os
import fcntl
import subprocess
import sys
import time

from cloudinit import atomic_helper, safeyaml, stages

from subiquitycore.log import setup_logger
from subiquitycore.utils import run_command

from .common import (
    LOGDIR,
    setup_environment,
    )
from .server import make_server_args_parser


class ClickAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        namespace.scripts.append("c(" + repr(values) + ")")


def make_client_args_parser():
    parser = argparse.ArgumentParser(
        description='SUbiquity - Ubiquity for Servers',
        prog='subiquity')
    try:
        ascii_default = os.ttyname(0) == "/dev/ttysclp0"
    except OSError:
        ascii_default = False
    parser.set_defaults(ascii=ascii_default)
    parser.add_argument('--dry-run', action='store_true',
                        dest='dry_run',
                        help='menu-only, do not call installer function')
    parser.add_argument('--socket')
    parser.add_argument('--serial', action='store_true',
                        dest='run_on_serial',
                        help='Run the installer over serial console.')
    parser.add_argument('--ssh', action='store_true',
                        dest='ssh',
                        help='Print ssh login details')
    parser.add_argument('--ascii', action='store_true',
                        dest='ascii',
                        help='Run the installer in ascii mode.')
    parser.add_argument('--unicode', action='store_false',
                        dest='ascii',
                        help='Run the installer in unicode mode.')
    parser.add_argument('--machine-config', metavar='CONFIG',
                        dest='machine_config',
                        help="Don't Probe. Use probe data file")
    parser.add_argument('--bootloader',
                        choices=['none', 'bios', 'prep', 'uefi'],
                        help='Override style of bootloader to use')
    parser.add_argument('--screens', action='append', dest='screens',
                        default=[])
    parser.add_argument('--script', metavar="SCRIPT", action='append',
                        dest='scripts', default=[],
                        help=('Execute SCRIPT in a namespace containing view '
                              'helpers and "ui"'))
    parser.add_argument('--click', metavar="PAT", action=ClickAction,
                        help='Synthesize a click on a button matching PAT')
    parser.add_argument('--answers')
    parser.add_argument('--autoinstall', action='store')
    with open('/proc/cmdline') as fp:
        cmdline = fp.read()
    parser.add_argument('--kernel-cmdline', action='store', default=cmdline)
    parser.add_argument('--source', default=[], action='append',
                        dest='sources', metavar='URL',
                        help='install from url instead of default.')
    parser.add_argument(
        '--snaps-from-examples', action='store_const', const=True,
        dest="snaps_from_examples",
        help=("Load snap details from examples/snaps instead of store. "
              "Default in dry-run mode.  "
              "See examples/snaps/README.md for more."))
    parser.add_argument(
        '--no-snaps-from-examples', action='store_const', const=False,
        dest="snaps_from_examples",
        help=("Load snap details from store instead of examples. "
              "Default in when not in dry-run mode.  "
              "See examples/snaps/README.md for more."))
    parser.add_argument(
        '--snap-section', action='store', default='server',
        help=("Show snaps from this section of the store in the snap "
              "list screen."))
    return parser


AUTO_ANSWERS_FILE = "/subiquity_config/answers.yaml"


def main():
    setup_environment()
    # setup_environment sets $APPORT_DATA_DIR which must be set before
    # apport is imported, which is done by this import:
    from subiquity.core import Subiquity
    parser = make_client_args_parser()
    args = sys.argv[1:]
    server_proc = None
    if '--dry-run' in args:
        opts, unknown = parser.parse_known_args(args)
        if opts.socket is None:
            os.makedirs('.subiquity', exist_ok=True)
            sock_path = '.subiquity/socket'
            opts.socket = sock_path
            server_args = ['--dry-run', '--socket=' + sock_path] + unknown
            server_parser = make_server_args_parser()
            server_parser.parse_args(server_args)  # just to check
            server_output = open('.subiquity/server-output', 'w')
            server_cmd = [sys.executable, '-m', 'subiquity.cmd.server'] + \
                server_args
            server_proc = subprocess.Popen(
                server_cmd, stdout=server_output, stderr=subprocess.STDOUT)
            print("running server pid {}".format(server_proc.pid))
        else:
            opts = parser.parse_args(args)
    else:
        opts = parser.parse_args(args)
        if opts.socket is None:
            opts.socket = '/run/subiquity/socket'
    os.makedirs(os.path.basename(opts.socket), exist_ok=True)
    logdir = LOGDIR
    if opts.dry_run:
        if opts.snaps_from_examples is None:
            opts.snaps_from_examples = True
        logdir = ".subiquity"
    logfiles = setup_logger(dir=logdir, base='subiquity')

    logger = logging.getLogger('subiquity')
    version = os.environ.get("SNAP_REVISION", "unknown")
    logger.info("Starting Subiquity revision {}".format(version))
    logger.info("Arguments passed: {}".format(sys.argv))

    if not opts.dry_run:
        ci_start = time.time()
        status_txt = run_command(["cloud-init", "status", "--wait"]).stdout
        logger.debug("waited %ss for cloud-init", time.time() - ci_start)
        if "status: done" in status_txt:
            logger.debug("loading cloud config")
            init = stages.Init()
            init.read_cfg()
            init.fetch(existing="trust")
            cloud = init.cloudify()
            autoinstall_path = '/autoinstall.yaml'
            if 'autoinstall' in cloud.cfg:
                if not os.path.exists(autoinstall_path):
                    atomic_helper.write_file(
                        autoinstall_path,
                        safeyaml.dumps(
                            cloud.cfg['autoinstall']).encode('utf-8'),
                        mode=0o600)
            if os.path.exists(autoinstall_path):
                opts.autoinstall = autoinstall_path
        else:
            logger.debug(
                "cloud-init status: %r, assumed disabled",
                status_txt)

    block_log_dir = os.path.join(logdir, "block")
    os.makedirs(block_log_dir, exist_ok=True)
    handler = logging.FileHandler(os.path.join(block_log_dir, 'discover.log'))
    handler.setLevel('DEBUG')
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(name)s:%(lineno)d %(message)s"))
    logging.getLogger('probert').addHandler(handler)
    handler.addFilter(lambda rec: rec.name != 'probert.network')
    logging.getLogger('curtin').addHandler(handler)
    logging.getLogger('block-discover').addHandler(handler)

    if opts.ssh:
        from subiquity.ui.views.help import (
            ssh_help_texts, get_installer_password)
        from subiquitycore.ssh import get_ips_standalone
        texts = ssh_help_texts(
            get_ips_standalone(), get_installer_password(opts.dry_run))
        for line in texts:
            if hasattr(line, 'text'):
                if line.text.startswith('installer@'):
                    print(' ' * 4 + line.text)
                else:
                    print(line.text)
            else:
                print(line)
        return 0

    if opts.answers is None and os.path.exists(AUTO_ANSWERS_FILE):
        logger.debug("Autoloading answers from %s", AUTO_ANSWERS_FILE)
        opts.answers = AUTO_ANSWERS_FILE

    if opts.answers:
        opts.answers = open(opts.answers)
        try:
            fcntl.flock(opts.answers, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            logger.exception(
                'Failed to lock auto answers file, proceding without it.')
            opts.answers.close()
            opts.answers = None

    subiquity_interface = Subiquity(opts, block_log_dir)
    subiquity_interface.server_proc = server_proc

    subiquity_interface.note_file_for_apport(
        "InstallerLog", logfiles['debug'])
    subiquity_interface.note_file_for_apport(
        "InstallerLogInfo", logfiles['info'])

    try:
        subiquity_interface.run()
    finally:
        if server_proc is not None:
            print('killing server {}'.format(server_proc.pid))
            server_proc.send_signal(2)
            server_proc.wait()


if __name__ == '__main__':
    sys.exit(main())
