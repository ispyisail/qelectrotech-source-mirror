#!/usr/bin/env python3
"""A virtual 3D mouse on Linux, through /dev/uhid, for testing QET's hidapi
backend without a device.

    sudo python3 fake-spacemouse.py --fifo /tmp/fake.fifo [--absolute]

The kernel sees a real USB HID device (3Dconnexion vendor id, multi-axis
usage), so it gets a /dev/hidrawN node that hidapi finds and opens like
any other. Events are read from the FIFO in the same 32-byte records
tools/spnav-shim/send.py writes, so the same test steps can drive either
backend:

    {1, x, y, z, rx, ry, rz, 0}  motion  -> report 1 (x,y,z) + report 2 (rx,ry,rz)
    {2, button, ...}             press   -> report 3 (button bitmask)
    {3, button, ...}             release -> report 3

The hidraw node is made readable by everyone (it is a test device), so QET
does not need to run as root. Ctrl-C or SIGTERM removes the device.
"""
import argparse
import glob
import os
import signal
import struct
import sys
import time

UHID_DESTROY, UHID_CREATE2, UHID_INPUT2 = 1, 11, 12
EVENT_SIZE = 4 + 4372          # sizeof(struct uhid_event)
BUS_USB = 0x03
NAME = 'QET fake SpaceMouse'


def descriptor(absolute):
    """Report 1: X Y Z, report 2: Rx Ry Rz, 16-bit, -350..350; report 3: 16 buttons."""
    flags = '8102' if absolute else '8106'
    return bytes.fromhex(
        '05010908a101'
        'a100' '8501' '16a2fe' '265e01' '093009310932' '7510' '9503' + flags + 'c0'
        'a100' '8502' '093309340935' '7510' '9503' + flags + 'c0'
        'a102' '8503' '0509' '1901' '2910' '1500' '2501' '7501' '9510' '8102' 'c0'
        'c0')


def event(kind, payload=b''):
    return (struct.pack('<I', kind) + payload).ljust(EVENT_SIZE, b'\0')


def create(fd, rd, vendor, product):
    payload = struct.pack('<128s64s64sHHIIII', NAME.encode(), b'qet-fake', b'',
                          len(rd), BUS_USB, vendor, product, 1, 0) + rd.ljust(4096, b'\0')
    os.write(fd, event(UHID_CREATE2, payload))


def send(fd, report):
    os.write(fd, event(UHID_INPUT2, struct.pack('<H', len(report)) + report.ljust(4096, b'\0')))


def hidraw_node(timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        for sysdir in glob.glob('/sys/class/hidraw/hidraw*'):
            try:
                with open(os.path.join(sysdir, 'device', 'uevent')) as f:
                    if 'HID_NAME=' + NAME in f.read():
                        return '/dev/' + os.path.basename(sysdir)
            except OSError:
                pass
        time.sleep(0.1)
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--fifo', required=True, help='FIFO to read event records from')
    ap.add_argument('--absolute', action='store_true', help='declare absolute axes (default relative)')
    ap.add_argument('--vendor', type=lambda v: int(v, 16), default=0x256f)
    ap.add_argument('--product', type=lambda v: int(v, 16), default=0xc635)
    args = ap.parse_args()

    if not os.path.exists(args.fifo):
        os.mkfifo(args.fifo)
    os.chmod(args.fifo, 0o666)

    uhid = os.open('/dev/uhid', os.O_RDWR)
    create(uhid, descriptor(args.absolute), args.vendor, args.product)

    def destroy(*_):
        os.write(uhid, event(UHID_DESTROY))
        sys.exit(0)
    signal.signal(signal.SIGTERM, destroy)
    signal.signal(signal.SIGINT, destroy)

    node = hidraw_node()
    if not node:
        print('the kernel created no hidraw node', file=sys.stderr)
        destroy()
    os.chmod(node, 0o666)
    print('%s ready: %s (%04x:%04x, %s axes)' % (NAME, node, args.vendor, args.product,
          'absolute' if args.absolute else 'relative'), flush=True)

    fifo = os.open(args.fifo, os.O_RDONLY)
    keep_open = os.open(args.fifo, os.O_WRONLY)   # never see EOF between senders
    buttons = 0
    while True:
        rec = os.read(fifo, 32)
        if len(rec) != 32:
            continue
        kind, *v = struct.unpack('8i', rec)
        if kind == 1:
            send(uhid, b'\x01' + struct.pack('<3h', *v[0:3]))
            send(uhid, b'\x02' + struct.pack('<3h', *v[3:6]))
        elif kind in (2, 3) and 0 <= v[0] < 16:
            buttons = buttons | (1 << v[0]) if kind == 2 else buttons & ~(1 << v[0])
            send(uhid, b'\x03' + struct.pack('<H', buttons))


if __name__ == '__main__':
    main()
