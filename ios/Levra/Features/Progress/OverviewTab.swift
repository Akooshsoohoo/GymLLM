import SwiftUI

/// The Overview tab: the headline numbers, workouts over time, muscle groups, new
/// bests, body weight, the week, and how each main lift is moving.
struct OverviewTab: View {
    @Bindable var store: ProgressStore
    let data: ProgressOverview

    var body: some View {
        let totals = data.totals
        VStack(alignment: .leading, spacing: 16) {
            Grid(horizontalSpacing: 10, verticalSpacing: 10) {
                GridRow {
                    StatTile(label: "Workouts", value: String(totals.sessions))
                    StatTile(label: "Streak", value: String(data.streak), unit: data.streak == 1 ? "week" : "weeks")
                }
                GridRow {
                    StatTile(label: "Lifted", value: Numbers.short(totals.volume), unit: data.weightUnit)
                    cardioTile
                }
            }

            VStack(alignment: .leading, spacing: 14) {
                CardHead("Workouts per \(data.by)")
                SegmentedToggle(
                    options: [("day", "Day"), ("week", "Week"), ("month", "Month")],
                    selection: Binding(get: { data.by }, set: { store.by = $0 }),
                    label: "Group by", fill: true
                )
                PeriodBars(periods: data.perPeriod, unit: data.by)
            }
            .card()

            VStack(alignment: .leading, spacing: 14) {
                CardHead("Muscle groups")
                if data.tags.isEmpty {
                    quiet("No tagged exercises in this range.")
                } else {
                    TagBars(tags: data.tags)
                    quiet("Exercises logged per muscle. One exercise can count toward several.", size: 13)
                }
            }
            .card()

            if data.isEmptyRange {
                EmptyRange { store.setRange("all") }
            } else {
                bests
                bodyweight
                WeekCalendar(store: store, week: data.week, streak: data.streak, rules: data.restRules)
                lifts
                mostTrained
            }
        }
    }

    /// Time when there is any, else distance, else how many: what the site leads with.
    private var cardioTile: some View {
        let totals = data.totals
        if let (value, unit) = Self.split(totals.cardioMinutes) ?? Self.split(totals.cardioDistance) {
            return StatTile(label: "Cardio", value: value, unit: unit)
        }
        return StatTile(label: "Cardio", value: String(totals.cardio))
    }

    /// "24 mi" -> ("24", "mi"); "3 h 44 min" -> ("3 h 44", "min").
    private static func split(_ text: String) -> (String, String)? {
        guard !text.isEmpty else { return nil }
        guard let gap = text.lastIndex(of: " ") else { return (text, "") }
        return (String(text[..<gap]), String(text[text.index(after: gap)...]))
    }

    private func quiet(_ text: String, size: CGFloat = 15) -> some View {
        Text(text)
            .font(.text(size, relativeTo: size < 15 ? .footnote : .body))
            .foregroundStyle(Palette.muted)
            .fixedSize(horizontal: false, vertical: true)
    }

    // MARK: Bests and body weight

    private var bests: some View {
        VStack(alignment: .leading, spacing: 12) {
            CardHead("New personal bests")
            if data.prs.isEmpty {
                quiet("No new bests in this range yet. A best needs an earlier entry of the same exercise to beat.")
            } else {
                ForEach(Array(data.prs.enumerated()), id: \.offset) { index, best in
                    if index > 0 { Palette.line2.frame(height: 1) }
                    NavigationLink(value: Route.exercise(name: best.exercise, range: store.range)) {
                        HStack(alignment: .center, spacing: 12) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(best.exercise.capFirst)
                                    .font(.text(15, .semibold))
                                    .foregroundStyle(Palette.ink)
                                Text("\(Days.label(best.date)) · up from \(Numbers.plain(best.previous))")
                                    .font(.text(13, relativeTo: .footnote))
                                    .foregroundStyle(Palette.muted)
                            }
                            Spacer(minLength: 8)
                            Text(best.weight)
                                .font(.head(19))
                                .foregroundStyle(Palette.youInk)
                        }
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .card()
    }

    private var bodyweight: some View {
        VStack(alignment: .leading, spacing: 12) {
            CardHead(title: "Body weight") {
                if let weight = data.bodyweight {
                    Text(weight.latest)
                        .font(.text(15, .bold))
                        .foregroundStyle(Palette.ink)
                }
            }
            if let weight = data.bodyweight, weight.charted > 0 {
                if let change = weight.change, let since = weight.since {
                    ChangeBadge(
                        text: "\(Numbers.signed(change)) \(weight.unit) since \(Days.label(since))",
                        change: change, neutral: true
                    )
                }
                TrendLine(
                    points: weight.periods.compactMap { p in p.weight.map { .init(label: p.label, value: $0) } },
                    unit: weight.chartUnit, height: 180, label: "Body weight per \(data.by)"
                )
                quiet(
                    weight.chartUnit + (data.by == "day" ? "" : " · average of the \(data.by)'s readings")
                        + " · only you can see this",
                    size: 13
                )
            } else {
                quiet("Log your weight to see a trend. Only you can see it.")
            }
        }
        .card()
    }

    // MARK: Lifts

    @ViewBuilder
    private var lifts: some View {
        SectionHead(title: "Exercise progress") {
            Button("See all exercises ›") { store.section = .exercises }
                .buttonStyle(LinkButtonStyle(color: Palette.muted))
        }
        .padding(.top, 4)
        if data.lifts.isEmpty {
            quiet("Log an exercise with a weight in two or more sessions to see its progress here.").card()
        } else {
            ForEach(data.lifts, id: \.exercise) { lift in
                NavigationLink(value: Route.exercise(name: lift.exercise, range: store.range)) {
                    VStack(alignment: .leading, spacing: 12) {
                        VStack(alignment: .leading, spacing: 4) {
                            HStack {
                                Text(lift.exercise.capFirst)
                                    .font(.head(17))
                                    .foregroundStyle(Palette.ink)
                                Spacer(minLength: 8)
                                Image(systemName: "chevron.right")
                                    .font(.system(size: 12, weight: .bold))
                                    .foregroundStyle(Palette.muted2)
                            }
                            LiftTrend(lift: lift)
                        }
                        TrendLine(
                            points: SeriesPoint.weights(lift.series), unit: lift.unit,
                            label: "\(lift.exercise): top weight per session"
                        )
                    }
                    .card()
                }
                .buttonStyle(.plain)
            }
        }
    }

    private var mostTrained: some View {
        VStack(alignment: .leading, spacing: 12) {
            CardHead("Most trained")
            ForEach(Array(data.topExercises.enumerated()), id: \.offset) { index, item in
                if index > 0 { Palette.line2.frame(height: 1) }
                NavigationLink(value: Route.exercise(name: item.exercise, range: store.range)) {
                    HStack(alignment: .center, spacing: 12) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(item.exercise.capFirst)
                                .font(.text(15, .semibold))
                                .foregroundStyle(Palette.ink)
                            Text("Logged \(item.entries) time\(item.entries == 1 ? "" : "s") · last \(Days.label(item.last))")
                                .font(.text(13, relativeTo: .footnote))
                                .foregroundStyle(Palette.muted)
                        }
                        Spacer(minLength: 8)
                        Text((item.best ?? "").isEmpty ? "—" : item.best ?? "")
                            .font(.text(15, .semibold))
                            .monospacedDigit()
                            .foregroundStyle(Palette.ink2)
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
        .card()
    }
}
