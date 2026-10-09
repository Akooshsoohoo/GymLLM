import SwiftUI

/// One of your own days: the poster, the numbers, body weight and what friends
/// said. Where you land after saving, and where a workout is edited and shared from.
/// Mirrors templates/day.html at phone width.
struct DayView: View {
    @Environment(AppState.self) private var app
    @Environment(\.dismiss) private var back

    @State private var date: String
    @State private var session: Int?
    @State private var saved: Route.SavedKind?
    @State private var day: DayDetail?
    @State private var error: String?
    @State private var pickingDate = false
    @State private var editing: DayDetail?
    @State private var sharing: DayDetail?
    /// The tab this stack belongs to, for the back button.
    private let backTitle: String

    init(date: String, session: Int?, saved: Route.SavedKind?, backTitle: String = "Home") {
        _date = State(initialValue: date)
        _session = State(initialValue: session)
        _saved = State(initialValue: saved)
        self.backTitle = backTitle
    }

    private struct Key: Hashable {
        let date: String
        let session: Int?
        let changes: Int
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                header
                if let error { ErrorBanner(message: error) }
                if let day, day.date == date {
                    content(day)
                } else if error == nil {
                    ProgressView()
                        .frame(maxWidth: .infinity)
                        .padding(.top, 60)
                }
            }
            .padding(.horizontal, Metrics.gutter)
            .padding(.top, 8)
            .padding(.bottom, 28)
        }
        .background(Palette.bg)
        .toolbar(.hidden, for: .navigationBar)
        .refreshable { await load() }
        .task(id: Key(date: date, session: session, changes: app.changes)) { await load() }
        .sheet(isPresented: $pickingDate) { datePicker }
        .sheet(item: $sharing) { day in
            ShareSheet(day: day, name: app.firstName)
        }
        .fullScreenCover(item: $editing) { day in
            DayEditView(day: day, cancel: { editing = nil }) { result in
                editing = nil
                edited(day, result)
            }
        }
    }

    /// Land on the workout wherever the edit left it. When it took the last thing
    /// off the day, there is nothing here to look at: go back.
    private func edited(_ day: DayDetail, _ result: DayEditResult) {
        saved = nil
        if !result.removed {
            date = result.date
            session = result.session
        } else if day.sessions.count > 1 || result.weighInLeft || (day.bodyweight != nil && !day.editsBodyweight) {
            session = nil
        } else {
            app.didChange()
            back()
            return
        }
        app.didChange()
    }

    private var datePicker: some View {
        let selection = Binding<Date>(
            get: { Days.date(date) ?? Date() },
            set: { go(to: Days.iso($0)) }
        )
        return VStack(spacing: 8) {
            DatePicker("Go to date", selection: selection, in: ...Date(), displayedComponents: .date)
                .datePickerStyle(.graphical)
                .tint(Palette.you)
            Button("Done") { pickingDate = false }
                .buttonStyle(.pill(.primary, height: 54, fill: true))
        }
        .padding(Metrics.gutter)
        .presentationDetents([.medium, .large])
        .presentationBackground(Palette.bg)
    }

    private func load() async {
        do {
            var query: [String: String] = [:]
            if let session { query["session"] = String(session) }
            day = try await app.api.get("/day/\(date)", query: query)
            error = nil
        } catch let failure {
            error = app.message(for: failure)
        }
    }

    private func go(to other: String) {
        guard other != date else { return }
        saved = nil
        session = nil
        date = other
    }

    // MARK: Header

    private var header: some View {
        VStack(spacing: 14) {
            HStack {
                Button {
                    back()
                } label: {
                    Label(backTitle, systemImage: "chevron.left").labelStyle(.titleAndIcon)
                }
                .buttonStyle(LinkButtonStyle(color: Palette.muted, size: 15))
                .accessibilityLabel("Back to \(backTitle)")
                Spacer()
                if let saved {
                    Badge(text: saved == .first ? "First workout logged" : "Saved", tone: .saved)
                }
            }
            HStack {
                step("chevron.left", to: day?.previous, label: "Previous day logged")
                Spacer()
                Button {
                    pickingDate = true
                } label: {
                    dateTitle
                }
                .buttonStyle(.plain)
                .accessibilityLabel("\(Days.label(date, long: true)). Pick a date")
                Spacer()
                step("chevron.right", to: day?.next, label: "Next day logged")
            }
        }
    }

    private var dateTitle: some View {
        VStack(spacing: 2) {
            HStack(spacing: 6) {
                Text(Days.short(date))
                    .font(.head(22))
                    .foregroundStyle(Palette.ink)
                Image(systemName: "chevron.down")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(Palette.muted)
            }
            Group {
                let relative = Days.label(date)
                if relative == "Today" || relative == "Yesterday" {
                    Text(relative)
                } else if relative != Days.short(date) {
                    Text(String(date.prefix(4)))  // the year, when it isn't this one
                }
            }
            .font(.text(13, .medium, relativeTo: .footnote))
            .foregroundStyle(Palette.muted)
        }
        .contentShape(Rectangle())
    }

    private func step(_ symbol: String, to other: String?, label: String) -> some View {
        let target = day?.date == date ? other : nil
        return Button {
            if let target { go(to: target) }
        } label: {
            Image(systemName: symbol)
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(target == nil ? Palette.disabled : Palette.ink)
                .frame(width: 40, height: 40)
                .background(Palette.surface, in: Circle())
        }
        .buttonStyle(.plain)
        .disabled(target == nil)
        .accessibilityLabel(target.map { "\(label): \(Days.short($0))" } ?? label)
    }

    // MARK: Content

    @ViewBuilder
    private func content(_ day: DayDetail) -> some View {
        if !day.sessions.isEmpty {
            FlowLayout(spacing: 8) {
                ForEach(day.sessions, id: \.session) { item in
                    Chip(text: item.title, active: item.session == day.session) {
                        saved = nil
                        session = item.session
                    }
                }
            }
        }
        if day.isEmpty {
            VStack(spacing: 6) {
                Text("Nothing logged on \(Days.label(date)).")
                    .font(.text(16, .medium))
                    .foregroundStyle(Palette.ink2)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 40)
        } else {
            if !day.lifts.isEmpty || !day.cardio.isEmpty { poster(day) }
            HStack(spacing: 10) {
                Button("Edit") { editing = day }
                    .buttonStyle(.pill(.white, fill: true))
                    .accessibilityLabel("Edit this workout")
                if !day.lifts.isEmpty || !day.cardio.isEmpty {
                    Button("Share") { sharing = day }
                        .buttonStyle(.pill(.primary, fill: true))
                        .accessibilityLabel("Share this workout")
                }
            }
            HStack(spacing: 10) {
                StatTile(label: "Exercises", value: String(day.stats.exercises))
                StatTile(label: "Reps", value: String(day.stats.reps))
                StatTile(label: "Volume", value: day.stats.volume > 0 ? Numbers.short(day.stats.volume) : "—")
            }
            if let weight = day.bodyweight {
                HStack(alignment: .firstTextBaseline) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Body weight")
                            .font(.text(15, .medium))
                            .foregroundStyle(Palette.ink)
                        Text("Only you see this")
                            .font(.text(13, relativeTo: .footnote))
                            .foregroundStyle(Palette.muted)
                    }
                    Spacer()
                    Text(weight)
                        .font(.head(19))
                        .foregroundStyle(Palette.ink)
                }
                .card(padding: 14)
            }
            notes(day)
            if let reactions = day.reactions, let handle = app.me?.profile?.handle,
               reactions.kudos > 0 || !reactions.comments.isEmpty {
                FromFriends(
                    key: SessionKey(handle: handle, date: day.date, session: day.session), reactions: reactions
                )
                .id(reactions)
            }
        }
    }

    /// The green card that is also the look of the share image.
    private func poster(_ day: DayDetail) -> some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack {
                Text(([app.firstName, Days.short(day.date)].filter { !$0.isEmpty }.joined(separator: " · ")).uppercased())
                Spacer()
                Text("LEVRA")
            }
            .font(.text(12, .bold, relativeTo: .caption))
            .tracking(1.2)

            HStack(alignment: .top, spacing: 12) {
                VStack(alignment: .leading, spacing: 8) {
                    Text(day.title)
                        .font(.head(42, .extrabold, relativeTo: .largeTitle))
                        .tracking(-1.2)
                        .lineSpacing(-6)
                        .fixedSize(horizontal: false, vertical: true)
                    if !day.statLine.isEmpty {
                        Text(day.statLine).font(.text(16, .semibold))
                    }
                }
                Spacer(minLength: 0)
                // A stand-in until the muscle icons are exported as assets.
                Image(systemName: Self.symbol(for: day.iconHint, lifts: !day.lifts.isEmpty))
                    .font(.system(size: 34, weight: .semibold))
                    .accessibilityHidden(true)
            }

            VStack(alignment: .leading, spacing: 8) {
                ForEach(day.lines, id: \.self) { line in
                    posterRow(
                        line.exercise.capFirst + (line.pr ? " · new best" : ""),
                        line.detail, sub: line.parts.joined(separator: ", ")
                    )
                }
                ForEach(day.cardio) { c in
                    posterRow(c.activity.capFirst, c.distance.isEmpty ? c.duration : c.distance, sub: "")
                }
            }
        }
        .foregroundStyle(Palette.onYou)
        .padding(22)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Palette.you, in: RoundedRectangle(cornerRadius: 28, style: .continuous))
    }

    private func posterRow(_ name: String, _ detail: String, sub: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Palette.youRule.frame(height: 1.5)
            HStack(alignment: .firstTextBaseline, spacing: 12) {
                Text(name).lineLimit(1)
                Spacer(minLength: 0)
                Text(detail).monospacedDigit().lineLimit(1).layoutPriority(1)
            }
            .font(.text(15, .semibold))
            if !sub.isEmpty {
                Text("↳ " + sub)
                    .font(.text(14, .medium, relativeTo: .subheadline))
                    .opacity(0.85)
            }
        }
    }

    static func symbol(for hint: String, lifts: Bool) -> String {
        let hint = hint.lowercased()
        let cardio: [(String, String)] = [
            ("run", "figure.run"), ("walk", "figure.walk"), ("hike", "figure.hiking"),
            ("cycl", "figure.outdoor.cycle"), ("bik", "figure.outdoor.cycle"),
            ("swim", "figure.pool.swim"), ("row", "figure.rower"), ("yoga", "figure.yoga"),
        ]
        if !lifts, let match = cardio.first(where: { hint.contains($0.0) }) { return match.1 }
        return lifts ? "dumbbell.fill" : "figure.mixed.cardio"
    }

    /// Notes are yours alone, so they sit apart from the poster.
    @ViewBuilder
    private func notes(_ day: DayDetail) -> some View {
        let lifts = day.lifts.filter { !($0.notes ?? "").isEmpty }.map { ($0.exercise, $0.notes ?? "") }
        let cardio = day.cardio.filter { !($0.notes ?? "").isEmpty }.map { ($0.activity, $0.notes ?? "") }
        let all = lifts + cardio
        if !all.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                Text("Your notes")
                    .font(.head(17))
                    .foregroundStyle(Palette.ink)
                ForEach(Array(all.enumerated()), id: \.offset) { _, item in
                    VStack(alignment: .leading, spacing: 1) {
                        Text(item.0.capFirst)
                            .font(.text(13, .semibold, relativeTo: .footnote))
                            .foregroundStyle(Palette.muted)
                        Text(item.1)
                            .font(.text(15))
                            .foregroundStyle(Palette.ink)
                    }
                }
            }
            .card()
        }
    }
}
