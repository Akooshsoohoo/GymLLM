import Foundation
import Observation

/// A workout being recorded: when it started and blocks of notes. Mirrors the
/// recording static/app.js keeps in localStorage.
struct Recording: Codable, Equatable {
    struct Block: Codable, Equatable, Identifiable {
        var id = UUID()
        var name = ""
        var text = ""

        var isWritten: Bool { !name.trimmed.isEmpty || !text.trimmed.isEmpty }
    }

    struct RoutineRef: Codable, Equatable {
        let id: Int
        let name: String
    }

    /// Whose it is: a recording never shows up in somebody else's account.
    let owner: String
    let startedAt: Date
    var routine: RoutineRef?
    var blocks: [Block]

    /// What gets read: each block as "Name\nbody" (or just the body), a blank line
    /// between blocks. A line still holding a ___ placeholder was skipped, so it goes.
    var built: (text: String, blocks: Int, skipped: Int) {
        var skipped = 0
        var parts: [String] = []
        for block in blocks {
            let kept = block.text.components(separatedBy: "\n").filter { line in
                guard line.contains("___") else { return true }
                skipped += 1
                return false
            }
            let body = kept.joined(separator: "\n").trimmed
            if body.isEmpty { continue }
            let name = block.name.trimmed
            parts.append(name.isEmpty ? body : "\(name)\n\(body)")
        }
        return (parts.joined(separator: "\n\n"), parts.count, skipped)
    }

    /// 42:07, or 1:02:07 past the hour.
    static func clock(from start: Date, to now: Date = Date()) -> String {
        let s = max(0, Int(now.timeIntervalSince(start)))
        let (h, m) = (s / 3600, s % 3600 / 60)
        return (h > 0 ? "\(h):" + String(format: "%02d", m) : "\(m)") + ":" + String(format: "%02d", s % 60)
    }

    /// 42 min, 1 h 5 min; under a minute, 10 sec.
    static func duration(from start: Date, to now: Date = Date()) -> String {
        let seconds = max(0, now.timeIntervalSince(start))
        if seconds < 60 { return "\(Int(seconds)) sec" }
        let m = Int((seconds / 60).rounded())
        return m < 60 ? "\(m) min" : "\(m / 60) h" + (m % 60 > 0 ? " \(m % 60) min" : "")
    }
}

/// Keeps the live recording in a file on the device, written on every change, so
/// it is still there after the app is closed, killed or the phone restarts.
@MainActor
@Observable
final class RecordingStore {
    private(set) var saved: Recording?

    @ObservationIgnored private let file: URL

    init() {
        let folder = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        file = folder.appendingPathComponent("recording.json")
        if let data = try? Data(contentsOf: file) {
            saved = try? JSONDecoder().decode(Recording.self, from: data)
        }
    }

    func start(owner: String, routine: Recording.RoutineRef? = nil, blocks: [Recording.Block] = []) {
        saved = Recording(
            owner: owner, startedAt: Date(), routine: routine, blocks: blocks.isEmpty ? [.init()] : blocks
        )
        write()
    }

    func update(_ change: (inout Recording) -> Void) {
        guard var recording = saved else { return }
        change(&recording)
        guard recording != saved else { return }
        saved = recording
        write()
    }

    /// Thrown away, or saved as a workout: either way it is done.
    func discard() {
        saved = nil
        try? FileManager.default.removeItem(at: file)
    }

    private func write() {
        guard let saved, let data = try? JSONEncoder().encode(saved) else { return }
        try? data.write(to: file, options: .atomic)
    }
}
