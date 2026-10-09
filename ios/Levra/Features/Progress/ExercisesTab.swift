import SwiftUI

/// The Exercises tab: every lift in the range with its best and a line of how it
/// has moved, then cardio by activity. Mirrors templates/exercises.html.
struct ExercisesTab: View {
    @Bindable var store: ProgressStore
    let data: ExerciseList

    var body: some View {
        if data.exercises.isEmpty && data.cardio.isEmpty {
            EmptyRange { store.setRange("all") }
        } else {
            VStack(alignment: .leading, spacing: 16) {
                if !data.exercises.isEmpty {
                    VStack(spacing: 0) {
                        ForEach(Array(data.exercises.enumerated()), id: \.offset) { index, row in
                            if index > 0 { Palette.line2.frame(height: 1).padding(.horizontal, 16) }
                            NavigationLink(value: Route.exercise(name: row.exercise, range: store.range)) {
                                exercise(row)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .card(padding: 0)
                }
                if !data.cardio.isEmpty {
                    SectionHead("Cardio").padding(.top, 4)
                    VStack(spacing: 0) {
                        ForEach(Array(data.cardio.enumerated()), id: \.offset) { index, row in
                            if index > 0 { Palette.line2.frame(height: 1).padding(.horizontal, 16) }
                            cardio(row)
                        }
                    }
                    .card(padding: 0)
                }
            }
        }
    }

    private func exercise(_ row: ExerciseRow) -> some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text(row.exercise.capFirst)
                    .font(.text(16, .semibold))
                    .foregroundStyle(Palette.ink)
                    .lineLimit(2)
                Text("\(row.sessions) session\(row.sessions == 1 ? "" : "s") · \(Days.label(row.last))")
                    .font(.text(13, relativeTo: .footnote))
                    .foregroundStyle(Palette.muted)
                    .lineLimit(1)
            }
            Spacer(minLength: 8)
            if row.spark.count > 1 {
                Sparkline(values: row.spark).frame(width: 48, height: 26)
            }
            VStack(alignment: .trailing, spacing: 2) {
                Text((row.best ?? "").isEmpty ? "—" : row.best ?? "")
                    .font(.text(15, .semibold))
                    .monospacedDigit()
                    .foregroundStyle(Palette.ink)
                Text("best")
                    .font(.text(12, relativeTo: .caption))
                    .foregroundStyle(Palette.muted)
            }
            .frame(minWidth: 62, alignment: .trailing)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 13)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isButton)
    }

    private func cardio(_ row: CardioRow) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text(row.activity.capFirst)
                    .font(.text(16, .semibold))
                    .foregroundStyle(Palette.ink)
                Text("\(row.count) time\(row.count == 1 ? "" : "s") · last \(Days.label(row.last))")
                    .font(.text(13, relativeTo: .footnote))
                    .foregroundStyle(Palette.muted)
            }
            Spacer(minLength: 8)
            Text([row.distance, row.minutes].filter { !$0.isEmpty }.joined(separator: " · "))
                .font(.text(15, .semibold))
                .monospacedDigit()
                .foregroundStyle(Palette.ink2)
                .multilineTextAlignment(.trailing)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 13)
        .accessibilityElement(children: .combine)
    }
}
