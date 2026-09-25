// SpaceMouse Check — a double-click macOS app for QElectroTech 3D mouse reports.
//
// It answers two questions on a Mac with (or without) 3DxWare installed:
//   1. Can QET's current route (hidapi = IOKit HID, opened shared) read the
//      device, and who else has it open?
//   2. Does the 3DxWare route (3DconnexionClient.framework, as Blender uses)
//      deliver motion instead?
// If route 1 works it also makes the guided raw recording that becomes a
// test fixture (same format as misc/spacemouse-capture.py).
//
// Everything ends up in one JSON file the user saves and attaches.
// `SpaceMouseCheck --selftest out.json` runs the non-interactive checks
// without a window (used by CI, where there is no device).

import AppKit
import Foundation
import IOKit
import IOKit.hid

let toolVersion = "SpaceMouse Check 1"
let vendors: [Int: String] = [0x046D: "Logitech (older 3Dconnexion)", 0x256F: "3Dconnexion"]

let guidedSteps: [(String, String, Int)] = [
    ("rest", "Do not touch the device.", 3),
    ("right", "Push the cap to the RIGHT and hold it, then let go.", 4),
    ("left", "Push the cap to the LEFT and hold it, then let go.", 4),
    ("away", "Push the cap AWAY from you and hold it, then let go.", 4),
    ("toward", "Pull the cap TOWARDS you and hold it, then let go.", 4),
    ("down", "Press the cap DOWN and hold it, then let go.", 4),
    ("up", "Lift the cap UP and hold it, then let go.", 4),
    ("twist_cw", "TWIST the cap CLOCKWISE (seen from above) and hold, then let go.", 4),
    ("twist_ccw", "TWIST the cap ANTICLOCKWISE and hold, then let go.", 4),
    ("tilt_away", "TILT the cap AWAY from you and hold, then let go.", 4),
    ("tilt_right", "TILT the cap to the RIGHT and hold, then let go.", 4),
    ("buttons", "Press each button once, slowly, one at a time, in any order.", 15),
]

// MARK: - Small helpers

func hex(_ d: Data) -> String { d.map { String(format: "%02x", $0) }.joined() }

func ioReturnText(_ r: IOReturn) -> String {
    let u = UInt32(bitPattern: r)
    switch u {
    case 0: return "ok"
    case 0xE00002C5: return String(format: "0x%08X exclusive access: another program holds the device", u)
    case 0xE00002E2: return String(format: "0x%08X not permitted: macOS privacy (Input Monitoring)", u)
    case 0xE00002C1: return String(format: "0x%08X not privileged", u)
    default: return String(format: "0x%08X", u)
    }
}

func run(_ path: String, _ args: [String]) -> String {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: path)
    p.arguments = args
    let pipe = Pipe()
    p.standardOutput = pipe
    p.standardError = pipe
    do { try p.run() } catch { return "could not run \(path): \(error)" }
    let data = pipe.fileHandleForReading.readDataToEndOfFile()
    p.waitUntilExit()
    return String(decoding: data, as: UTF8.self)
}

func grepLines(_ text: String, _ needles: [String]) -> [String] {
    text.split(separator: "\n").map(String.init).filter { line in
        needles.contains { line.lowercased().contains($0) }
    }
}

// MARK: - Environment

func environment() -> [String: Any] {
    var env: [String: Any] = [:]
    env["macos"] = ProcessInfo.processInfo.operatingSystemVersionString
    env["machine"] = run("/usr/bin/uname", ["-m"]).trimmingCharacters(in: .whitespacesAndNewlines)

    let fw = "/Library/Frameworks/3DconnexionClient.framework"
    if let b = Bundle(path: fw), let info = b.infoDictionary {
        env["3dxware_framework"] = [
            "path": fw,
            "version": info["CFBundleVersion"] as? String ?? "?",
            "short_version": info["CFBundleShortVersionString"] as? String ?? "?",
        ]
    } else {
        env["3dxware_framework"] = "not installed"
    }
    let needles = ["3dconnexion", "3dx"]
    env["processes"] = grepLines(run("/bin/ps", ["-A", "-o", "pid=,comm="]), needles)
        .map { $0.trimmingCharacters(in: .whitespaces) }
    env["kexts"] = grepLines(run("/usr/sbin/kextstat", ["-l"]), needles)
    env["system_extensions"] = grepLines(run("/usr/bin/systemextensionsctl", ["list"]), needles)
    env["device_openers"] = deviceOpeners()
    return env
}

/// Which processes have the 3D mouse open, from the I/O Registry: each
/// user client under the device carries "IOUserClientCreator" = "pid N, name".
func deviceOpeners() -> [String] {
    let text = run("/usr/sbin/ioreg", ["-l", "-w0", "-r", "-c", "IOHIDDevice"])
    var out: [String] = []
    var block: [String] = []
    func flush() {
        let joined = block.joined(separator: "\n")
        let ours = joined.contains("\"VendorID\" = 1133") || joined.contains("\"VendorID\" = 9839")
        if ours && joined.contains("\"PrimaryUsage\" = 8") {
            for line in block where line.contains("+-o") || line.contains("IOUserClientCreator") {
                out.append(line.trimmingCharacters(in: .whitespaces))
            }
        }
        block = []
    }
    for line in text.split(separator: "\n").map(String.init) {
        // A root entry starts at column 0 with "+-o".
        if line.hasPrefix("+-o") { flush() }
        block.append(line)
    }
    flush()
    return out
}

// MARK: - Route 1: IOKit HID, the way QET's hidapi backend reads it

final class HidRoute {
    var device: IOHIDDevice?
    var info: [String: Any] = [:]
    var openResult: IOReturn = -1
    var buffer: UnsafeMutablePointer<UInt8>?
    var onReport: ((Data) -> Void)?

    static var current: HidRoute?

    func find() -> [IOHIDDevice] {
        let mgr = IOHIDManagerCreate(kCFAllocatorDefault, 0)
        IOHIDManagerSetDeviceMatching(mgr, nil)
        let all = IOHIDManagerCopyDevices(mgr) as? Set<IOHIDDevice> ?? []
        var list: [[String: Any]] = []
        var found: [IOHIDDevice] = []
        for d in all {
            guard let vendor = intProp(d, "VendorID"), vendors[vendor] != nil else { continue }
            let page = intProp(d, "PrimaryUsagePage") ?? 0
            let usage = intProp(d, "PrimaryUsage") ?? 0
            list.append([
                "product": strProp(d, "Product") ?? "?",
                "vendor": String(format: "%04x", vendor),
                "product_id": String(format: "%04x", intProp(d, "ProductID") ?? 0),
                "usage": String(format: "%x:%x", page, usage),
                "transport": strProp(d, "Transport") ?? "?",
            ])
            // Same test as QET's SpaceMouseHid::isSpaceMouse().
            if (page == 1 && usage == 8) || (page == 0 && usage == 0) { found.append(d) }
        }
        info["seen"] = list
        return found
    }

    func intProp(_ d: IOHIDDevice, _ k: String) -> Int? { IOHIDDeviceGetProperty(d, k as CFString) as? Int }
    func strProp(_ d: IOHIDDevice, _ k: String) -> String? { IOHIDDeviceGetProperty(d, k as CFString) as? String }

    /// Opens the first 3D mouse shared (kIOHIDOptionsTypeNone), as QET does since #1028.
    func open() -> Bool {
        guard let d = find().first else {
            info["open"] = "no 3D mouse found"
            return false
        }
        device = d
        info["device"] = [
            "name": strProp(d, "Product") ?? "?",
            "vendor": String(format: "%04x", intProp(d, "VendorID") ?? 0),
            "product": String(format: "%04x", intProp(d, "ProductID") ?? 0),
        ]
        if let desc = IOHIDDeviceGetProperty(d, "ReportDescriptor" as CFString) as? Data {
            info["report_descriptor"] = hex(desc)
        }
        openResult = IOHIDDeviceOpen(d, 0)
        info["open"] = ioReturnText(openResult)
        guard openResult == 0 else { return false }

        let size = intProp(d, "MaxInputReportSize") ?? 64
        buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: size)
        HidRoute.current = self
        let cb: IOHIDReportCallback = { _, _, _, _, _, report, length in
            let data = Data(bytes: report, count: length)
            HidRoute.current?.onReport?(data)
        }
        IOHIDDeviceRegisterInputReportCallback(d, buffer!, size, cb, nil)
        IOHIDDeviceScheduleWithRunLoop(d, CFRunLoopGetMain(), CFRunLoopMode.commonModes.rawValue)
        return true
    }

    func close() {
        guard let d = device, openResult == 0 else { return }
        IOHIDDeviceUnscheduleFromRunLoop(d, CFRunLoopGetMain(), CFRunLoopMode.commonModes.rawValue)
        IOHIDDeviceClose(d, 0)
        openResult = -1
    }
}

// MARK: - Route 2: 3DxWare's own client framework, as Blender does

typealias MessageHandler = @convention(c) (UInt32, UInt32, UnsafeMutableRawPointer?) -> Void
typealias DeviceHandler = @convention(c) (UInt32) -> Void
typealias SetConnexionHandlersFn = @convention(c) (MessageHandler?, DeviceHandler?, DeviceHandler?, Bool) -> Int16
typealias CleanupConnexionHandlersFn = @convention(c) () -> Void
typealias RegisterConnexionClientFn = @convention(c) (UInt32, UnsafePointer<UInt8>?, UInt16, UInt32) -> UInt16
typealias SetConnexionClientButtonMaskFn = @convention(c) (UInt16, UInt32) -> Void
typealias UnregisterConnexionClientFn = @convention(c) (UInt16) -> Void
typealias ConnexionClientControlFn = @convention(c) (UInt16, UInt32, Int32, UnsafeMutablePointer<Int32>?) -> Int16

let kConnexionMsgDeviceState: UInt32 = 0x33645352   // '3dSR'
let kConnexionCtlGetDeviceID: UInt32 = 0x33646964   // '3did'
let kConnexionClientWildcard: UInt32 = 0x2A2A2A2A   // '****'
let ownSignature: UInt32 = 0x51457363               // 'QEsc', matches Info.plist

final class DriverRoute {
    var info: [String: Any] = [:]
    var handle: UnsafeMutableRawPointer?
    var setHandlers: SetConnexionHandlersFn?
    var cleanup: CleanupConnexionHandlersFn?
    var register: RegisterConnexionClientFn?
    var buttonMask: SetConnexionClientButtonMaskFn?
    var unregister: UnregisterConnexionClientFn?
    var control: ConnexionClientControlFn?
    var clientID: UInt16 = 0
    var handlersInstalled = false
    var onEvent: (([String: Any]) -> Void)?

    static var current: DriverRoute?

    func load() -> Bool {
        let path = "/Library/Frameworks/3DconnexionClient.framework/3DconnexionClient"
        guard FileManager.default.fileExists(atPath: path) else {
            info["load"] = "3DxWare framework not installed"
            return false
        }
        guard let h = dlopen(path, RTLD_LAZY | RTLD_LOCAL) else {
            info["load"] = "dlopen failed: " + (dlerror().map { String(cString: $0) } ?? "?")
            return false
        }
        handle = h
        func sym<T>(_ name: String, _ type: T.Type) -> T? {
            guard let s = dlsym(h, name) else { return nil }
            return unsafeBitCast(s, to: type)
        }
        setHandlers = sym("SetConnexionHandlers", SetConnexionHandlersFn.self)
        cleanup = sym("CleanupConnexionHandlers", CleanupConnexionHandlersFn.self)
        register = sym("RegisterConnexionClient", RegisterConnexionClientFn.self)
        buttonMask = sym("SetConnexionClientButtonMask", SetConnexionClientButtonMaskFn.self)
        unregister = sym("UnregisterConnexionClient", UnregisterConnexionClientFn.self)
        control = sym("ConnexionClientControl", ConnexionClientControlFn.self)
        guard let setHandlers = setHandlers, register != nil else {
            info["load"] = "framework loaded but SetConnexionHandlers/RegisterConnexionClient missing"
            return false
        }
        DriverRoute.current = self
        let message: MessageHandler = { _, type, arg in
            guard type == kConnexionMsgDeviceState, let p = arg else { return }
            // ConnexionDeviceState, #pragma pack(2): client@2 command@4 param@6
            // value@8 time@12 report@20 appEventPressed@28 axis[6]@30 buttons@44
            var axes: [Int] = []
            for i in 0..<6 { axes.append(Int(p.loadUnaligned(fromByteOffset: 30 + 2 * i, as: Int16.self))) }
            let ev: [String: Any] = [
                "client": Int(p.loadUnaligned(fromByteOffset: 2, as: UInt16.self)),
                "command": Int(p.loadUnaligned(fromByteOffset: 4, as: UInt16.self)),
                "value": Int(p.loadUnaligned(fromByteOffset: 8, as: Int32.self)),
                "pressed": Int(p.loadUnaligned(fromByteOffset: 28, as: UInt16.self)),
                "axis": axes,
                "buttons": Int(p.loadUnaligned(fromByteOffset: 44, as: UInt32.self)),
            ]
            DispatchQueue.main.async { DriverRoute.current?.onEvent?(ev) }
        }
        let added: DeviceHandler = { _ in
            DispatchQueue.main.async { DriverRoute.current?.deviceAdded() }
        }
        let removed: DeviceHandler = { _ in
            DispatchQueue.main.async { DriverRoute.current?.info["removed_seen"] = true }
        }
        let err = setHandlers(message, added, removed, true)
        info["load"] = "ok"
        info["set_handlers"] = Int(err)
        handlersInstalled = err == 0
        return handlersInstalled
    }

    func deviceAdded() {
        var result: Int32 = 0
        if let control = control, clientID != 0 {
            _ = control(clientID, kConnexionCtlGetDeviceID, 0, &result)
            info["device_id"] = String(format: "%04x:%04x", (result >> 16) & 0xffff, result & 0xffff)
        }
        info["added_seen"] = true
    }

    /// Registers in take-over mode. `signature` is either this app's own
    /// (events only while it is frontmost, which is what QET would use) or
    /// the wildcard (every application).
    func registerClient(signature: UInt32) -> UInt16 {
        guard let register = register else { return 0 }
        let name = Array("SpaceMouseCheck".utf8)
        let pascal = [UInt8(name.count)] + name
        clientID = pascal.withUnsafeBufferPointer { register(signature, $0.baseAddress, 1, 0x3fff) }
        buttonMask?(clientID, 0xffffffff)
        return clientID
    }

    func unregisterClient() {
        if clientID != 0 { unregister?(clientID) }
        clientID = 0
    }

    func shutdown() {
        unregisterClient()
        if handlersInstalled { cleanup?() }
        handlersInstalled = false
    }
}

// MARK: - The guided run

final class Checker: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    var headline = NSTextField(labelWithString: "")
    var countdown = NSTextField(labelWithString: "")
    var logView = NSTextView()
    var startButton = NSButton()
    var saveButton = NSButton()

    let hid = HidRoute()
    let driver = DriverRoute()
    var result: [String: Any] = [:]
    var hidBucket: [[Any]] = []
    var driverBucket: [[String: Any]] = []
    var bucketStart = Date()
    var queue: [() -> Void] = []
    var timer: Timer?

    func applicationDidFinishLaunching(_ n: Notification) {
        buildWindow()
        log("This checks how QElectroTech can read your 3D mouse on this Mac.")
        log("It takes about 3 minutes. Nothing is sent anywhere; at the end you save one file.")
        log("Leave 3DxWare exactly as it normally is on this Mac (installed and running, or not).\n")
        headline.stringValue = "Plug in the 3D mouse, then press Start."
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ s: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ n: Notification) { driver.shutdown(); hid.close() }

    func buildWindow() {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 720, height: 560),
                          styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        window.title = "SpaceMouse Check for QElectroTech"
        let v = window.contentView!

        headline.frame = NSRect(x: 20, y: 470, width: 680, height: 70)
        headline.font = .boldSystemFont(ofSize: 20)
        headline.maximumNumberOfLines = 3
        headline.lineBreakMode = .byWordWrapping
        v.addSubview(headline)

        countdown.frame = NSRect(x: 20, y: 430, width: 680, height: 34)
        countdown.font = .monospacedDigitSystemFont(ofSize: 26, weight: .semibold)
        countdown.textColor = .systemBlue
        v.addSubview(countdown)

        let scroll = NSScrollView(frame: NSRect(x: 20, y: 70, width: 680, height: 350))
        scroll.hasVerticalScroller = true
        scroll.borderType = .bezelBorder
        logView.frame = scroll.contentView.bounds
        logView.autoresizingMask = [.width]
        logView.isEditable = false
        logView.font = .monospacedSystemFont(ofSize: 11, weight: .regular)
        scroll.documentView = logView
        v.addSubview(scroll)

        startButton = NSButton(title: "Start", target: self, action: #selector(start))
        startButton.frame = NSRect(x: 580, y: 20, width: 120, height: 32)
        startButton.keyEquivalent = "\r"
        v.addSubview(startButton)

        saveButton = NSButton(title: "Save report…", target: self, action: #selector(save))
        saveButton.frame = NSRect(x: 440, y: 20, width: 130, height: 32)
        saveButton.isEnabled = false
        v.addSubview(saveButton)

        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func log(_ s: String) {
        logView.textStorage?.append(NSAttributedString(string: s + "\n", attributes: [
            .font: NSFont.monospacedSystemFont(ofSize: 11, weight: .regular),
            .foregroundColor: NSColor.textColor,
        ]))
        logView.scrollToEndOfDocument(nil)
    }

    // A step shows "get ready" for 3 s, then records for `seconds`. It is
    // skipped when `when` says there is nothing to test.
    func timed(_ instruction: String, seconds: Int, when: @escaping () -> Bool = { true },
               end: @escaping () -> Void) {
        queue.append { [self] in
            guard when() else { next(); return }
            var left = 3
            headline.stringValue = "Get ready: " + instruction
            countdown.stringValue = "Starts in \(left)…"
            timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [self] t in
                left -= 1
                if left > 0 { countdown.stringValue = "Starts in \(left)…"; return }
                t.invalidate()
                headline.stringValue = "NOW: " + instruction
                hidBucket = []; driverBucket = []; bucketStart = Date()
                var rec = seconds
                countdown.stringValue = "Recording… \(rec)"
                timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [self] t2 in
                    rec -= 1
                    if rec > 0 { countdown.stringValue = "Recording… \(rec)"; return }
                    t2.invalidate()
                    countdown.stringValue = ""
                    end()
                    next()
                }
            }
        }
    }

    func instant(_ f: @escaping () -> Void) { queue.append { [self] in f(); next() } }

    func next() {
        guard !queue.isEmpty else { return }
        let f = queue.removeFirst()
        DispatchQueue.main.async(execute: f)
    }

    func ms() -> Double { (Date().timeIntervalSince(bucketStart) * 10000).rounded() / 10 }

    @objc func start() {
        startButton.isEnabled = false
        hid.onReport = { [self] d in hidBucket.append([ms(), hex(d)]) }
        driver.onEvent = { [self] e in var e = e; e["ms"] = ms(); driverBucket.append(e) }
        result["tool"] = toolVersion
        result["date"] = ISO8601DateFormatter().string(from: Date())

        instant { [self] in
            log("1. Looking at this Mac…")
            let env = environment()
            result["environment"] = env
            log("   macOS \(env["macos"] ?? "?")")
            if let fw = env["3dxware_framework"] as? [String: Any] {
                log("   3DxWare installed: framework \(fw["short_version"] ?? "?") (\(fw["version"] ?? "?"))")
            } else { log("   3DxWare: not installed") }
            for p in env["processes"] as? [String] ?? [] { log("   running: \(p)") }
            for o in env["device_openers"] as? [String] ?? [] { log("   device: \(o)") }
        }

        instant { [self] in
            log("\n2. Opening the device the way QElectroTech does now…")
            let ok = hid.open()
            log("   open: \(hid.info["open"] ?? "?")")
            if let dev = hid.info["device"] as? [String: String] {
                log("   device: \(dev["name"] ?? "?") \(dev["vendor"] ?? ""):\(dev["product"] ?? "")")
            }
            if !ok { log("   (QElectroTech cannot read the device this way on this Mac.)") }
        }

        timed("Move, push and twist the cap in every direction.", seconds: 6,
              when: { [self] in hid.openResult == 0 }, end: { [self] in
            hid.info["reports_while_moving"] = hidBucket.count
            hid.info["sample"] = Array(hidBucket.prefix(20))
            log("   QElectroTech's way received \(hidBucket.count) reports while you moved it.")
        })

        instant { [self] in
            log("\n3. Asking 3DxWare for the motion instead (the way Blender does)…")
            if driver.load() {
                let id = driver.registerClient(signature: ownSignature)
                driver.info["client_own"] = Int(id)
                log("   connected to 3DxWare, client \(id)")
            } else {
                log("   \(driver.info["load"] ?? "not available")")
            }
        }

        timed("Move, push and twist the cap again.", seconds: 6,
              when: { [self] in driver.handlersInstalled }, end: { [self] in
            driver.info["events_own_signature"] = driverBucket.count
            driver.info["sample_own_signature"] = Array(driverBucket.prefix(20))
            driver.info["hid_reports_meanwhile"] = hidBucket.count
            log("   3DxWare delivered \(driverBucket.count) events; QElectroTech's way got \(hidBucket.count) meanwhile.")
            driver.unregisterClient()
            if driverBucket.isEmpty {
                let id = driver.registerClient(signature: kConnexionClientWildcard)
                driver.info["client_wildcard"] = Int(id)
                log("   Nothing arrived; trying again as a system-wide client (\(id)).")
            }
        })

        timed("One last time: move the cap in every direction.", seconds: 6,
              when: { [self] in driver.handlersInstalled && driver.clientID != 0 }, end: { [self] in
            driver.info["events_wildcard"] = driverBucket.count
            driver.info["sample_wildcard"] = Array(driverBucket.prefix(20))
            log("   System-wide: 3DxWare delivered \(driverBucket.count) events.")
            driver.unregisterClient()
        })

        instant { [self] in
            driver.shutdown()
            result["hid_route"] = hid.info
            result["driver_route"] = driver.info
            let got = (hid.info["reports_while_moving"] as? Int ?? 0) > 0
            if got {
                log("\n4. Recording each movement, for QElectroTech's tests (about 1 minute).")
                let capture: [String: Any] = [
                    "tool": toolVersion, "date": result["date"] ?? "",
                    "system": "macOS " + ProcessInfo.processInfo.operatingSystemVersionString,
                    "backend": "iokit",
                    "device": hid.info["device"] ?? [String: String](),
                    "report_descriptor": hid.info["report_descriptor"] ?? "unknown",
                    "steps": [[String: Any]](),
                ]
                result["capture"] = capture
            } else {
                log("\n4. Skipping the recording: QElectroTech's way gets no reports on this Mac.")
                queue.removeAll()
                finish()
            }
        }

        for (key, text, secs) in guidedSteps {
            timed(text, seconds: secs, when: { [self] in result["capture"] != nil }, end: { [self] in
                guard var cap = result["capture"] as? [String: Any],
                      var steps = cap["steps"] as? [[String: Any]] else { return }
                steps.append(["step": key, "instruction": text, "reports": hidBucket])
                cap["steps"] = steps
                result["capture"] = cap
                log("   \(key): \(hidBucket.count) reports")
            })
        }
        instant { [self] in finish() }
        next()
    }

    func finish() {
        hid.close()
        result["hid_route"] = hid.info
        result["driver_route"] = driver.info
        headline.stringValue = "Done. Press “Save report…” and attach the file to the discussion."
        countdown.stringValue = ""
        log("\nSummary")
        log("  QElectroTech's way (direct USB): open \(hid.info["open"] ?? "?"), \(hid.info["reports_while_moving"] ?? 0) reports")
        let d = driver.info
        log("  Through 3DxWare: \(d["load"] ?? "not tried"); own \(d["events_own_signature"] ?? "-"), system-wide \(d["events_wildcard"] ?? "-") events")
        saveButton.isEnabled = true
        saveButton.keyEquivalent = "\r"
    }

    @objc func save() {
        let panel = NSSavePanel()
        let stamp = ISO8601DateFormatter().string(from: Date()).prefix(10)
        panel.nameFieldStringValue = "spacemouse-check-\(stamp).json"
        panel.directoryURL = FileManager.default.urls(for: .desktopDirectory, in: .userDomainMask).first
        panel.beginSheetModal(for: window) { [self] resp in
            guard resp == .OK, let url = panel.url else { return }
            do {
                let data = try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys])
                try data.write(to: url)
                log("\nSaved \(url.path)")
                NSWorkspace.shared.activateFileViewerSelecting([url])
            } catch {
                log("\nCould not save: \(error)")
            }
        }
    }
}

// MARK: - Entry point

let args = CommandLine.arguments
if args.count >= 3 && args[1] == "--selftest" {
    // No window, no device needed: exercise every non-interactive path.
    var out: [String: Any] = ["tool": toolVersion, "environment": environment()]
    let hid = HidRoute()
    _ = hid.open()
    hid.close()
    out["hid_route"] = hid.info
    let driver = DriverRoute()
    if driver.load() {
        // Register both ways, letting callbacks arrive, as the real run does.
        for (key, sig) in [("client_own", ownSignature), ("client_wildcard", kConnexionClientWildcard)] {
            driver.info[key] = Int(driver.registerClient(signature: sig))
            RunLoop.main.run(until: Date().addingTimeInterval(2))
            driver.unregisterClient()
        }
    }
    driver.shutdown()
    out["driver_route"] = driver.info
    let data = try! JSONSerialization.data(withJSONObject: out, options: [.prettyPrinted, .sortedKeys])
    try! data.write(to: URL(fileURLWithPath: args[2]))
    print(String(decoding: data, as: UTF8.self))
    exit(0)
}

let app = NSApplication.shared
let mainMenu = NSMenu()
let appItem = NSMenuItem()
mainMenu.addItem(appItem)
let appMenu = NSMenu()
appMenu.addItem(NSMenuItem(title: "Quit SpaceMouse Check",
                           action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
appItem.submenu = appMenu
app.mainMenu = mainMenu
let checker = Checker()
app.delegate = checker
app.setActivationPolicy(.regular)
app.run()
