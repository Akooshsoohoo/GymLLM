import SwiftUI

/// "Here's what we heard." Grouped cards of lifts, cardio and body weight, every
/// value a pill that edits in place. Nothing is saved until "Save workout".
/// Mirrors templates/review.html.
struct ReviewView: View {
    @Environment(AppState.self) private var app
    @Environment(\.dismiss) private var back
    let cancel: () -> Void
    let onSaved: (SavedSession, Bool) -> Void

    @State private var draft: ReviewDraft
    @State private var pickingDate = false
    @State private var saving = false
    @State private var error: String?
    private let nothingFound: Bool

    init(draft: ReviewDraft, cancel: @escaping () -> Void, onSaved: @escaping (SavedSession, Bool) -> Void) {
        _draft = State(initialValue: draft)
        self.cancel = cancel
        self.onSaved = onSaved
        // The text was read but held nothing to log: say so instead of an empty form.
        nothingFound = !draft.byHand && draft.isEmpty
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                HStack {
                    Button {
                        back()
                    } label: {
                        Label(draft.byHand ? "Back" : "Edit text", systemImage: "chevron.left")
                            .labelStyle(.titleAndIcon)
                    }
                    Spacer()
                    Button("Cancel", action: cancel)
                }
                .buttonStyle(LinkButtonStyle(color: Palette.muted, size: 15))

                VStack(alignment: .leading, spacing: 8) {
                    Text(heading)
                        .font(.head(30, relativeTo: .largeTitle))
                        .tracking(-0.6)
                        .foregroundStyle(Palette.ink)
                        .fixedSize(horizontal: false, vertical: true)
                    if let hint {
                        Text(hint)
                            .font(.text(15))
                            .foregroundStyle(Palette.ink2)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }

                dateRow
                titleField
                liftsGroup
                cardioGroup
                bodyweightCard
                visibilityCard
            }
            .padding(.horizontal, Metrics.gutter)
            .padding(.top, 8)
            .padding(.bottom, 20)
        }
        .scrollDismissesKeyboard(.interactively)
        .background(Palette.bg)
        .toolbar(.hidden, for: .navigationBar)
        .safeAreaInset(edge: .bottom, spacing: 0) { saveBar }
        .sheet(isPresented: $pickingDate) { datePicker }
        .disabled(saving)
    }

    private var heading: String {
        draft.byHand ? "Add it by hand" : nothingFound ? "We couldn't find a workout in that." : "Here's what we heard."
    }

    private var hint: String? {
        if nothingFound {
            return "Say what you did and how much, like \"bench 135, 3 sets of 8, then ran 2 miles\". Go back to change your words, or add it here."
        }
        return draft.firstLog ? "Tap anything to fix it. Nothing is saved until you press Save." : nil
    }

    // MARK: Date and name

    private var dateRow: some View {
        HStack(spacing: 10) {
            Button {
                pickingDate = true
            } label: {
                HStack(spacing: 6) {
                    Text(dateLabel)
                    Image(systemName: "chevron.down").font(.system(size: 11, weight: .bold))
                }
                .font(.text(14, .semibold, relativeTo: .subheadline))
                .foregroundStyle(Palette.onPrimary)
                .padding(.horizontal, 14)
                .padding(.vertical, 8)
                .background(Palette.primary, in: Capsule())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Date, \(dateLabel)")
            if draft.dateFromText {
                Text("taken from your text")
                    .font(.text(13, relativeTo: .footnote))
                    .foregroundStyle(Palette.muted)
            }
        }
    }

    private var dateLabel: String {
        let relative = Days.label(draft.date)
        let short = Days.short(draft.date)
        return relative == "Today" || relative == "Yesterday" ? "\(relative) · \(short)" : relative
    }

    private var datePicker: some View {
        let selection = Binding<Date>(
            get: { Days.date(draft.date) ?? Date() },
            set: {
                draft.date = Days.iso($0)
                draft.dateFromText = false
            }
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

    private var titleField: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Name this workout")
                .font(.text(13, .semibold, relativeTo: .footnote))
                .foregroundStyle(Palette.muted)
            TextField(
                "", text: $draft.title,
                prompt: Text(draft.titlePlaceholder).foregroundStyle(Palette.muted2)
            )
            .font(.text(16, .medium))
            .foregroundStyle(Palette.ink)
            .padding(.horizontal, 14)
            .frame(height: 46)
            .background(Palette.surface, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            .accessibilityLabel("Name this workout")
            .onChange(of: draft.title) { _, new in
                if new.count > 80 { draft.title = String(new.prefix(80)) }
            }
        }
    }

    // MARK: Groups

    private var liftsGroup: some View {
        group("Lifts", empty: draft.byHand ? "No lifts." : "No lifts in this text.", isEmpty: draft.lifts.isEmpty) {
            withAnimation(.easeOut(duration: 0.15)) { draft.lifts.append(.init()) }
        } rows: {
            ForEach($draft.lifts) { $row in
                ReviewRow(name: $row.entry.exercise, placeholder: "Exercise") {
                    withAnimation(.easeOut(duration: 0.15)) { draft.lifts.removeAll { $0.id == row.id } }
                } pills: {
                    ValuePill(name: "weight", text: $row.entry.weight)
                    ValuePill(name: "sets", text: $row.entry.sets, unit: "sets", keyboard: .numberPad)
                    ValuePill(name: "reps", text: $row.entry.reps, unit: "reps", keyboard: .numbersAndPunctuation)
                    ValuePill(name: "note", text: $row.entry.notes)
                }
                if row.id != draft.lifts.last?.id { Palette.line2.frame(height: 1) }
            }
        }
    }

    private var cardioGroup: some View {
        group("Cardio", empty: draft.byHand ? "No cardio." : "No cardio in this text.", isEmpty: draft.cardio.isEmpty) {
            withAnimation(.easeOut(duration: 0.15)) { draft.cardio.append(.init()) }
        } rows: {
            ForEach($draft.cardio) { $row in
                ReviewRow(name: $row.entry.activity, placeholder: "Activity") {
                    withAnimation(.easeOut(duration: 0.15)) { draft.cardio.removeAll { $0.id == row.id } }
                } pills: {
                    ValuePill(name: "distance", text: $row.entry.distance)
                    ValuePill(name: "time", text: $row.entry.duration)
                    ValuePill(name: "note", text: $row.entry.notes)
                }
                if row.id != draft.cardio.last?.id { Palette.line2.frame(height: 1) }
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
                Text("Only you see this")
                    .font(.text(13, relativeTo: .footnote))
                    .foregroundStyle(Palette.muted)
            }
            Spacer()
            ValuePill(name: "weight", text: $draft.bodyweight, keyboard: .numbersAndPunctuation)
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
                    selection: $draft.visibility, label: "Who can see this"
                )
            }
            (Text(draft.visibility == "private" ? "Only you. " : "Your friends, in their feed. ")
                .foregroundStyle(Palette.ink)
                + Text("Notes and body weight always stay private.").foregroundStyle(Palette.muted))
                .font(.text(13, relativeTo: .footnote))
        }
        .card(padding: 14)
    }

    // MARK: Save

    private var saveBar: some View {
        VStack(spacing: 10) {
            if let error { ErrorBanner(message: error) }
            Button(action: save) {
                if saving {
                    ProgressView().tint(Palette.onPrimary)
                } else {
                    Text("Save workout")
                }
            }
            .buttonStyle(.pill(.primary, height: 56, fill: true))
            .disabled(draft.isEmpty || saving)
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

    private func save() {
        UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
        saving = true
        error = nil
        Task {
            do {
                let saved: SavedSession = try await app.api.post("/sessions", draft.request)
                onSaved(saved, draft.firstLog)
            } catch let failure {
                error = app.message(for: failure)
            }
            saving = false
        }
    }
}

/// One lift or one cardio activity: the name, Remove, and its value pills.
private struct ReviewRow<Pills: View>: View {
    @Binding var name: String
    let placeholder: String
    let remove: () -> Void
    @ViewBuilder var pills: Pills

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 12) {
                TextField("", text: $name, prompt: Text(placeholder).foregroundStyle(Palette.muted2))
                    .font(.text(16, .semibold))
                    .foregroundStyle(Palette.ink)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
                    .accessibilityLabel(placeholder)
                Button("Remove", action: remove)
                    .buttonStyle(LinkButtonStyle(color: Palette.muted2, size: 13))
                    .accessibilityLabel("Remove \(name.isEmpty ? placeholder.lowercased() : name)")
            }
            FlowLayout(spacing: 8) { pills }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 14)
    }
}
