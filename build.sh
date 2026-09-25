#!/bin/sh
# Build SpaceMouseCheck.app (universal: Apple silicon + Intel) and zip it.
# macOS only: needs the Xcode command line tools (swiftc, lipo, codesign).
set -eu
cd "$(dirname "$0")"
rm -rf build && mkdir -p build/SpaceMouseCheck.app/Contents/MacOS
for arch in arm64 x86_64; do
	swiftc -swift-version 5 -O -target "$arch-apple-macos11" main.swift \
		-framework AppKit -framework IOKit -o "build/SpaceMouseCheck-$arch"
done
lipo -create build/SpaceMouseCheck-arm64 build/SpaceMouseCheck-x86_64 \
	-output build/SpaceMouseCheck.app/Contents/MacOS/SpaceMouseCheck
cp Info.plist build/SpaceMouseCheck.app/Contents/
# Ad-hoc signature: required to run on Apple silicon. Not a Developer ID,
# so Gatekeeper still asks the user to allow it once (see README).
codesign --force --deep --sign - build/SpaceMouseCheck.app
(cd build && ditto -c -k --keepParent SpaceMouseCheck.app SpaceMouseCheck.zip)
echo "built build/SpaceMouseCheck.zip"
