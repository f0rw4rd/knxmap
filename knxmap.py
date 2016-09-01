#!/usr/bin/env python3
import sys
import os
import argparse
import logging

from libknxmap import KnxMap, Targets, KnxTargets

# asyncio requires at least Python 3.3
if sys.version_info.major < 3 or \
    (sys.version_info.major > 2 and
    sys.version_info.minor < 3):
    print('At least Python version 3.3 is required to run this script!')
    sys.exit(1)
try:
    # Python 3.4 ships with asyncio in the standard libraries. Users of Python 3.3
    # need to install it, e.g.: pip install asyncio
    import asyncio
except ImportError:
    print('Please install the asyncio module!')
    sys.exit(1)

LOGGER = logging.getLogger(__name__)

# TODO: create proper arguments
# TODO: add subcommands for scanning modes?
# TODO: add dump-file argument for monitoring modes
ARGS = argparse.ArgumentParser(description="KNXnet/IP network and bus mapper")
# General options
ARGS.add_argument(
    'targets', nargs='*',
    default=[], help='Target hostnames/IP addresses')
ARGS.add_argument(
    '-p', '--port', action='store', dest='port', type=int,
    default=3671, help='UDP port to be scanned')
ARGS.add_argument(
    '--workers', action='store', type=int, metavar='N',
    default=30, help='Limit concurrent workers')
# Search options
ARGS.add_argument(
    '-i', '--interface', action='store', dest='iface',
    default=None, help='Interface to be used')
ARGS.add_argument(
    '--search', action='store_true', dest='search_mode',
    default=False, help='Find local KNX gateways via search requests')
ARGS.add_argument(
    '--search-timeout', action='store', dest='search_timeout', type=int,
    default=5, help='Timeout in seconds for multicast responses')
# KNX description request options
ARGS.add_argument(
    '--desc-timeout', action='store', dest='desc_timeout', type=int,
    default=2, help='Timeout in seconds for unicast description responses')
ARGS.add_argument(
    '--desc-retries', action='store', dest='desc_retries', type=int,
    default=3, help='Count of retries for description requests')
# Bus options
ARGS.add_argument(
    '--bus-targets', action='store', dest='bus_targets',
    default=None, help='Bus target range')
ARGS.add_argument(
    '--bus-info', action='store_true', dest='bus_info',
    default=False, help='Try to extract information from bus devices')
# Monitor options
ARGS.add_argument(
    '--bus-monitor', action='store_true', dest='bus_monitor_mode',
    default=False, help='Monitor all bus messages via KNXnet/IP gateway')
ARGS.add_argument(
    '--group-monitor', action='store_true', dest='group_monitor_mode',
    default=False, help='Monitor group bus messages via KNXnet/IP gateway')
# Misc options
ARGS.add_argument(
    '-v', '--verbose', action='count', dest='level',
    default=2, help='Verbose logging (repeat for more verbose)')
ARGS.add_argument(
    '-q', '--quiet', action='store_const', const=0, dest='level',
    default=2, help='Only log errors')

ARGS.add_argument(
    '--bruteforce-key', action='store_true', dest='bruteforce_key',
    default=False, help='Bruteforce the access control key')
ARGS.add_argument(
    '--auth-key', action='store', dest='auth_key', type=int,
    default=0xffffffff, help='Authorize key for System 2 and System 7 devices')

ARGS.add_argument(
    '--group-write', action='store', dest='group_write_value',
    default=False, help='Value to write to the group address')
ARGS.add_argument(
    '--group-address', action='store', dest='group_write_address',
    default=False, help='A KNX group address')
ARGS.add_argument(
    '--routing', action='store_true', dest='routing',
    default=False, help='Use Routing instead of Tunnelling')


def main():
    args = ARGS.parse_args()
    if not args.targets and not args.search_mode:
        ARGS.print_help()
        sys.exit(1)

    targets = Targets(args.targets, args.port)
    bus_targets = KnxTargets(args.bus_targets)
    levels = [logging.ERROR, logging.WARN, logging.INFO, logging.DEBUG]
    format = '[%(filename)s:%(lineno)s - %(funcName)20s() ] %(message)s' if args.level > 2 else '%(message)s'
    logging.basicConfig(level=levels[min(args.level, len(levels)-1)], format=format)
    loop = asyncio.get_event_loop()

    if args.search_mode:
        if not args.iface:
            LOGGER.error('--search option requires -i/--interface argument')
            sys.exit(1)

        if os.geteuid() != 0:
            LOGGER.error('-i/--interface option requires superuser privileges')
            sys.exit(1)
    else:
        LOGGER.info('Scanning {} target(s)'.format(len(targets.targets)))

    scanner = KnxScanner(targets=targets.targets, max_workers=args.workers)

    try:
        if args.group_write_value and args.group_write_address:
            loop.run_until_complete(scanner.group_writer(
                target=args.group_write_address,
                value=args.group_write_value,
                desc_timeout=args.desc_timeout,
                desc_retries=args.desc_retries,
                iface=args.iface,
                routing=args.routing))
        else:
            loop.run_until_complete(scanner.scan(
                search_mode=args.search_mode,
                search_timeout=args.search_timeout,
                desc_timeout=args.desc_timeout,
                desc_retries=args.desc_retries,
                bus_targets=bus_targets.targets,
                bus_info=args.bus_info,
                bus_monitor_mode=args.bus_monitor_mode,
                group_monitor_mode=args.group_monitor_mode,
                iface=args.iface,
                bruteforce_key=args.bruteforce_key,
                auth_key=args.auth_key))
    except KeyboardInterrupt:
        for t in asyncio.Task.all_tasks():
            t.cancel()
        loop.run_forever()

        if scanner.bus_protocols:
            # Make sure to send a DISCONNECT_REQUEST when the bus monitor will be closed
            for p in scanner.bus_protocols:
                p.knx_tunnel_disconnect()
    finally:
        loop.close()


if __name__ == '__main__':
    main()
