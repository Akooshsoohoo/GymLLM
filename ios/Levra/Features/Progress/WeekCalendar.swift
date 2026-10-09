import SwiftUI

/// The training calendar: one week, Monday to Sunday, stepped back and forth. A
/// logged day opens; an empty day that has happened flips between rest and not.
/// Under it, the rest schedule. Mirrors the week card of templates/progress.html.
struct WeekCalendar: View {
    @Environment(AppState.self) private var app
    @Bindable var store: ProgressStore
    let week: WeekCard
    let streak: Int
    let rules: [RestRule]

    @State private var editingRest = false
    @State private var picked: Set<Int> = []
    @State private var interval = 3
    @State private var anchor = Date()
    @State private var busy = false
    @State private var error: String?

    private static let weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    private var logged: Int { week.days.filter(\.logged).count }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 10) {
                arrow("chevron.left", to: week.previous, label: "Previous week")
                VStack(spacing: 2) {
                    Text(title)
                        .font(.head(17))
                        .foregroundStyle(Palette.ink)
                        .lineLimit(1)
                        .minimumScaleFactor(0.8)
                    Text("\(logged) of 7 days" + (week.isThisWeek && streak > 0 ? " · \(streak)-week streak" : ""))
                        .font(.text(13, .medium, relativeTo: .footnote))
                        .foregroundStyle(Palette.muted)
                }
                .frame(maxWidth: .infinity)
                .accessibilityElement(children: .combine)
                arrow("chevron.right", to: week.next, label: "Next week")
            }

            HStack(alignment: .top, spacing: 5) {
                ForEach(week.days, id: \.date) { day in tile(day) }
            }

            if !week.isThisWeek {
                Button("Back to this week") { store.week = nil }
                    .buttonStyle(LinkButtonStyle())
            }
            if let error { ErrorBanner(message: error) }

            Palette.line2.frame(height: 1)
            restEditor
        }
        .card()
        .disabled(busy)
    }

    private var title: String {
        var text = "Week of \(Days.dayMonth(week.start)) to \(Days.dayMonth(week.end))"
        let year = String(week.end.prefix(4))
        if year != String(Days.today().prefix(4)) { text += " \(year)" }
        return text
    }

    private func arrow(_ symbol: String, to other: String?, label: String) -> some View {
        Button {
            if let other { store.week = other }
        } label: {
            Image(systemName: symbol)
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(other == nil ? Palette.disabled : Palette.ink)
                .frame(width: 36, height: 36)
                .background(Palette.field, in: Circle())
        }
        .buttonStyle(.plain)
        .disabled(other == nil)
        .accessibilityLabel(label)
    }

    // MARK: Days

    @ViewBuilder
    private func tile(_ day: WeekDay) -> some View {
        let name = Days.label(day.date, long: true)
        if day.logged {
            NavigationLink(value: Route.day(date: day.date, session: nil, saved: nil)) { face(day) }
                .buttonStyle(.plain)
                .accessibilityLabel("\(name), \(stats(day).joined(separator: ", ")). Open this day")
        } else if !day.future {
            Button {
                setRest(day.date, to: !day.rest)
            } label: {
                face(day)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("\(name), \(day.rest ? "rest day. Tap to clear" : "nothing logged. Tap to mark as a rest day")")
        } else {
            face(day).accessibilityLabel("\(name)\(day.rest ? ", rest day" : "")")
        }
    }

    private func stats(_ day: WeekDay) -> [String] {
        guard day.logged else { return day.rest ? ["Rest"] : [] }
        var lines: [String] = []
        if day.exercises > 0 { lines += ["\(day.exercises) ex", "\(day.sets) set\(day.sets == 1 ? "" : "s")"] }
        if !day.cardio.isEmpty { lines.append(day.cardio) }
        if !day.bodyweight.isEmpty, !(day.exercises > 0 && !day.cardio.isEmpty) { lines.append(day.bodyweight) }
        return lines
    }

    private func face(_ day: WeekDay) -> some View {
        let ink = day.logged ? Palette.onYou : day.rest ? Palette.restInk : day.future ? Palette.muted2 : Palette.ink
        let fill = day.logged ? Palette.you : day.rest ? Palette.rest : Palette.field
        return VStack(spacing: 2) {
            Text(day.letter)
                .font(.text(11, .semibold, relativeTo: .caption2))
                .opacity(0.75)
            Text(String(day.day))
                .font(.head(17))
            VStack(spacing: 0) {
                ForEach(stats(day), id: \.self) { line in
                    Text(line)
                        .font(.text(10, .semibold, relativeTo: .caption2))
                        .lineLimit(1)
                        .minimumScaleFactor(0.7)
                }
            }
            .frame(maxHeight: .infinity, alignment: .top)
        }
        .foregroundStyle(ink)
        .padding(.vertical, 8)
        .padding(.horizontal, 2)
        .frame(maxWidth: .infinity)
        .frame(height: 92)
        .background(fill.opacity(day.future && !day.rest ? 0.5 : 1), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay {
            if day.today {
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .strokeBorder(day.logged ? Palette.ink : day.rest ? Palette.restInk : Palette.you, lineWidth: 2)
            }
        }
        .contentShape(Rectangle())
    }

    // MARK: Rest days

    private var restEditor: some View {
        VStack(alignment: .leading, spacing: 14) {
            Button {
                withAnimation(.easeOut(duration: 0.15)) { editingRest.toggle() }
            } label: {
                HStack(spacing: 8) {
                    Text("Rest days")
                        .font(.text(15, .semibold))
                        .foregroundStyle(Palette.ink)
                    if !rules.isEmpty {
                        Text(String(rules.count))
                            .font(.text(12, .bold, relativeTo: .caption))
                            .foregroundStyle(Palette.restInk)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 2)
                            .background(Palette.rest, in: Capsule())
                    }
                    Spacer()
                    Image(systemName: editingRest ? "chevron.up" : "chevron.down")
                        .font(.system(size: 12, weight: .bold))
                        .foregroundStyle(Palette.muted)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Rest days" + (rules.isEmpty ? "" : ", \(rules.count) rule\(rules.count == 1 ? "" : "s")"))
            .accessibilityHint(editingRest ? "Hides the rest schedule" : "Shows the rest schedule")

            if editingRest {
                Text("Tap an empty day above to mark it as rest, or set a schedule. Rest days show in blue and don't change your counts or streak.")
                    .font(.text(13, relativeTo: .footnote))
                    .foregroundStyle(Palette.muted)
                    .fixedSize(horizontal: false, vertical: true)

                ForEach(rules) { rule in
                    HStack(alignment: .firstTextBaseline) {
                        Text(describe(rule))
                            .font(.text(15, .medium))
                            .foregroundStyle(Palette.ink)
                        Spacer(minLength: 8)
                        Button("Remove") { remove(rule) }
                            .buttonStyle(LinkButtonStyle(color: Palette.muted, size: 13))
                            .accessibilityLabel("Remove rest rule: \(describe(rule))")
                    }
                }

                VStack(alignment: .leading, spacing: 10) {
                    label("Repeat on")
                    HStack(spacing: 5) {
                        ForEach(Array(Self.weekdays.enumerated()), id: \.offset) { index, name in
                            let on = picked.contains(index)
                            Button {
                                if on { picked.remove(index) } else { picked.insert(index) }
                            } label: {
                                Text(name)
                                    .font(.text(13, .semibold, relativeTo: .footnote))
                                    .foregroundStyle(on ? Palette.restInk : Palette.ink2)
                                    .frame(maxWidth: .infinity)
                                    .frame(height: 36)
                                    .background(on ? Palette.rest : Palette.field, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                            }
                            .buttonStyle(.plain)
                            .accessibilityAddTraits(on ? .isSelected : [])
                        }
                    }
                    Button("Add weekly rest days") {
                        add(RestRuleRequest(kind: "weekdays", weekdays: picked.sorted()))
                    }
                    .buttonStyle(.pill(.ghost, height: 40))
                    .disabled(picked.isEmpty)
                }

                VStack(alignment: .leading, spacing: 10) {
                    label("Or every few days")
                    Stepper(value: $interval, in: 2...60) {
                        Text("Every \(interval) days")
                            .font(.text(15, .medium))
                            .foregroundStyle(Palette.ink)
                    }
                    DatePicker(selection: $anchor, displayedComponents: .date) {
                        Text("Starting")
                            .font(.text(15, .medium))
                            .foregroundStyle(Palette.ink)
                    }
                    Button("Add") {
                        add(RestRuleRequest(kind: "interval", intervalDays: interval, anchorDate: Days.iso(anchor)))
                    }
                    .buttonStyle(.pill(.ghost, height: 40))
                    .accessibilityLabel("Add rest every \(interval) days")
                }
            }
        }
    }

    private func label(_ text: String) -> some View {
        Text(text)
            .font(.text(13, .semibold, relativeTo: .footnote))
            .foregroundStyle(Palette.muted)
    }

    private func describe(_ rule: RestRule) -> String {
        if rule.kind == "weekdays" {
            let names = (rule.weekdays ?? []).filter { Self.weekdays.indices.contains($0) }.map { Self.weekdays[$0] }
            return "Every " + names.joined(separator: ", ")
        }
        return "Every \(rule.intervalDays ?? 0) days" + (rule.anchorDate.map { ", from \(Days.label($0))" } ?? "")
    }

    private func setRest(_ date: String, to rest: Bool) {
        change { let _: RestDay = try await app.api.put("/rest/day/\(date)", RestDayRequest(rest: rest)) }
    }

    private func add(_ rule: RestRuleRequest) {
        change {
            let _: RestRules = try await app.api.post("/rest/rules", rule)
            picked = []
        }
    }

    private func remove(_ rule: RestRule) {
        change { let _: RestRules = try await app.api.delete("/rest/rules/\(rule.id)") }
    }

    /// Run one change, then have Progress (and Home's week) load again.
    private func change(_ work: @escaping () async throws -> Void) {
        busy = true
        Task {
            do {
                try await work()
                error = nil
                app.didChange()
            } catch let failure {
                error = app.message(for: failure)
            }
            busy = false
        }
    }
}
