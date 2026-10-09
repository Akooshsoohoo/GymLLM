import Charts
import SwiftUI

/// You beside a friend over a time range: totals, the lifts you both do, where
/// each of you puts the work, favourites, and sessions per week. Green is you,
/// clay is them. Mirrors templates/compare.html.
struct CompareView: View {
    @Environment(AppState.self) private var app
    let handle: String

    @State private var range = "30d"
    @State private var data: Comparison?
    @State private var error: String?

    private struct Key: Hashable {
        let range: String
        let changes: Int
    }

    private var first: String {
        data?.other.name.split(separator: " ").first.map(String.init) ?? "them"
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                BackLink()
                if let data { people(data) }
                SegmentedToggle(options: ProgressStore.ranges, selection: $range, label: "Time range", fill: true)
                if let error { ErrorBanner(message: error) }
                if let data, data.range == range {
                    content(data)
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
        .dismissesKeyboard()
        .refreshable { await load() }
        .task(id: Key(range: range, changes: app.changes)) { await load() }
    }

    private func load() async {
        do {
            data = try await app.api.get("/u/\(handle)/compare", query: ["range": range])
            error = nil
        } catch let failure {
            error = app.message(for: failure)
        }
    }

    private func people(_ data: Comparison) -> some View {
        HStack(spacing: 14) {
            HStack(spacing: 10) {
                Avatar(name: data.me?.name ?? app.firstName, url: data.me?.avatarUrl, size: 48, tone: .you)
                Text("You").font(.head(20)).foregroundStyle(Palette.ink)
            }
            Spacer(minLength: 0)
            Text("vs")
                .font(.text(14, .semibold, relativeTo: .subheadline))
                .foregroundStyle(Palette.muted)
            Spacer(minLength: 0)
            HStack(spacing: 10) {
                Text(first).font(.head(20)).foregroundStyle(Palette.ink).lineLimit(1)
                Avatar(name: data.other.name, url: data.other.avatarUrl, size: 48, tone: .friend)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("You vs \(data.other.name)")
        .accessibilityAddTraits(.isHeader)
    }

    @ViewBuilder
    private func content(_ data: Comparison) -> some View {
        if data.empty {
            EmptyRange { range = "all" }
        } else {
            totals(data.totals)
            shared(data.shared)
            muscles(data.muscles)
            favourites(data.favourites, name: data.other.name)
        }
        weekly(data.weekly, name: data.other.name)
    }

    // MARK: Totals

    private func totals(_ rows: [CompareTotal]) -> some View {
        VStack(spacing: 12) {
            ForEach(Array(rows.enumerated()), id: \.offset) { index, row in
                if index > 0 { Palette.line2.frame(height: 1) }
                HStack(alignment: .firstTextBaseline) {
                    number(row, mine: true).frame(maxWidth: .infinity, alignment: .leading)
                    Text(row.label)
                        .font(.text(13, .medium, relativeTo: .footnote))
                        .foregroundStyle(Palette.muted)
                        .multilineTextAlignment(.center)
                    number(row, mine: false).frame(maxWidth: .infinity, alignment: .trailing)
                }
                .accessibilityElement(children: .ignore)
                .accessibilityLabel("\(row.label): you \(Numbers.short(row.mine.rounded())), \(first) \(Numbers.short(row.theirs.rounded()))")
            }
        }
        .card()
    }

    private func number(_ row: CompareTotal, mine: Bool) -> some View {
        let leads = row.lead == (mine ? "mine" : "theirs")
        let unit = row.units.flatMap { $0.count == 2 ? $0[mine ? 0 : 1] : nil }
        return (Text(Numbers.short((mine ? row.mine : row.theirs).rounded()))
            .font(.head(24, .extrabold, relativeTo: .title2))
            .foregroundStyle(leads ? (mine ? Palette.youInk : Palette.friendInk) : Palette.ink)
            + Text(unit.map { " \($0)" } ?? "")
            .font(.text(13, .semibold, relativeTo: .footnote)).foregroundStyle(Palette.muted))
            .monospacedDigit()
            .lineLimit(1)
            .minimumScaleFactor(0.7)
    }

    // MARK: Lifts you both do

    private func shared(_ lifts: [SharedLift]) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            CardHead(title: "Lifts you both do") { legend }
            if lifts.isEmpty {
                Text("No exercise in common in this range.")
                    .font(.text(15))
                    .foregroundStyle(Palette.muted)
            } else {
                ForEach(lifts, id: \.exercise) { lift in
                    VStack(alignment: .leading, spacing: 6) {
                        HStack(alignment: .firstTextBaseline) {
                            Text(lift.exercise.capFirst)
                                .font(.text(15, .medium))
                                .foregroundStyle(Palette.ink)
                            Spacer(minLength: 8)
                            Text(gap(lift))
                                .font(.text(13, .medium, relativeTo: .footnote))
                                .monospacedDigit()
                                .foregroundStyle(Palette.ink2)
                                .multilineTextAlignment(.trailing)
                        }
                        splitBar(lift)
                        Text("\(lift.mine.sessions)× you · \(lift.theirs.sessions)× \(first)")
                            .font(.text(13, relativeTo: .footnote))
                            .foregroundStyle(Palette.muted)
                    }
                    .accessibilityElement(children: .combine)
                }
                Text("Best weight in this range. No gap is shown when the units differ.")
                    .font(.text(13, relativeTo: .footnote))
                    .foregroundStyle(Palette.muted)
            }
        }
        .card()
    }

    private func gap(_ lift: SharedLift) -> String {
        guard let a = lift.mine.value, let b = lift.theirs.value, !lift.unit.isEmpty else {
            let dash = "—"
            return "\(lift.mine.text.isEmpty ? dash : lift.mine.text) · \(lift.theirs.text.isEmpty ? dash : lift.theirs.text)"
        }
        var text = "\(Numbers.plain(a)) · \(Numbers.plain(b)) · "
        if let diff = lift.diff, diff > 0 {
            text += "\(lift.lead == "mine" ? "You" : first) +\(Numbers.plain(diff)) \(lift.unit)"
        } else {
            text += "tied"
        }
        return text
    }

    @ViewBuilder
    private func splitBar(_ lift: SharedLift) -> some View {
        if let a = lift.mine.value, let b = lift.theirs.value, a > 0, b > 0, !lift.unit.isEmpty {
            GeometryReader { box in
                let mine = (box.size.width - 3) * CGFloat(a / (a + b))
                HStack(spacing: 3) {
                    Capsule().fill(Palette.you).frame(width: max(mine, 6))
                    Capsule().fill(Palette.friend)
                }
            }
            .frame(height: 8)
        } else {
            Capsule().fill(Palette.track).frame(height: 8)
        }
    }

    private var legend: some View {
        HStack(spacing: 10) {
            legendDot(Palette.you, "You")
            legendDot(Palette.friend, first)
        }
    }

    private func legendDot(_ color: Color, _ label: String) -> some View {
        HStack(spacing: 5) {
            Circle().fill(color).frame(width: 8, height: 8)
            Text(label)
                .font(.text(12, .medium, relativeTo: .caption))
                .foregroundStyle(Palette.muted)
                .lineLimit(1)
        }
    }

    // MARK: Muscle split

    private func muscles(_ rows: [MuscleShare]) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            CardHead("Muscle split")
            if rows.isEmpty {
                Text("No tagged exercises in this range.")
                    .font(.text(15))
                    .foregroundStyle(Palette.muted)
            } else {
                Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 10) {
                    ForEach(rows, id: \.tag) { row in
                        GridRow {
                            Text(row.tag)
                                .font(.text(14, .medium, relativeTo: .subheadline))
                                .foregroundStyle(Palette.ink)
                                .lineLimit(1)
                            VStack(spacing: 3) {
                                share(row.mine, Palette.you)
                                share(row.theirs, Palette.friend)
                            }
                            Text("\(row.mine)% / \(row.theirs)%")
                                .font(.text(13, .medium, relativeTo: .footnote))
                                .monospacedDigit()
                                .foregroundStyle(Palette.muted)
                                .gridColumnAlignment(.trailing)
                        }
                        .accessibilityElement(children: .ignore)
                        .accessibilityLabel("\(row.tag): you \(row.mine) percent, \(first) \(row.theirs) percent")
                    }
                }
                Text("Share of each person's logged exercises.")
                    .font(.text(13, relativeTo: .footnote))
                    .foregroundStyle(Palette.muted)
            }
        }
        .card()
    }

    private func share(_ percent: Int, _ color: Color) -> some View {
        GeometryReader { box in
            Capsule().fill(Palette.track)
            Capsule().fill(color)
                .frame(width: percent > 0 ? max(box.size.width * CGFloat(percent) / 100, 6) : 0)
        }
        .frame(height: 7)
    }

    // MARK: Favourites

    private func favourites(_ both: CompareFavourites, name: String) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            CardHead("Favourites")
            HStack(alignment: .top, spacing: 14) {
                favouriteList("You", both.mine, mine: true)
                favouriteList(name, both.theirs, mine: false)
            }
            Text("Most-logged exercises. Filled numbers are in both lists.")
                .font(.text(13, relativeTo: .footnote))
                .foregroundStyle(Palette.muted)
        }
        .card()
    }

    private func favouriteList(_ who: String, _ items: [CompareFavourite], mine: Bool) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(who)
                .font(.text(13, .semibold, relativeTo: .footnote))
                .foregroundStyle(Palette.muted)
                .lineLimit(1)
            if items.isEmpty {
                Text("No lifts in this range.")
                    .font(.text(14, relativeTo: .subheadline))
                    .foregroundStyle(Palette.muted)
            }
            ForEach(Array(items.enumerated()), id: \.offset) { index, item in
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(String(index + 1))
                        .font(.text(12, .bold, relativeTo: .caption))
                        .monospacedDigit()
                        .foregroundStyle(item.shared ? (mine ? Palette.onYou : Palette.onFriend) : (mine ? Palette.youInk : Palette.friendInk))
                        .frame(width: 22, height: 22)
                        .background(
                            item.shared ? (mine ? Palette.you : Palette.friend) : (mine ? Palette.youTint : Palette.friendTint),
                            in: Circle()
                        )
                    Text(item.exercise.capFirst)
                        .font(.text(14, .medium, relativeTo: .subheadline))
                        .foregroundStyle(Palette.ink)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .accessibilityElement(children: .ignore)
                .accessibilityLabel("\(index + 1). \(item.exercise)\(item.shared ? ", in both lists" : "")")
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    // MARK: Sessions per week

    private func weekly(_ weeks: [WeekPair], name: String) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            CardHead(title: "Sessions per week") { legend }
            PairLines(weeks: weeks, other: name)
            Text("Last 12 weeks")
                .font(.text(13, relativeTo: .footnote))
                .foregroundStyle(Palette.muted)
        }
        .card()
    }
}
