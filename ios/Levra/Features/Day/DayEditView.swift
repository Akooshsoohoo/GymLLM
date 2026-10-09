import SwiftUI

/// Change one logged workout: its name, its date, its lifts and cardio, the day's
/// weigh-in and who sees it, or delete it. Nothing changes until "Save changes".
/// Mirrors templates/day_edit.html; the rows are the review screen's.
struct DayEditView: View {
    @Environment(AppState.self) private var app
    let day: DayDetail
    let cancel: () -> Void
    let onDone: (DayEditResult) -> Void

    /// A row of the form. `saved` is the row's id on the server; nil is a new row.
    private struct LiftRow: Identifiable {
        let id = UUID()
        var saved: Int?
        var entry = EntryDraft()
    }

    private struct CardioRow: Identifiable {
        let id = UUID()
        var saved: Int?
        var entry = CardioDraft()
    }

    @State private var date: String
    @State private var title: String
    @State private var visibility: String
    @State private var bodyweight: String
    @State private var lifts: [LiftRow]
    @State private var cardio: [CardioRow]
    @State private var removedLifts: [Int] = []
    @State private var removedCardio: [Int] = []
    @State private var pickingDate = false
    @State private var confirmingDelete = false
    @State private var saving = false
    @State private var error: String?

    init(day: DayDetail, cancel: @escaping () -> Void, onDone: @escaping (DayEditResult) -> Void) {
        self.day = day
        self.cancel = cancel
        self.onDone = onDone
        _date = State(initialValue: day.date)
        // A name the server made up stays the placeholder, so it follows the date.
        _title = State(initialValue: day.title == day.defaultTitle ? "" : day.title)
        _visibility = State(initialValue: day.visibility)
        _bodyweight = State(initialValue: day.bodyweight ?? "")
        _lifts = State(initialValue: day.lifts.map {
            LiftRow(saved: $0.id, entry: EntryDraft(
                exercise: $0.exercise, weight: $0.weight, sets: $0.sets, reps: $0.reps, notes: $0.notes ?? ""
            ))
        })
        _cardio = State(initialValue: day.cardio.map {
            CardioRow(saved: $0.id, entry: CardioDraft(
                activity: $0.activity, distance: $0.distance, duration: $0.duration, notes: $0.notes ?? ""
            ))
        })
    }

    private var path: String { "/day/\(day.date)/sessions/\(day.session)" }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                HStack {
                    Button {
                        cancel()
                    } label: {
                        Label("Back to day", systemImage: "chevron.left").labelStyle(.titleAndIcon)
                    }
                    Spacer()
                    Button("Cancel", action: cancel)
                }
                .buttonStyle(LinkButtonStyle(color: Palette.muted, size: 15))

                Text("Edit \(Days.label(day.date))")
                    .font(.head(30, relativeTo: .largeTitle))
                    .tracking(-0.6)
                    .foregroundStyle(Palette.ink)

                titleField
                dateRow
                liftsGroup
                cardioGroup
                if day.editsBodyweight { bodyweightCard }
                visibilityCard

                Button("Delete this workout") { confirmingDelete = true }
                    .buttonStyle(LinkButtonStyle(color: Palette.dangerInk, size: 15))
                    .frame(maxWidth: .infinity)
                    .padding(.top, 4)
            }
            .padding(.horizontal, Metrics.gutter)
            .padding(.top, 8)
            .padding(.bottom, 20)
        }
        .scrollDismissesKeyboard(.interactively)
        .background(Palette.bg)
        .safeAreaInset(edge: .bottom, spacing: 0) { saveBar }
        .sheet(isPresented: $pickingDate) { datePicker }
        .confirmationDialog("Delete this workout?", isPresented: $confirmingDelete, titleVisibility: .visible) {
            Button("Delete workout", role: .destructive) {
                send { try await app.api.delete(path) }
            }
            Button("Keep it", role: .cancel) {}
        } message: {
            Text(
                day.bodyweight != nil && day.editsBodyweight
                    ? "Its lifts and cardio are removed for good. The day's body weight stays."
                    : "Its lifts and cardio are removed for good."
            )
        }
        .disabled(saving)
    }

    // MARK: Name and date

    private var titleField: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Title")
                .font(.text(13, .semibold, relativeTo: .footnote))
                .foregroundStyle(Palette.muted)
            TextField("", text: $title, prompt: Text(day.defaultTitle).foregroundStyle(Palette.muted2))
                .font(.text(16, .medium))
                .foregroundStyle(Palette.ink)
                .padding(.horizontal, 14)
                .frame(height: 46)
                .background(Palette.surface, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                .accessibilityLabel("Title")
                .onChange(of: title) { _, new in
                    if new.count > 80 { title = String(new.prefix(80)) }
                }
        }
    }

    private var dateRow: some View {
        HStack(spacing: 10) {
            Button {
                pickingDate = true
            } label: {
                HStack(spacing: 6) {
                    Text(Days.label(date))
                    Image(systemName: "chevron.down").font(.system(size: 11, weight: .bold))
                }
                .font(.text(14, .semibold, relativeTo: .subheadline))
                .foregroundStyle(Palette.onPrimary)
                .padding(.horizontal, 14)
                .padding(.vertical, 8)
                .background(Palette.primary, in: Capsule())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Date, \(Days.label(date))")
            Text("Changing it moves this workout")
                .font(.text(13, relativeTo: .footnote))
                .foregroundStyle(Palette.muted)
        }
    }

    private var datePicker: some View {
        let selection = Binding<Date>(
            get: { Days.date(date) ?? Date() },
            set: { date = Days.iso($0) }
        )
        return VStack(spacing: 8) {
            DatePicker("Date", selection: selection, in: ...Date(), displayedComponents: .date)
                .datePickerStyle(.graphical)
                .tint(Palette.you)
            Button("Done") { pickingDate = false }
                .buttonStyle(.pill(.primary, height: 54, fill: true))
        }
        .padding(Metrics.gutter)
        .presentationDetents([.medium, .large])
        .presentationBackground(Palette.bg)
    }

    // MARK: Rows

    private var liftsGroup: some View {
        group("Lifts", empty: "No lifts in this workout.", isEmpty: lifts.isEmpty) {
            withAnimation(.easeOut(duration: 0.15)) { lifts.append(.init()) }
        } rows: {
            ForEach($lifts) { $row in
                ReviewRow(name: $row.entry.exercise, placeholder: "Exercise") {
                    if let saved = row.saved { removedLifts.append(saved) }
                    withAnimation(.easeOut(duration: 0.15)) { lifts.removeAll { $0.id == row.id } }
                } pills: {
                    ValuePill(name: "weight", text: $row.entry.weight)
                    ValuePill(name: "sets", text: $row.entry.sets, unit: "sets", keyboard: .numberPad)
                    ValuePill(name: "reps", text: $row.entry.reps, unit: "reps", keyboard: .numbersAndPunctuation)
                    ValuePill(name: "note", text: $row.entry.notes)
                }
                if row.id != lifts.last?.id { Palette.line2.frame(height: 1) }
            }
        }
    }

    private var cardioGroup: some View {
        group("Cardio", empty: "No cardio in this workout.", isEmpty: cardio.isEmpty) {
            withAnimation(.easeOut(duration: 0.15)) { cardio.append(.init()) }
        } rows: {
            ForEach($cardio) { $row in
                ReviewRow(name: $row.entry.activity, placeholder: "Activity") {
                    if let saved = row.saved { removedCardio.append(saved) }
                    withAnimation(.easeOut(duration: 0.15)) { cardio.removeAll { $0.id == row.id } }
                } pills: {
                    ValuePill(name: "distance", text: $row.entry.distance)
                    ValuePill(name: "time", text: $row.entry.duration)
                    ValuePill(name: "note", text: $row.entry.notes)
                }
                if row.id != cardio.last?.id { Palette.line2.frame(height: 1) }
            }
        }
    }

    private func group(
        _ title: String, empty: String, isEmpty: Bool, add: @escaping () -> Void,
        @ViewBuilder rows: () -> some View
    ) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline) {
                Text(title)
                    .font(.head(17))
                    .foregroundStyle(Palette.ink)
                Spacer()
                Button("+ Add", action: add)
                    .buttonStyle(LinkButtonStyle())
                    .accessibilityLabel("Add to \(title)")
            }
            if isEmpty {
                Text(empty)
                    .font(.text(13, relativeTo: .footnote))
                    .foregroundStyle(Palette.muted)
            } else {
                VStack(spacing: 0) { rows() }
                    .card(padding: 0)
            }
        }
    }

    private var bodyweightCard: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text("Body weight")
                    .font(.head(17))
                    .foregroundStyle(Palette.ink)
                Text("Only you see this. Clear it to remove the reading.")
                    .font(.text(13, relativeTo: .footnote))
                    .foregroundStyle(Palette.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer()
            ValuePill(name: "weight", text: $bodyweight, keyboard: .numbersAndPunctuation)
        }
        .card(padding: 14)
    }

    private var visibilityCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 12) {
                Text("Who can see this")
                    .font(.head(17))
                    .foregroundStyle(Palette.ink)
                Spacer(minLength: 0)
                SegmentedToggle(
                    options: [("private", "Private"), ("friends", "Friends")],
                    selection: $visibility, label: "Who can see this"
                )
            }
            (Text(visibility == "private" ? "Only you. " : "Your friends, in their feed. ")
                .foregroundStyle(Palette.ink)
                + Text("It covers everything logged that day. Notes and body weight always stay private.")
                .foregroundStyle(Palette.muted))
                .font(.text(13, relativeTo: .footnote))
        }
        .card(padding: 14)
    }

    // MARK: Save

    private var saveBar: some View {
        VStack(spacing: 10) {
            if let error { ErrorBanner(message: error) }
            Button {
                let body = request
                send { try await app.api.put(path, body) }
            } label: {
                if saving {
                    ProgressView().tint(Palette.onPrimary)
                } else {
                    Text("Save changes")
                }
            }
            .buttonStyle(.pill(.primary, height: 56, fill: true))
            .disabled(saving)
        }
        .padding(.horizontal, Metrics.gutter)
        .padding(.top, 22)
        .padding(.bottom, 10)
        .background {
            LinearGradient(
                stops: [
                    .init(color: Palette.bgClear, location: 0),
                    .init(color: Palette.bg, location: 0.3),
                ],
                startPoint: .top, endPoint: .bottom
            )
            .ignoresSafeArea(edges: .bottom)
        }
    }

    /// Every row still on the form with what it now says, the rows taken off it, and
    /// the new ones that were given a name.
    private var request: DayEditRequest {
        var liftEdits = removedLifts.map { LiftEdit(id: $0, delete: true) }
        for row in lifts {
            let e = row.entry
            if row.saved == nil, e.exercise.trimmed.isEmpty { continue }
            liftEdits.append(LiftEdit(
                id: row.saved, exercise: e.exercise.trimmed, weight: e.weight.trimmed,
                sets: e.sets.trimmed, reps: e.reps.trimmed, notes: e.notes.trimmed
            ))
        }
        var cardioEdits = removedCardio.map { CardioEdit(id: $0, delete: true) }
        for row in cardio {
            let e = row.entry
            if row.saved == nil, e.activity.trimmed.isEmpty { continue }
            cardioEdits.append(CardioEdit(
                id: row.saved, activity: e.activity.trimmed, distance: e.distance.trimmed,
                duration: e.duration.trimmed, notes: e.notes.trimmed
            ))
        }
        return DayEditRequest(
            date: date, title: title.trimmed, visibility: visibility,
            bodyweight: day.editsBodyweight ? bodyweight.trimmed : nil,
            lifts: liftEdits, cardio: cardioEdits
        )
    }

    private func send(_ work: @escaping () async throws -> DayEditResult) {
        UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
        saving = true
        error = nil
        Task {
            do {
                onDone(try await work())
            } catch let failure {
                error = app.message(for: failure)
            }
            saving = false
        }
    }
}
