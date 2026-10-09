import SwiftUI

/// One exercise over time: its top weight and volume per session, then every time
/// it was logged. Mirrors templates/exercise.html.
struct ExerciseView: View {
    @Environment(AppState.self) private var app
    @Environment(\.dismiss) private var back

    let name: String
    @State private var range: String
    @State private var detail: ExerciseDetail?
    @State private var error: String?

    init(name: String, range: String) {
        self.name = name
        _range = State(initialValue: range)
    }

    private struct Key: Hashable {
        let range: String
        let changes: Int
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Button {
                    back()
                } label: {
                    Label("Back", systemImage: "chevron.left").labelStyle(.titleAndIcon)
                }
                .buttonStyle(LinkButtonStyle(color: Palette.muted, size: 15))

                VStack(alignment: .leading, spacing: 10) {
                    Text(name.capFirst)
                        .font(.head(30, relativeTo: .largeTitle))
                        .tracking(-0.6)
                        .foregroundStyle(Palette.ink)
                        .fixedSize(horizontal: false, vertical: true)
                    if let tags = detail?.tags, !tags.isEmpty {
                        FlowLayout(spacing: 6) {
                            ForEach(tags, id: \.self) { tag in
                                Text(tag)
                                    .font(.text(13, .medium, relativeTo: .footnote))
                                    .foregroundStyle(Palette.ink2)
                                    .padding(.horizontal, 10)
                                    .padding(.vertical, 5)
                                    .background(Palette.surface2, in: Capsule())
                                    .overlay { Capsule().strokeBorder(Palette.chipBorder, lineWidth: 1) }
                            }
                        }
                    }
                }

                SegmentedToggle(options: ProgressStore.ranges, selection: $range, label: "Time range", fill: true)
                if let error { ErrorBanner(message: error) }
                if let detail, detail.range == range {
                    content(detail)
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
        .task(id: Key(range: range, changes: app.changes)) { await load() }
    }

    private func load() async {
        do {
            // The client escapes the path, so the name goes in as it is.
            detail = try await app.api.get("/exercises/\(name)", query: ["range": range])
            error = nil
        } catch let failure {
            error = app.message(for: failure)
        }
    }

    @ViewBuilder
    private func content(_ detail: ExerciseDetail) -> some View {
        if detail.entries.isEmpty {
            EmptyRange { range = "all" }
        } else {
            Text(summary(detail))
                .font(.text(15))
                .foregroundStyle(Palette.ink2)
                .fixedSize(horizontal: false, vertical: true)

            let weights = SeriesPoint.weights(detail.series)
            VStack(alignment: .leading, spacing: 12) {
                CardHead("Top weight per session")
                if let progress = detail.progress { LiftTrend(lift: progress) }
                if weights.isEmpty {
                    Text("Weights without a leading number (like \"bodyweight\") are not charted.")
                        .font(.text(13, relativeTo: .footnote))
                        .foregroundStyle(Palette.muted)
                } else {
                    TrendLine(points: weights, unit: detail.weightUnit, label: "Top weight per session")
                }
            }
            .card()

            if !weights.isEmpty {
                VStack(alignment: .leading, spacing: 12) {
                    CardHead(title: "Volume per session") {
                        Text("weight × reps")
                            .font(.text(13, relativeTo: .footnote))
                            .foregroundStyle(Palette.muted)
                    }
                    SessionColumns(
                        points: SeriesPoint.volumes(detail.series), unit: detail.weightUnit,
                        label: "Volume per session"
                    )
                }
                .card()
            }

            SectionHead("Every time").padding(.top, 4)
            VStack(spacing: 0) {
                ForEach(Array(detail.entries.enumerated()), id: \.element.id) { index, entry in
                    if index > 0 { Palette.line2.frame(height: 1).padding(.horizontal, 16) }
                    NavigationLink(value: Route.day(date: entry.date, session: entry.session, saved: nil)) {
                        row(entry)
                    }
                    .buttonStyle(.plain)
                }
            }
            .card(padding: 0)
        }
    }

    private func summary(_ detail: ExerciseDetail) -> String {
        var parts = ["\(detail.sessions) session\(detail.sessions == 1 ? "" : "s")"]
        if let best = detail.best { parts.append("best \(best.weight) (\(Days.label(best.date)))") }
        if detail.volume > 0 { parts.append("\(Numbers.short(detail.volume)) \(detail.weightUnit) total volume") }
        if let last = detail.lastDate { parts.append("last done \(Days.label(last))") }
        return parts.joined(separator: " · ")
    }

    private func row(_ entry: ExerciseEntry) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(Days.label(entry.date))
                    .font(.text(15, .medium))
                    .foregroundStyle(Palette.ink)
                Spacer(minLength: 8)
                Text([entry.weight, entry.setsReps].filter { !$0.isEmpty }.joined(separator: " · "))
                    .font(.text(15))
                    .monospacedDigit()
                    .foregroundStyle(Palette.ink2)
                    .multilineTextAlignment(.trailing)
            }
            if let notes = entry.notes, !notes.isEmpty {
                Text(notes)
                    .font(.text(13, relativeTo: .footnote))
                    .foregroundStyle(Palette.muted)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isButton)
    }
}
