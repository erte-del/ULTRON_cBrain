// Ultron.app: Ultron in the menu bar. Opening it starts Ultron and opens the page;
// the orb's menu opens the page again or quits (which stops Ultron).
// It also owns the screen overlay: a small always-on-top window (ctrl+option+U, or "Look at
// my screen" in the orb's menu) where you ask about what's on your screen.
// Built by scripts/make_app.sh, which writes the project folder into Info.plist (UltronRoot).
import AppKit
import Carbon.HIToolbox
import WebKit

struct OverlayError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

/// A panel that can take typing without making Ultron the frontmost app, so the app
/// you're working in keeps its place.
final class OverlayPanel: NSPanel {
    override var canBecomeKey: Bool { true }
}

/// The overlay window: the page at /?overlay=1 in a floating panel, plus the capture it asks
/// for. The page talks to us through window.webkit.messageHandlers.ultron (see
/// frontend/src/screen/nativeScreenSource.ts): "start" checks Screen Recording permission,
/// "grab" answers with one JPEG of the screen (base64), "hide" hides the window.
final class Overlay: NSObject, WKScriptMessageHandlerWithReply, WKNavigationDelegate {
    let url: URL
    var panel: OverlayPanel!
    var web: WKWebView!
    var loaded = false

    init(url: URL) {
        self.url = url
        super.init()
        let config = WKWebViewConfiguration()
        config.userContentController.addScriptMessageHandler(self, contentWorld: .page, name: "ultron")
        web = WKWebView(frame: .zero, configuration: config)
        web.navigationDelegate = self

        panel = OverlayPanel(
            contentRect: NSRect(x: 0, y: 0, width: 400, height: 340),
            styleMask: [.titled, .closable, .resizable, .utilityWindow, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        panel.title = "Ultron"
        panel.isFloatingPanel = true
        panel.level = .floating
        panel.hidesOnDeactivate = false
        panel.isReleasedWhenClosed = false
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.minSize = NSSize(width: 280, height: 220)
        panel.contentView = web
        // Bottom-left the first time; after that wherever you left it.
        if !panel.setFrameUsingName("UltronOverlay") {
            let area = (NSScreen.main ?? NSScreen.screens[0]).visibleFrame
            panel.setFrameOrigin(NSPoint(x: area.minX + 16, y: area.minY + 16))
        }
        panel.setFrameAutosaveName("UltronOverlay")
    }

    var isVisible: Bool { panel.isVisible }

    func toggle() {
        if panel.isVisible { panel.orderOut(nil) } else { show() }
    }

    func show() {
        if !loaded { web.load(URLRequest(url: url)) }  // the page keeps its chat while hidden
        panel.orderFrontRegardless()
        panel.makeKey()
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) { loaded = true }
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { loaded = false }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        loaded = false  // Ultron wasn't up yet: the next show() tries again
    }

    func userContentController(
        _ controller: WKUserContentController,
        didReceive message: WKScriptMessage,
        replyHandler: @escaping (Any?, String?) -> Void
    ) {
        let kind = (message.body as? [String: Any])?["type"] as? String
        switch kind {
        case "start":
            if CGPreflightScreenCaptureAccess() {
                replyHandler(true, nil)
            } else {
                CGRequestScreenCaptureAccess()
                replyHandler(nil, "Allow Ultron under System Settings > Privacy & Security > Screen Recording, then press Share my screen.")
            }
        case "grab":
            Task { @MainActor in
                do { replyHandler(try await self.capture(), nil) }
                catch { replyHandler(nil, error.localizedDescription) }
            }
        case "hide":
            panel.orderOut(nil)
            replyHandler(true, nil)
        default:
            replyHandler(nil, "Unknown request")
        }
    }

    /// One JPEG (base64) of the screen the mouse is on. Uses macOS's own screencapture tool,
    /// which works on every macOS version and needs the same Screen Recording permission.
    /// The overlay is hidden for a moment so it isn't in the picture.
    @MainActor
    func capture() async throws -> String {
        let mouse = NSEvent.mouseLocation
        let screen = NSScreen.screens.first { NSMouseInRect(mouse, $0.frame, false) } ?? NSScreen.screens[0]
        let f = screen.frame
        let top = NSScreen.screens[0].frame.maxY  // screencapture counts y down from the top of the main screen
        let rect = "\(Int(f.minX)),\(Int(top - f.maxY)),\(Int(f.width)),\(Int(f.height))"
        let file = NSTemporaryDirectory() + "ultron-screen-\(UUID().uuidString).jpg"
        defer { try? FileManager.default.removeItem(atPath: file) }

        let wasVisible = panel.isVisible
        if wasVisible {
            panel.alphaValue = 0
            try? await Task.sleep(nanoseconds: 150_000_000)
        }
        let ok = await Task.detached {
            Overlay.run("/usr/sbin/screencapture", ["-x", "-t", "jpg", "-R", rect, file])
                && Overlay.run("/usr/bin/sips", ["-Z", "1920", file])  // shrink: big screens make big files
        }.value
        if wasVisible { panel.alphaValue = 1 }

        guard ok, let data = FileManager.default.contents(atPath: file), !data.isEmpty
        else { throw OverlayError(message: "Couldn't capture the screen.") }
        return data.base64EncodedString()
    }

    static func run(_ path: String, _ arguments: [String]) -> Bool {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: path)
        p.arguments = arguments
        p.standardOutput = FileHandle.nullDevice
        p.standardError = FileHandle.nullDevice
        do { try p.run() } catch { return false }
        p.waitUntilExit()
        return p.terminationStatus == 0
    }
}

final class App: NSObject, NSApplicationDelegate {
    let root = Bundle.main.object(forInfoDictionaryKey: "UltronRoot") as! String
    let page = URL(string: "http://127.0.0.1:8000")!
    var item: NSStatusItem!
    lazy var overlay = Overlay(url: URL(string: "http://127.0.0.1:8000/?overlay=1")!)
    var hotKey: EventHotKeyRef?

    func applicationDidFinishLaunching(_ note: Notification) {
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        item.button?.image = orb()
        item.button?.toolTip = "Ultron"
        let menu = NSMenu()
        menu.addItem(withTitle: "Open Ultron", action: #selector(openPage), keyEquivalent: "o").target = self
        menu.addItem(withTitle: "Look at my screen   ⌃⌥U", action: #selector(toggleOverlay), keyEquivalent: "").target = self
        menu.addItem(.separator())
        menu.addItem(withTitle: "Quit Ultron", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        item.menu = menu
        installEditMenu()
        registerHotKey()

        DispatchQueue.global().async {  // start_ultron.sh can take up to 30 seconds
            let (ok, message) = self.run("start_ultron.sh")
            guard !ok else { return }
            DispatchQueue.main.async {
                NSApp.activate(ignoringOtherApps: true)
                let alert = NSAlert()
                alert.messageText = "Ultron couldn't start"
                alert.informativeText = message
                alert.alertStyle = .warning
                alert.runModal()
                NSApp.terminate(nil)
            }
        }
    }

    // Opening Ultron.app again while it runs just opens the page again.
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows: Bool) -> Bool {
        openPage()
        return false
    }

    func applicationWillTerminate(_ note: Notification) {
        run("stop_ultron.sh")
    }

    @objc func toggleOverlay() {
        overlay.toggle()
    }

    /// ctrl+option+U shows or hides the overlay from anywhere. Needs no permission.
    func registerHotKey() {
        var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        InstallEventHandler(GetApplicationEventTarget(), { _, _, userData in
            let me = Unmanaged<App>.fromOpaque(userData!).takeUnretainedValue()
            DispatchQueue.main.async { me.toggleOverlay() }
            return noErr
        }, 1, &spec, Unmanaged.passUnretained(self).toOpaque(), nil)
        let id = EventHotKeyID(signature: OSType(0x554C5452), id: 1)  // 'ULTR'
        RegisterEventHotKey(UInt32(kVK_ANSI_U), UInt32(controlKey | optionKey), id, GetApplicationEventTarget(), 0, &hotKey)
    }

    /// A menu bar app has no main menu, so copy and paste wouldn't work in the overlay's box.
    func installEditMenu() {
        let bar = NSMenu()
        let holder = NSMenuItem()
        bar.addItem(holder)
        let edit = NSMenu(title: "Edit")
        edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        holder.submenu = edit
        NSApp.mainMenu = bar
    }

    @objc func openPage() {
        NSWorkspace.shared.open(page)
    }

    /// Runs one of our scripts and returns whether it worked, and what it said on stderr.
    @discardableResult
    func run(_ script: String) -> (Bool, String) {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "\(root)/scripts/\(script)")
        let err = Pipe()
        p.standardError = err
        p.standardOutput = FileHandle.nullDevice
        do { try p.run() } catch { return (false, error.localizedDescription) }
        let data = err.fileHandleForReading.readDataToEndOfFile()
        p.waitUntilExit()
        return (p.terminationStatus == 0, String(decoding: data, as: UTF8.self))
    }

    /// The orb from the page header as a menu bar symbol: a ring around a dot. A template
    /// image, so macOS draws it white or black to match the menu bar.
    func orb() -> NSImage {
        let img = NSImage(size: NSSize(width: 18, height: 18), flipped: false) { r in
            NSColor.black.set()
            let ring = NSBezierPath(ovalIn: r.insetBy(dx: 1.5, dy: 1.5))
            ring.lineWidth = 1.5
            ring.stroke()
            NSBezierPath(ovalIn: r.insetBy(dx: 5, dy: 5)).fill()
            return true
        }
        img.isTemplate = true
        return img
    }
}

let app = NSApplication.shared
let delegate = App()
app.delegate = delegate
app.run()
