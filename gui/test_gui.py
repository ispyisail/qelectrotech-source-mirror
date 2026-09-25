#!/usr/bin/env python3
"""End-to-end test of SpaceMouse Check on Linux, against the virtual uhid
3D mouse (tools/hid-capture/fake-spacemouse.py). Needs passwordless sudo
and Xvfb.

    python3 test_gui.py [app command...]    default: python3 spacemouse_check.py

Runs the app twice, with --auto: once with the device readable (direct),
once with it root-only (the pkexec route, with `sudo -n` standing in for
the password prompt). Each time it moves the cap during the movement
check, pushes right during `right` and presses a button during `buttons`,
then checks the saved report put each one in the right step.
"""
import json
import os
import struct
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FAKE = next(p for p in (os.path.join(HERE, 'hid-capture', 'fake-spacemouse.py'),
                        os.path.join(HERE, '..', 'hid-capture', 'fake-spacemouse.py')) if os.path.exists(p))


def event(fifo, kind, *values):
    values = list(values) + [0] * (7 - len(values))
    fifo.write(struct.pack('8i', kind, *values))
    fifo.flush()


def run(app, fifo, node, elevated, out):
    env = dict(os.environ)
    if elevated:
        subprocess.run(['sudo', '-n', 'chmod', '600', node], check=True)
        env['SPACEMOUSE_CHECK_ELEVATE'] = 'sudo -n'
    else:
        subprocess.run(['sudo', '-n', 'chmod', '666', node], check=True)
    proc = subprocess.Popen(['xvfb-run', '-a'] + app + ['--auto', '--save-to', out],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    step = None
    lines = []
    for line in proc.stdout:
        line = line.rstrip()
        lines.append(line)
        if line.startswith('STEP '):
            step = line[5:]
        elif line == 'RECORDING':
            time.sleep(0.5)
            if step.startswith('Move, push and twist'):
                event(fifo, 1, 0, 0, 120)
            elif step.startswith('Push the cap to the RIGHT'):
                event(fifo, 1, 300)
            elif step.startswith('Press each button'):
                event(fifo, 2, 1)
                time.sleep(0.3)
                event(fifo, 3, 1)
    proc.wait(timeout=30)
    return lines


def check(out):
    d = json.load(open(out))
    steps = {s['step']: s['reports'] for s in d['steps']}
    problems = []
    if not d.get('move_test_reports'):
        problems.append('movement check got nothing')
    if not any(r[1].startswith('012c01') for r in steps.get('right', [])):
        problems.append('the push right is not in `right`')
    for key, reports in steps.items():
        if key not in ('right', 'buttons') and reports:
            problems.append('stray reports in `%s`' % key)
    if not any(r[1].startswith('0302') for r in steps.get('buttons', [])):
        problems.append('the button press is not in `buttons`')
    return d, problems


def main():
    app = sys.argv[1:] or [sys.executable, os.path.join(HERE, 'spacemouse_check.py')]
    tmp = tempfile.mkdtemp()
    fifo_path = os.path.join(tmp, 'device.fifo')
    os.mkfifo(fifo_path)
    os.chmod(fifo_path, 0o666)
    fake = subprocess.Popen(['sudo', '-n', 'python3', FAKE, '--fifo', fifo_path],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    fifo = open(fifo_path, 'wb')
    node = None
    for line in fake.stdout:
        if '/dev/hidraw' in line:
            node = line[line.index('/dev/hidraw'):].split()[0].rstrip('.,')
            break
    time.sleep(1)
    failed = False
    try:
        for elevated in (False, True):
            name = 'elevated' if elevated else 'direct'
            out = os.path.join(tmp, name + '.json')
            lines = run(app, fifo, node, elevated, out)
            if not os.path.exists(out):
                print('%s: FAIL, no report saved\n  %s' % (name, '\n  '.join(lines[-15:])))
                failed = True
                continue
            d, problems = check(out)
            print('%s: %s  (access=%s, move test %s reports)' % (
                name, 'FAIL ' + '; '.join(problems) if problems else 'ok',
                d.get('access', 'direct'), d.get('move_test_reports')))
            failed |= bool(problems)
    finally:
        fifo.close()
        subprocess.run(['sudo', '-n', 'kill', str(fake.pid)])
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
