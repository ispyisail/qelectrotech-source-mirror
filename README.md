# SpaceMouse Check — a double-click Mac app for 3D mouse reports

For a Mac user with a 3Dconnexion 3D mouse, **with or without 3DxWare
installed**. No Terminal, no Python. It takes about 3 minutes and saves one
JSON file for them to attach to the discussion.

What it finds out:

1. **This Mac:** macOS version, whether 3DxWare is installed (and which
   version), 3DxWare processes, kernel/system extensions, and which processes
   have the 3D mouse open (from the I/O Registry).
2. **QET's current route:** it opens the device the way QET's hidapi backend
   does (IOKit, shared, as since PR #1028), then counts reports while the
   user moves the cap.
3. **The 3DxWare route:** it loads `/Library/Frameworks/3DconnexionClient.framework`
   the way Blender does, registers as a take-over client and counts motion
   events. It tries this app's own signature first, which is what QET would
   use, then a system-wide client if nothing arrives. It also counts how
   many direct-USB reports QET's route receives meanwhile.
4. **The recording:** if route 2 works, it records the same twelve guided
   steps as `misc/spacemouse-capture.py`. `capture` in the JSON has the
   fixture format, ready for `tests/qttest/fixtures/spacemouse/`.

## For the user

1. Download `SpaceMouseCheck.zip` from the release
   (<https://github.com/ispyisail/qelectrotech-source-mirror/releases/tag/spacemouse-check-v1>)
   and double-click it to unzip.
2. Open **SpaceMouse Check**. The app is not notarized, so the first time
   macOS says it can't verify it. Click **Done**, then go to
   **System Settings → Privacy & Security**, scroll down and click
   **Open Anyway**. (On macOS 14 and older, right-click the app → Open.)
3. Press **Start** and follow the big text: it counts down before each
   movement.
4. Press **Save report…** and attach the file.

Leave 3DxWare as it normally is on that Mac. The point is to see what happens
in the setup people really have.

## Build

macOS only. GitHub's macOS runners build it; there is no Mac here.

```sh
sh build.sh                     # -> build/SpaceMouseCheck.zip (arm64 + x86_64)
build/SpaceMouseCheck.app/Contents/MacOS/SpaceMouseCheck --selftest out.json
```

`ci/spacemouse-check.yml` is the workflow. It lives on the fork's orphan
branch `tools/spacemouse-check-mac` as `.github/workflows/`, with these files
at the root. Each push builds and self-tests the app (the runner has no
device) and re-uploads the zip to the `spacemouse-check-v1` release.

## Not verified

- It has never run on a Mac with a real 3D mouse. CI proves it compiles,
  launches and handles "no device, no 3DxWare".
- The 3DxWare structure layout and function signatures are copied from
  Blender's `GHOST_NDOFManagerCocoa.mm`, not from 3Dconnexion's SDK, whose
  headers are confidential and must not be committed.
- The wildcard signature `'****'` meaning "every application" is from memory
  of the SDK header comment. The report says whether it delivered anything.
