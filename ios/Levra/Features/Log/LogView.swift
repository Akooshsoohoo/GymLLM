import SwiftUI

/// Logging, start to finish: say what you did, check what we heard, save. Opens
/// over the tabs; `onSaved` gets the new workout and whether it was the first ever.
struct LogFlow: View {
    let store: HomeStore
    let onSaved: (SavedSession, Bool) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var path: [ReviewDraft] = []

    var body: some View {
        NavigationStack(path: $path) {
            LogView(store: store, cancel: { dismiss() }, review: { path = [$0] })
                .navigationDestination(for: ReviewDraft.self) { draft in
                    ReviewView(draft: draft, cancel: { dismiss() }, onSaved: onSaved)
                }
        }
        .tint(Palette.you)
    }
}

/// "What did you get up to?" Mirrors templates/log.html.
struct LogView: View {
    @Environment(AppState.self) private var app
    let store: HomeStore
    let cancel: () -> Void
    let review: (ReviewDraft) -> Void

    @State private var text = ""
    @State private var unit = "lbs"
    @State private var busy = false
    @State private var error: String?
    @FocusState private var focused: Bool

    private static let suggestions = [
        "Ran 5k in 28 min", "Squats 3×8 at 135", "Yoga, 45 min", "Weighed in at 142",
    ]

    private var quota: Quota? { store.home?.quota ?? app.me?.quota }
    private var outOfLogs: Bool { quota?.left == 0 }
    private var trimmed: String { text.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                HStack {
                    Spacer()
                    Button("Cancel", action: cancel)
                        .buttonStyle(LinkButtonStyle(color: Palette.muted, size: 15))
                }
                VStack(alignment: .leading, spacing: 4) {
                    Text(Days.label(Days.today(), long: true))
                        .font(.text(14, relativeTo: .subheadline))
                        .foregroundStyle(Palette.muted)
                    Text(app.firstName.isEmpty ? "What did you get up to?" : "What did you get up to, \(app.firstName)?")
                        .font(.head(30, relativeTo: .largeTitle))
                        .tracking(-0.6)
                        .foregroundStyle(Palette.ink)
                        .fixedSize(horizontal: false, vertical: true)
                }

                if outOfLogs, let quota {
                    Text("You've used today's \(quota.limit) free logs. Come back tomorrow, or add this one by hand.")
                        .font(.text(15, .medium))
                        .foregroundStyle(Palette.neutralInk)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, 16)
                        .padding(.vertical, 12)
                        .background(Palette.neutralTint, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                }
                if let error { ErrorBanner(message: error) }

                logCard

                VStack(alignment: .leading, spacing: 10) {
                    Text("Or try something like")
                        .font(.text(14, .medium, relativeTo: .subheadline))
                        .foregroundStyle(Palette.muted)
                    FlowLayout(spacing: 8) {
                        ForEach(Self.suggestions, id: \.self) { suggestion in
                            Chip(text: suggestion) { insert(suggestion) }
                        }
                    }
                }

                if let home = store.home {
                    WeekDots(week: home.week, streak: home.streak)
                }

                HStack(spacing: 10) {
                    Text("Prefer a form?")
                        .font(.text(14, relativeTo: .subheadline))
                        .foregroundStyle(Palette.muted)
                    Button("Add manually") {
                        review(.manual(app: app, firstLog: store.home?.hasLogged == false))
                    }
                    .buttonStyle(.pill(.ghost, height: 36))
                    Spacer(minLength: 8)
                    if let quota {
                        Text(quota.leftText)
                            .font(.text(13, .medium, relativeTo: .footnote))
                            .foregroundStyle(Palette.muted)
                            .multilineTextAlignment(.trailing)
                    }
                }
            }
            .padding(.horizontal, Metrics.gutter)
            .padding(.top, 8)
            .padding(.bottom, 28)
        }
        .scrollDismissesKeyboard(.interactively)
        .background(Palette.bg)
        .toolbar(.hidden, for: .navigationBar)
        .onAppear {
            unit = app.weightUnit
            if text.isEmpty { focused = true }
        }
        .task { if store.home == nil { await store.load(app: app) } }
    }

    /// The one thing in the app with a shadow.
    private var logCard: some View {
        VStack(alignment: .leading, spacing: 18) {
            TextField(
                "", text: $text,
                prompt: Text("today I walked 3 miles, did some pull ups, curled the 20 lb dumbbells for a few sets, and weighed in at 160 lbs")
                    .foregroundStyle(Palette.muted2),
                axis: .vertical
            )
            .lineLimit(5...12)
            .font(.text(20))
            .foregroundStyle(Palette.ink)
            .focused($focused)
            .accessibilityLabel("Describe your workout")

            HStack {
                SegmentedToggle(
                    options: [("lbs", "lbs"), ("kg", "kg")], selection: $unit,
                    label: "Weight unit when you don't say one"
                )
                Spacer()
                Button(action: logIt) {
                    if busy {
                        HStack(spacing: 8) {
                            ProgressView().tint(Palette.onYou)
                            Text("Reading")
                        }
                    } else {
                        Text("Log it")
                    }
                }
                .buttonStyle(.pill(.you))
                .disabled(busy || trimmed.isEmpty || outOfLogs)
            }
        }
        .card(radius: 26, padding: 20, shadow: true)
    }

    private func insert(_ suggestion: String) {
        text = trimmed.isEmpty ? suggestion : "\(trimmed), \(suggestion.prefix(1).lowercased() + suggestion.dropFirst())"
    }

    private func logIt() {
        focused = false
        busy = true
        error = nil
        Task {
            do {
                let heard: ParseResult = try await app.api.post(
                    "/parse", ParseRequest(text: trimmed, weightUnit: unit)
                )
                review(ReviewDraft(heard))
            } catch let failure {
                error = app.message(for: failure)
            }
            busy = false
        }
    }
}
