#!/usr/bin/env python3
# Copyright 2006-2026 The QElectroTech Team
# This file is part of QElectroTech.
#
# QElectroTech is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# QElectroTech is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with QElectroTech.  If not, see <http://www.gnu.org/licenses/>.
"""SpaceMouse Check for Windows and Linux: misc/spacemouse-capture.py in a
window, for people who would rather not use a terminal.

It finds the 3D mouse, checks QElectroTech's route to it (direct USB, as
QET's hidapi backend reads it) gets anything, then walks through the same
twelve guided steps with a countdown instead of Enter prompts, and saves
the same JSON the script does. The device code is the script's own,
imported from spacemouse_capture.py next to this file.

On Linux /dev/hidraw* is readable by root only. Rather than running the
whole window as root, the app starts a copy of itself through pkexec
(the desktop's own password prompt) that only reads the device and
passes each report back on stdout.

    spacemouse_check.py                         the window
    spacemouse_check.py --stream /dev/hidrawN   (internal) the pkexec reader
    spacemouse_check.py --auto --save-to F      run and save without clicks (tests)
    spacemouse_check.py --selftest F            no window: find devices, write F (CI)
"""
import datetime
import json
import os
import platform
import queue
import select
import subprocess
import sys
import threading
import time

import spacemouse_capture as cap

# Tests replace the password prompt with `sudo -n`.
ELEVATE = os.environ.get('SPACEMOUSE_CHECK_ELEVATE', 'pkexec').split()
TOOL = 'SpaceMouse Check (%s) 1' % ('Windows' if sys.platform == 'win32' else 'Linux')
MOVE_TEST_SECONDS = 6
GET_READY_SECONDS = 3


def emit(line):
    """A line for tests and CI. A windowed Windows build has no console
    (sys.stdout is None), so SPACEMOUSE_CHECK_EVENTS can name a file instead."""
    path = os.environ.get('SPACEMOUSE_CHECK_EVENTS')
    if path:
        with open(path, 'a') as f:
            f.write(line + '\n')
    elif sys.stdout:
        print(line, flush=True)


def device_class():
    return {'win32': cap.WinDevice, 'darwin': cap.MacDevice}.get(sys.platform, cap.HidrawDevice)


def self_command():
    """How to start this program again: the bundled executable, or the script."""
    if getattr(sys, 'frozen', False):
        return [sys.executable]
    return [sys.executable, os.path.abspath(__file__)]


def stream(path):
    """--stream: read the device as root, one 'hex' line per report, until killed."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    print('ready', flush=True)
    while True:
        ready, _, _ = select.select([fd], [], [], 1.0)
        if not ready:
            continue
        try:
            data = os.read(fd, 64)
        except BlockingIOError:
            continue
        if data:
            print(data.hex(), flush=True)


class Reader(threading.Thread):
    """Puts (monotonic time, hex) for every report into a queue."""

    def __init__(self, reports):
        super().__init__(daemon=True)
        self.reports = reports
        self.stopping = False
        self.error = None

    def stop(self):
        self.stopping = True


class DirectReader(Reader):
    def __init__(self, reports, device):
        super().__init__(reports)
        self.device = device

    def run(self):
        try:
            while not self.stopping:
                start = time.monotonic()
                for ms, data in self.device.record(0.1):
                    self.reports.put((start + ms / 1000.0, data))
        except Exception as e:      # the device went away
            self.error = str(e)
        finally:
            self.device.close()


class PkexecReader(Reader):
    """Linux without read access: a root copy of this program reads for us."""

    def __init__(self, reports, path):
        super().__init__(reports)
        self.proc = subprocess.Popen(ELEVATE + self_command() + ['--stream', path],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.ready = threading.Event()

    def run(self):
        for line in self.proc.stdout:
            line = line.strip()
            if line == 'ready':
                self.ready.set()
            elif line and not self.stopping:
                self.reports.put((time.monotonic(), line))
        self.error = (self.proc.stderr.read() or '').strip() or 'the reader stopped (code %s)' % self.proc.poll()
        self.ready.set()

    def stop(self):
        super().stop()
        if self.proc.poll() is None:
            self.proc.terminate()


class App:
    def __init__(self, auto=False, save_to=None):
        import tkinter as tk
        from tkinter import scrolledtext
        self.tk = tk
        self.auto, self.save_to = auto, save_to
        self.root = tk.Tk()
        self.root.title('SpaceMouse Check for QElectroTech')
        self.root.geometry('760x560')
        self.headline = tk.Label(self.root, font=('TkDefaultFont', 16, 'bold'), wraplength=720,
                                 justify='left', anchor='w')
        self.headline.pack(fill='x', padx=16, pady=(16, 4))
        self.countdown = tk.Label(self.root, font=('TkFixedFont', 22, 'bold'), fg='#1a5fb4', anchor='w')
        self.countdown.pack(fill='x', padx=16)
        self.logbox = scrolledtext.ScrolledText(self.root, height=18, font=('TkFixedFont', 10))
        self.logbox.pack(fill='both', expand=True, padx=16, pady=8)
        bar = tk.Frame(self.root)
        bar.pack(fill='x', padx=16, pady=(0, 16))
        self.save_button = tk.Button(bar, text='Save report…', state='disabled', command=self.save)
        self.save_button.pack(side='right', padx=(8, 0))
        self.start_button = tk.Button(bar, text='Start', default='active', command=self.start)
        self.start_button.pack(side='right')

        self.reports = queue.Queue()
        self.reader = None
        self.device = None
        self.bucket = None          # reports of the step being recorded, or None
        self.bucket_start = 0.0
        self.result = {}

        self.headline['text'] = 'Plug in the 3D mouse, then press Start.'
        self.log('This checks how QElectroTech can read your 3D mouse and records it for its tests.')
        self.log('About 3 minutes. Nothing is sent anywhere: at the end you save one file.')
        self.log('Leave 3DxWare or spacenavd as they normally are on this computer.\n')
        self.root.after(20, self.poll)
        self.root.protocol('WM_DELETE_WINDOW', self.quit)
        if auto:
            self.root.after(500, self.start)

    # -- plumbing --------------------------------------------------------

    def log(self, text):
        self.logbox.insert('end', text + '\n')
        self.logbox.see('end')
        if self.auto:
            emit(text)

    def poll(self):
        """Move reports from the reader thread into the current step."""
        while True:
            try:
                t, data = self.reports.get_nowait()
            except queue.Empty:
                break
            if self.bucket is not None and t >= self.bucket_start:
                self.bucket.append([round((t - self.bucket_start) * 1000, 1), data])
        self.root.after(20, self.poll)

    def timed(self, instruction, seconds, done):
        """'Get ready' for a few seconds, then record `seconds`, then done(reports)."""
        self.headline['text'] = 'Get ready: ' + instruction
        if self.auto:
            emit('STEP ' + instruction)

        def ready(left):
            if left > 0:
                self.countdown['text'] = 'Starts in %d…' % left
                self.root.after(1000, ready, left - 1)
                return
            self.headline['text'] = 'NOW: ' + instruction
            self.bucket, self.bucket_start = [], time.monotonic()
            if self.auto:
                emit('RECORDING')
            recording(seconds)

        def recording(left):
            if left > 0:
                self.countdown['text'] = 'Recording… %d' % int(left + 0.99)
                self.root.after(int(min(left, 1) * 1000), recording, left - min(left, 1))
                return
            self.poll_now()
            reports, self.bucket = self.bucket, None
            self.countdown['text'] = ''
            done(reports)

        ready(GET_READY_SECONDS)

    def poll_now(self):
        while True:
            try:
                t, data = self.reports.get_nowait()
            except queue.Empty:
                return
            if self.bucket is not None:
                self.bucket.append([round((t - self.bucket_start) * 1000, 1), data])

    # -- the run ---------------------------------------------------------

    def start(self):
        self.start_button['state'] = 'disabled'
        Device = device_class()
        readers = cap.other_readers()
        self.result = {
            'tool': TOOL,
            'date': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
            'system': platform.platform(),
            'other_readers': readers,
        }
        self.log('1. Looking for the 3D mouse…')
        if readers:
            self.log('   also running: ' + ', '.join(readers))
        devices = Device.find()
        if not devices:
            self.log('   No 3Dconnexion 3D mouse found. Plug it in and press Start again.')
            self.headline['text'] = 'No 3D mouse found.'
            self.start_button['state'] = 'normal'
            return self.finish_auto(ok=False)
        for d in devices[1:]:
            self.log('   also found: %s (%s:%s) -- using the first one' % (d.name, d.vendor, d.product))
        dev = self.device = devices[0]
        self.log('   %s  %s:%s' % (dev.name, dev.vendor, dev.product))
        self.result.update({
            'backend': dev.backend,
            'device': {'name': dev.name, 'vendor': dev.vendor, 'product': dev.product},
            'report_descriptor': dev.descriptor(),
            'steps': [],
        })

        self.log('\n2. Opening it the way QElectroTech does…')
        if not self.open_reader(dev):
            self.headline['text'] = 'Could not open the 3D mouse.'
            return self.finish(ok=False)
        self.timed('Move, push and twist the cap in every direction.', MOVE_TEST_SECONDS, self.after_move_test)

    def open_reader(self, dev):
        if sys.platform.startswith('linux') and not os.access(dev.path, os.R_OK):
            self.log('   %s is readable by root only: asking for your password (pkexec)…' % dev.path)
            try:
                reader = PkexecReader(self.reports, dev.path)
            except FileNotFoundError:
                self.log('   pkexec is not installed. Run the terminal version instead:')
                self.log('   sudo python3 spacemouse-capture.py --seconds 3')
                return False
            reader.start()
            reader.ready.wait(120)
            if reader.error:
                self.log('   Could not read it: ' + reader.error)
                return False
            self.result['access'] = 'pkexec'
        else:
            try:
                dev.open()
            except SystemExit as e:     # the script's own messages
                self.log('   ' + str(e))
                return False
            reader = DirectReader(self.reports, dev)
            reader.start()
        self.reader = reader
        self.log('   open.')
        return True

    def after_move_test(self, reports):
        self.result['move_test_reports'] = len(reports)
        self.log('   QElectroTech\'s way received %d reports while you moved it.' % len(reports))
        if not reports:
            self.log('   Nothing arrived. ' + self.device.empty_hint())
            self.headline['text'] = 'Nothing arrived from the 3D mouse.'
            return self.finish(ok=False)
        self.log('\n3. Recording each movement, for QElectroTech\'s tests (about 1 minute).')
        self.next_step(0)

    def next_step(self, i):
        if i == len(cap.STEPS):
            return self.finish(ok=True)
        key, text, seconds = cap.STEPS[i]

        def done(reports):
            self.result['steps'].append({'step': key, 'instruction': text, 'reports': reports})
            self.log('   %s: %d reports' % (key, len(reports)))
            self.next_step(i + 1)
        self.timed(text, seconds, done)

    def finish(self, ok):
        if self.reader:
            self.reader.stop()
        self.log('\nDone.' if ok else '\nStopped.')
        self.headline['text'] = ('Done. Press "Save report…" and attach the file to discussion #599.'
                                 if ok else self.headline['text'] + ' Press "Save report…" anyway: '
                                 'the file says why.')
        self.countdown['text'] = ''
        self.save_button['state'] = 'normal'
        self.finish_auto(ok)

    def finish_auto(self, ok):
        if self.auto:
            if self.save_to:
                self.write(self.save_to)
            emit('FINISHED ' + ('ok' if ok else 'failed'))
            self.root.after(200, self.quit)

    def save(self):
        from tkinter import filedialog
        product = self.result.get('device', {}).get('product', 'none')
        path = filedialog.asksaveasfilename(
            parent=self.root, title='Save the report',
            initialdir=os.path.expanduser('~'), initialfile='spacemouse-check-%s.json' % product,
            defaultextension='.json', filetypes=[('JSON', '*.json')])
        if path:
            self.write(path)

    def write(self, path):
        with open(path, 'w') as f:
            json.dump(self.result, f, indent=1)
        self.log('Saved ' + path)

    def quit(self):
        if self.reader:
            self.reader.stop()
        self.root.destroy()


def selftest(path):
    """No window, no device needed: check the device code loads and runs."""
    found = device_class().find()
    out = {'tool': TOOL, 'system': platform.platform(), 'other_readers': cap.other_readers(),
           'devices': [{'path': d.path, 'name': d.name, 'vendor': d.vendor, 'product': d.product}
                       for d in found]}
    with open(path, 'w') as f:
        json.dump(out, f, indent=1)
    emit(json.dumps(out, indent=1))


def main():
    args = sys.argv[1:]
    if args[:1] == ['--stream'] and len(args) == 2:
        return stream(args[1])
    if args[:1] == ['--selftest'] and len(args) == 2:
        return selftest(args[1])
    save_to = args[args.index('--save-to') + 1] if '--save-to' in args else None
    app = App(auto='--auto' in args, save_to=save_to)
    app.root.mainloop()


if __name__ == '__main__':
    sys.exit(main())
