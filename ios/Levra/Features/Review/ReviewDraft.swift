import Foundation

/// A workout on its way to being saved: what POST /parse heard, or an empty form
/// to fill in by hand. Everything stays text, as the server stores it.
struct ReviewDraft: Hashable, Identifiable {
    struct LiftRow: Hashable, Identifiable {
        let id = UUID()
        var entry = EntryDraft()
    }

    struct CardioRow: Hashable, Identifiable {
        let id = UUID()
        var entry = CardioDraft()
    }

    let id = UUID()
    /// True when there was no text to read: "Add manually".
    var byHand = false
    var date: String
    var dateFromText = false
    var lifts: [LiftRow] = []
    var cardio: [CardioRow] = []
    var bodyweight = ""
    var title = ""
    /// The name the server gives the workout if `title` is left empty.
    var defaultTitle = ""
    var visibility: String
    var firstLog = false

    /// The date the default title was worked out for.
    private var titleDate = ""

    init(_ heard: ParseResult) {
        date = heard.date
        titleDate = heard.date
        dateFromText = heard.dateFromText
        lifts = heard.entries.map { LiftRow(entry: $0) }
        cardio = heard.cardio.map { CardioRow(entry: $0) }
        bodyweight = heard.bodyweight ?? ""
        title = heard.title
        defaultTitle = heard.defaultTitle
        visibility = heard.visibility
        firstLog = heard.firstLog
    }

    /// An empty form with one lift to start on. Private until there is a profile,
    /// as the server defaults it.
    @MainActor
    static func manual(app: AppState, firstLog: Bool) -> ReviewDraft {
        var draft = ReviewDraft(date: Days.today(), visibility: app.me?.profile == nil ? "private" : "friends")
        draft.byHand = true
        draft.lifts = [LiftRow()]
        draft.firstLog = firstLog
        return draft
    }

    private init(date: String, visibility: String) {
        self.date = date
        self.visibility = visibility
    }

    var isEmpty: Bool {
        savedLifts.isEmpty && savedCardio.isEmpty && bodyweight.trimmed.isEmpty
    }

    /// Rows without a name are dropped, as the server would drop them.
    var savedLifts: [EntryDraft] { lifts.map(\.entry).filter { !$0.exercise.trimmed.isEmpty } }
    var savedCardio: [CardioDraft] { cardio.map(\.entry).filter { !$0.activity.trimmed.isEmpty } }

    /// What the title field shows while empty: the server's own default for the
    /// date it read, or "Tuesday workout" once the date has been changed.
    var titlePlaceholder: String {
        if date == titleDate, !defaultTitle.isEmpty { return defaultTitle }
        guard let day = Days.date(date) else { return "Workout" }
        let weekday = DateFormatter()
        weekday.locale = Locale(identifier: "en_US_POSIX")
        weekday.dateFormat = "EEEE"
        return "\(weekday.string(from: day)) workout"
    }

    var request: SaveRequest {
        SaveRequest(
            date: date, title: title.trimmed, visibility: visibility,
            entries: savedLifts, cardio: savedCardio, bodyweight: bodyweight.trimmed
        )
    }
}

extension String {
    var trimmed: String { trimmingCharacters(in: .whitespacesAndNewlines) }
}
