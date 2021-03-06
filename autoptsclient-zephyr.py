#!/usr/bin/env python

#
# auto-pts - The Bluetooth PTS Automation Framework
#
# Copyright (c) 2017, Intel Corporation.
#
# This program is free software; you can redistribute it and/or modify it
# under the terms and conditions of the GNU General Public License,
# version 2, as published by the Free Software Foundation.
#
# This program is distributed in the hope it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for
# more details.
#

"""Zephyr auto PTS client"""

import os
import sys
import argparse
from distutils.spawn import find_executable

import autoptsclient_common as autoptsclient
import ptsprojects.zephyr as autoprojects
import ptsprojects.stack as stack
from pybtp import btp
from ptsprojects.zephyr.iutctl import get_iut


def check_args(args):
    """Sanity check command line arguments"""

    qemu_bin = autoprojects.iutctl.QEMU_BIN
    tty_file = args.tty_file
    kernel_image = args.kernel_image
    ip_addr = args.ip_addr

    if not ip_addr:
        sys.exit("Server IP address not specified!")

    if tty_file:
        if (not tty_file.startswith("/dev/tty") and
                not tty_file.startswith("/dev/pts")):
            sys.exit("%s is not a TTY file!" % repr(tty_file))
        if not os.path.exists(tty_file):
            sys.exit("%s TTY file does not exist!" % repr(tty_file))
    else:  # no TTY - will run DUT in QEMU
        if not find_executable(qemu_bin):
            sys.exit("%s is needed but not found!" % (qemu_bin,))

    if not os.path.isfile(kernel_image):
        sys.exit("kernel_image %s is not a file!" % repr(kernel_image))


def parse_args():
    """Parses command line arguments and options"""

    arg_parser = argparse.ArgumentParser(
        description="PTS automation client")

    arg_parser.add_argument("-i", "--ip_addr", nargs="+",
                            help="IP address of the PTS automation servers")

    arg_parser.add_argument("-l", "--local_addr", default=None,
                            help="Local IP address of PTS automation client")

    arg_parser.add_argument("workspace",
                            help="Path to PTS workspace file to use for "
                            "testing. It should have pqw6 extension. "
                            "The file should be located on the "
                            "Windows machine, where the PTS "
                            "automation server is running. It is also "
                            "possible to use workspace provided with "
                            "the auto-pts, in that case this arguments "
                            "must be set to one of the  following: "
                            "zephyr-hci")

    # If DUT is QEMU kernel_image is passed to QEMU. If DUT is Arduino101 board
    # kernel_image helps locate openocd.cfg needed by the openocd reset command
    arg_parser.add_argument("kernel_image",
                            help="Zephyr OS kernel image to be used for "
                            "testing. Normally a zephyr.elf file.")

    arg_parser.add_argument("-t", "--tty-file",
                            help="If TTY is specified, BTP communication "
                            "with Zephyr OS running on hardware will "
                            "be done over this TTY. Hence, QEMU will "
                            "not be used.")

    arg_parser.add_argument("-a", "--bd-addr",
                            help="Bluetooth device address of the IUT")

    arg_parser.add_argument("-d", "--debug-logs", dest="enable_max_logs",
                            action='store_true', default=False,
                            help="Enable the PTS maximum logging. Equivalent "
                            "to running test case in PTS GUI using "
                            "'Run (Debug Logs)'")

    board_names = autoprojects.iutctl.Board.names
    arg_parser.add_argument("-b", "--board",
                            help="Used DUT board. This option is used to "
                            "select DUT reset command that is run before "
                            "each test case. If board is not specified DUT "
                            "will not be reset. Supported boards: %s. " %
                            (", ".join(board_names,),), choices=board_names)

    arg_parser.add_argument("-c", "--test-cases", nargs='+',
                            help="Names of test cases to run. Groups of test "
                            "cases can be specified by profile names: "
                            "GATT, GATTS, GATTC, GAP, L2CAP, RFCOMM, SM, MESH")

    arg_parser.add_argument("-e", "--excluded", nargs='+',
                            help="Names of test cases to exclude. Groups of "
                            "test cases can be specified by profile names: "
                            "GATT, GATTS, GATTC, GAP, L2CAP, SM, MESH")

    arg_parser.add_argument("-r", "--retry", type=int, default=0,
                            help="Repeat test if failed. Parameter specifies "
                                 "maximum repeat count per test")

    # Hidden option to save test cases data in TestCase.db
    arg_parser.add_argument("-s", "--store", action="store_true",
                            default=False, help=argparse.SUPPRESS)

    args = arg_parser.parse_args()

    check_args(args)

    return args


def main():
    """Main."""
    if os.geteuid() == 0:  # root privileges are not needed
        sys.exit("Please do not run this program as root.")

    args = parse_args()

    if args.store:
        tc_db_table_name = "zephyr_" + str(args.board)
    else:
        tc_db_table_name = None

    callback_thread = autoptsclient.init_core()

    ptses = []
    for ip in args.ip_addr:
        ptses.append(autoptsclient.init_pts(ip, args.workspace, args.bd_addr,
                                            args.enable_max_logs,
                                            callback_thread, tc_db_table_name,
                                            args.local_addr))

    btp.init(get_iut)
    autoprojects.iutctl.init(args.kernel_image, args.tty_file, args.board)

    stack.init_stack()
    stack_inst = stack.get_stack()
    stack_inst.synch_init(callback_thread.set_pending_response,
                          callback_thread.clear_pending_responses)

    test_cases = autoprojects.gap.test_cases(ptses[0])
    test_cases += autoprojects.gatt.test_cases(ptses[0])
    test_cases += autoprojects.sm.test_cases(ptses[0])
    test_cases += autoprojects.l2cap.test_cases(ptses[0])
    if len(ptses) >= 2:
        mesh_test_cases, additional_mesh_test_cases \
            = autoprojects.mesh.test_cases(ptses)
        test_cases += mesh_test_cases
        additional_test_cases = additional_mesh_test_cases
    else:
        additional_test_cases = []

    if args.test_cases or args.excluded:
        test_cases = autoptsclient.get_test_cases_subset(
            test_cases, args.test_cases, args.excluded)

    autoptsclient.run_test_cases(ptses, test_cases, additional_test_cases,
                                 args.retry)

    autoprojects.iutctl.cleanup()

    print "\nBye!"
    sys.stdout.flush()

    for pts in ptses:
        pts.unregister_xmlrpc_ptscallback()

    # not the cleanest but the easiest way to exit the server thread
    os._exit(0)


if __name__ == "__main__":

    # os._exit: not the cleanest but the easiest way to exit the server thread
    try:
        main()

    except KeyboardInterrupt:  # Ctrl-C
        os._exit(14)

    # SystemExit is thrown in arg_parser.parse_args and in sys.exit
    except SystemExit:
        raise  # let the default handlers do the work

    except BaseException:
        import traceback
        traceback.print_exc()
        os._exit(16)
