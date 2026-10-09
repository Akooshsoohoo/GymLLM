import SwiftUI

/// What Progress is showing, kept while you are on another tab.
@MainActor
@Observable
final class ProgressStore {
    enum Section: String, CaseIterable {
        case overview, sessions, exercises

        var label: String { rawValue.capFirst }
    }

    static let ranges: [(value: String, label: String)] = [
        ("7d", "7d"), ("30d", "30d"), ("90d", "90d"), ("1y", "1y"), ("all", "All"),
    ]

    var section: Section = .overview
    var range = "all"
    /// How "Workouts per ..." is grouped. Nil takes the range's own default.
    var by: String?
    /// Any date in the week the calendar shows. Nil is this week.
    var week: String?
    var query = ""

    var overview: ProgressOverview?
    var sessions: SessionList?
    var exercises: ExerciseList?
    var error: String?

    /// Everything ever logged, from whichever tab has loaded. Nil until one has.
    var total: Int? { overview?.total ?? sessions?.total ?? exercises?.total }

    func setRange(_ value: String) {
        guard value != range else { return }
        range = value
        by = nil  // each range has its own grouping to start from
    }

    func load(app: AppState) async {
        do {
            switch section {
            case .overview:
                var query = ["range": range]
                if let by { query["by"] = by }
                if let week { query["week"] = week }
                overview = try await app.api.get("/progress", query: query)
            case .sessions:
                let words = query.trimmed
                // Wait for a pause in the typing before asking.
                if !words.isEmpty { try await Task.sleep(for: .milliseconds(300)) }
                sessions = try await app.api.get("/search", query: ["range": range, "q": words])
            case .exercises:
                exercises = try await app.api.get("/exercises", query: ["range": range])
            }
            error = nil
        } catch let failure {
            error = app.message(for: failure)
        }
    }
}

/// Progress: Overview, Sessions and Exercises under one time range. Mirrors
/// templates/progress.html, search.html and exercises.html at phone width.
struct ProgressScreen: View {
    @Environment(AppState.self) private var app
    @Bindable var store: ProgressStore
    let openLog: () -> Void

    private struct Key: Hashable {
        let section: ProgressStore.Section
        let range: String
        let by: String?
        let week: String?
        let query: String
        let changes: Int
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("Progress")
                    .font(.head(32, relativeTo: .largeTitle))
                    .foregroundStyle(Palette.ink)
                sectionTabs
                if let total = store.total, total > 0 {
                    SegmentedToggle(
                        options: ProgressStore.ranges,
                        selection: Binding(get: { store.range }, set: { store.setRange($0) }),
                        label: "Time range", fill: true
                    )
                }
                if let error = store.error { ErrorBanner(message: error) }
                content
            }
            .padding(.horizontal, Metrics.gutter)
            .padding(.top, 20)
            .padding(.bottom, 28)
        }
        .scrollDismissesKeyboard(.interactively)
        .background(Palette.bg)
        .toolbar(.hidden, for: .navigationBar)
        .refreshable { await store.load(app: app) }
        .task(
            id: Key(
                section: store.section, range: store.range, by: store.by, week: store.week,
                query: store.query.trimmed, changes: app.changes
            )
        ) { await store.load(app: app) }
    }

    private var sectionTabs: some View {
        HStack(spacing: 22) {
            ForEach(ProgressStore.Section.allCases, id: \.self) { section in
                let on = store.section == section
                Button {
                    store.section = section
                } label: {
                    Text(section.label)
                        .font(.text(16, on ? .bold : .medium))
                        .foregroundStyle(on ? Palette.ink : Palette.muted)
                        .padding(.bottom, 8)
                        .overlay(alignment: .bottom) {
                            Capsule().fill(on ? Palette.you : .clear).frame(height: 3)
                        }
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(on ? .isSelected : [])
            }
            Spacer(minLength: 0)
        }
        .overlay(alignment: .bottom) { Palette.line.frame(height: 1) }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Progress sections")
    }

    @ViewBuilder
    private var content: some View {
        if store.total == 0 {
            EmptyNote(text: "Nothing logged yet. Your stats and charts show up here once you log a workout.") {
                Button("Log your first workout", action: openLog).buttonStyle(.pill(.primary))
            }
        } else {
            switch store.section {
            case .overview:
                if let overview = store.overview {
                    OverviewTab(store: store, data: overview)
                } else {
                    loading
                }
            case .sessions:
                if let sessions = store.sessions {
                    SessionsTab(store: store, data: sessions)
                } else {
                    loading
                }
            case .exercises:
                if let exercises = store.exercises {
                    ExercisesTab(store: store, data: exercises)
                } else {
                    loading
                }
            }
        }
    }

    @ViewBuilder
    private var loading: some View {
        if store.error == nil {
            ProgressView()
                .frame(maxWidth: .infinity)
                .padding(.top, 60)
        }
    }
}

/// A centred line for an empty page or an empty range, with what to do about it.
struct EmptyNote<Action: View>: View {
    let text: String
    @ViewBuilder var action: Action

    var body: some View {
        VStack(spacing: 14) {
            Text(text)
                .font(.text(16, .medium))
                .foregroundStyle(Palette.ink2)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
            action
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 36)
    }
}

/// "Nothing logged in this range." and the way out of it.
struct EmptyRange: View {
    let showAll: () -> Void

    var body: some View {
        EmptyNote(text: "Nothing logged in this range.") {
            Button("Show all time", action: showAll).buttonStyle(.pill(.ghost, height: 44))
        }
    }
}

/// A card's heading, with something quiet on the right.
struct CardHead<Trailing: View>: View {
    let title: String
    @ViewBuilder var trailing: Trailing

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Text(title)
                .font(.head(17))
                .foregroundStyle(Palette.ink)
            Spacer(minLength: 8)
            trailing
        }
    }
}

extension CardHead where Trailing == EmptyView {
    init(_ title: String) {
        self.init(title: title) { EmptyView() }
    }
}

/// "+5 · +3%" on a tint: green up, red down. `neutral` never takes a side, for body
/// weight, where which way is good depends on the goal.
struct ChangeBadge: View {
    let text: String
    let change: Double
    var neutral = false

    var body: some View {
        let up = change > 0 && !neutral, down = change < 0 && !neutral
        Text(text)
            .font(.text(12, .bold, relativeTo: .caption))
            .monospacedDigit()
            .foregroundStyle(up ? Palette.youInk : down ? Palette.dangerInk : Palette.neutralInk)
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(up ? Palette.youTint : down ? Palette.dangerTint : Palette.neutralTint, in: Capsule())
            .fixedSize()
    }
}

/// "165 → 250 lbs" and how far that is.
struct LiftTrend: View {
    let lift: LiftProgress

    var body: some View {
        HStack(spacing: 6) {
            (Text("\(Numbers.plain(lift.first)) → ").foregroundStyle(Palette.muted)
                + Text(Numbers.plain(lift.latest)).font(.text(14, .bold, relativeTo: .subheadline)).foregroundStyle(Palette.ink)
                + Text(" \(lift.unit)").foregroundStyle(Palette.muted))
                .font(.text(14, relativeTo: .subheadline))
                .monospacedDigit()
                .lineLimit(1)
            if let change = lift.change {
                ChangeBadge(
                    text: Numbers.signed(change) + (lift.pct.map { " · \($0 > 0 ? "+" : "")\($0)%" } ?? ""),
                    change: change
                )
            }
        }
    }
}
