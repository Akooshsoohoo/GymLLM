import Foundation

/// Dates as the server keeps them: "YYYY-MM-DD" text in the user's own time zone.
/// The labels match the site's day_label, short_date and nice_date filters.
enum Days {
    private static let calendar = Calendar(identifier: .gregorian)

    private static func formatter(_ format: String) -> DateFormatter {
        let f = DateFormatter()
        f.calendar = calendar
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = format
        return f
    }

    private static let iso = formatter("yyyy-MM-dd")
    private static let shortFormat = formatter("EEE d MMM")
    private static let longFormat = formatter("EEEE, d MMM")

    static func iso(_ date: Date) -> String { iso.string(from: date) }
    static func date(_ value: String) -> Date? { iso.date(from: value) }
    static func today() -> String { iso(Date()) }

    /// "2026-09-24" -> "Thu 24 Sep".
    static func short(_ value: String) -> String {
        date(value).map(shortFormat.string(from:)) ?? value
    }

    /// "Today", "Yesterday", else "Wed 23 Sep" (plus the year when it isn't this
    /// one). `long` spells it out and is never relative: "Thursday, 24 Sep".
    static func label(_ value: String, long: Bool = false) -> String {
        guard let day = date(value) else { return value }
        let now = Date()
        if !long {
            if calendar.isDate(day, inSameDayAs: now) { return "Today" }
            if let yesterday = calendar.date(byAdding: .day, value: -1, to: now),
               calendar.isDate(day, inSameDayAs: yesterday) {
                return "Yesterday"
            }
        }
        let text = (long ? longFormat : shortFormat).string(from: day)
        let year = calendar.component(.year, from: day)
        return year == calendar.component(.year, from: now) ? text : "\(text) \(year)"
    }

    private static let dayMonthFormat = formatter("d MMM")

    /// "2026-10-05" -> "5 Oct".
    static func dayMonth(_ value: String) -> String {
        date(value).map(dayMonthFormat.string(from:)) ?? value
    }

    private static let stamp: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    /// "2026-10-06T18:04:05Z" -> "just now", "5m", "3h", "2d", then "6 Oct". The
    /// site's ago filter.
    static func ago(_ value: String?, now: Date = Date()) -> String {
        guard let value, let then = stamp.date(from: value) else { return "" }
        let seconds = max(now.timeIntervalSince(then), 0)
        if seconds < 60 { return "just now" }
        if seconds < 3600 { return "\(Int(seconds / 60))m" }
        if seconds < 86400 { return "\(Int(seconds / 3600))h" }
        if seconds < 7 * 86400 { return "\(Int(seconds / 86400))d" }
        return dayMonthFormat.string(from: then)
    }

    /// "Morning", "Afternoon" or "Evening", as Home greets you on the site.
    static func greeting(at date: Date = Date()) -> String {
        let hour = Calendar.current.component(.hour, from: date)
        return (4..<12).contains(hour) ? "Morning" : (12..<17).contains(hour) ? "Afternoon" : "Evening"
    }
}

extension String {
    /// "back squat" -> "Back squat"; the rest is left alone, so "RDL" stays.
    var capFirst: String { prefix(1).uppercased() + dropFirst() }
}

enum Numbers {
    /// 86400 -> "86k"; 4625 -> "4.6k"; 950 -> "950". The site's short_num filter.
    static func short(_ n: Double) -> String {
        if abs(n) >= 10000 { return String(format: "%.0fk", n / 1000) }
        if abs(n) >= 1000 {
            var text = String(format: "%.1f", n / 1000)
            if text.hasSuffix(".0") { text.removeLast(2) }
            return text + "k"
        }
        return plain(n)
    }

    /// 250.0 -> "250"; 12.5 -> "12.5". The site's fmt_num filter, without the commas.
    static func plain(_ n: Double) -> String {
        n == n.rounded() ? String(format: "%.0f", n) : String(format: "%.1f", n)
    }

    /// 5 -> "+5"; -2.5 -> "-2.5"; 0 -> "0".
    static func signed(_ n: Double) -> String { (n > 0 ? "+" : "") + plain(n) }
}
