import Charts
import SwiftUI

/// The charts on Progress, drawn with Swift Charts in the theme's colours: green
/// for what you did, the quiet line colours for the grid. The site draws the same
/// ones as SVG in static/app.js.

/// A count per period as bars, the current period in full green. A phone has room
/// for the last eight, as the site shows at this width.
struct PeriodBars: View {
    let periods: [PeriodCount]
    let unit: String

    private var shown: [PeriodCount] { Array(periods.suffix(8)) }

    var body: some View {
        let shown = shown
        Chart(Array(shown.enumerated()), id: \.offset) { index, period in
            BarMark(x: .value("Period", String(index)), y: .value("Workouts", period.sessions), width: .ratio(0.62))
                .foregroundStyle(period.current ? Palette.you : Palette.barPast)
                .cornerRadius(5)
                .accessibilityLabel(period.title)
                .accessibilityValue("\(period.sessions) workout\(period.sessions == 1 ? "" : "s")")
        }
        .chartXAxis {
            AxisMarks(values: shown.indices.map(String.init)) { value in
                AxisValueLabel {
                    if let key = value.as(String.self), let index = Int(key), shown.indices.contains(index) {
                        Text(Self.short(shown[index].label)).chartLabel()
                    }
                }
            }
        }
        .chartYAxis { countAxis }
        .chartYScale(domain: 0...max(shown.map(\.sessions).max() ?? 0, 4))
        .frame(height: 180)
        .accessibilityLabel("Workouts per \(unit), last \(shown.count) \(unit)s")
    }

    /// "Nov 2025" -> "Nov": eight labels have to fit across a phone.
    private static func short(_ label: String) -> String {
        let words = label.split(separator: " ")
        if words.count == 2, let year = words.last, year.count == 4, Int(year) != nil { return String(words[0]) }
        return label
    }
}

/// A value per session as a line with a dot on each point.
struct TrendLine: View {
    struct Point: Hashable {
        let label: String
        let value: Double
    }

    let points: [Point]
    let unit: String
    var height: CGFloat = 170
    let label: String

    var body: some View {
        Chart(Array(points.enumerated()), id: \.offset) { index, point in
            LineMark(x: .value("Session", index), y: .value("Value", point.value))
                .interpolationMethod(.linear)
                .lineStyle(StrokeStyle(lineWidth: 2.5, lineCap: .round, lineJoin: .round))
                .foregroundStyle(Palette.you)
            PointMark(x: .value("Session", index), y: .value("Value", point.value))
                .symbolSize(index == points.count - 1 ? 70 : 34)
                .foregroundStyle(Palette.you)
                .accessibilityLabel(point.label)
                .accessibilityValue("\(Numbers.plain(point.value)) \(unit)")
        }
        .chartXAxis {
            AxisMarks(values: ticks) { value in
                AxisValueLabel(anchor: anchor(value.as(Int.self))) {
                    if let index = value.as(Int.self), points.indices.contains(index) {
                        Text(points[index].label).chartLabel()
                    }
                }
            }
        }
        .chartXScale(domain: -0.25...(Double(max(points.count - 1, 1)) + 0.25))
        .chartYAxis { valueAxis }
        .chartYScale(domain: domain)
        .frame(height: height)
        .accessibilityLabel(label)
    }

    /// The first, the last, and one in the middle when there is room for it.
    private var ticks: [Int] {
        guard points.count > 1 else { return [0] }
        let last = points.count - 1
        return last >= 4 ? [0, last / 2, last] : [0, last]
    }

    private func anchor(_ index: Int?) -> UnitPoint {
        index == 0 ? .topLeading : index == points.count - 1 ? .topTrailing : .top
    }

    /// Room above and below, so a flat line sits in the middle and not on the axis.
    private var domain: ClosedRange<Double> {
        let values = points.map(\.value)
        guard let low = values.min(), let high = values.max() else { return 0...1 }
        let pad = max((high - low) * 0.18, max(abs(high), 1) * 0.04)
        return (low - pad)...(high + pad)
    }
}

/// A value per session as columns: volume on an exercise's page.
struct SessionColumns: View {
    let points: [TrendLine.Point]
    let unit: String
    let label: String

    var body: some View {
        Chart(Array(points.enumerated()), id: \.offset) { index, point in
            BarMark(x: .value("Session", String(index)), y: .value("Value", point.value), width: .ratio(0.62))
                .foregroundStyle(index == points.count - 1 ? Palette.you : Palette.barPast)
                .cornerRadius(4)
                .accessibilityLabel(point.label)
                .accessibilityValue("\(Numbers.plain(point.value)) \(unit)")
        }
        .chartXAxis {
            AxisMarks(values: ticks.map(String.init)) { value in
                AxisValueLabel {
                    if let key = value.as(String.self), let index = Int(key), points.indices.contains(index) {
                        Text(points[index].label).chartLabel()
                    }
                }
            }
        }
        .chartYAxis { valueAxis }
        .frame(height: 160)
        .accessibilityLabel(label)
    }

    private var ticks: [Int] {
        guard points.count > 1 else { return [0] }
        let last = points.count - 1
        return last >= 4 ? [0, last / 2, last] : [0, last]
    }
}

/// A row's worth of trend with no axes: top weight per session, oldest first.
struct Sparkline: View {
    let values: [Double]

    var body: some View {
        GeometryReader { box in
            let low = values.min() ?? 0, high = values.max() ?? 0
            let span = high - low
            let step = values.count > 1 ? box.size.width / CGFloat(values.count - 1) : 0
            let points = values.enumerated().map { index, value in
                CGPoint(
                    x: CGFloat(index) * step,
                    y: span > 0 ? box.size.height * (1 - CGFloat((value - low) / span)) : box.size.height / 2
                )
            }
            Path { path in
                guard let first = points.first else { return }
                path.move(to: first)
                points.dropFirst().forEach { path.addLine(to: $0) }
            }
            .stroke(Palette.you, style: StrokeStyle(lineWidth: 2, lineCap: .round, lineJoin: .round))
            if let last = points.last {
                Circle().fill(Palette.you).frame(width: 6, height: 6).position(last)
            }
        }
        .padding(3)
        .accessibilityHidden(true)
    }
}

/// How often each muscle came up, as bars against the most trained one.
struct TagBars: View {
    let tags: [TagCount]

    var body: some View {
        let top = max(tags.map(\.count).max() ?? 1, 1)
        Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 9) {
            ForEach(tags, id: \.tag) { row in
                GridRow {
                    Text(row.tag)
                        .font(.text(14, .medium, relativeTo: .subheadline))
                        .foregroundStyle(Palette.ink)
                        .lineLimit(1)
                    GeometryReader { box in
                        Capsule().fill(Palette.track)
                        Capsule().fill(Palette.you)
                            .frame(width: max(box.size.width * CGFloat(row.count) / CGFloat(top), 8))
                    }
                    .frame(height: 8)
                    Text(String(row.count))
                        .font(.text(14, .semibold, relativeTo: .subheadline))
                        .monospacedDigit()
                        .foregroundStyle(Palette.ink2)
                        .gridColumnAlignment(.trailing)
                }
                .accessibilityElement(children: .combine)
            }
        }
    }
}

private var countAxis: some AxisContent {
    AxisMarks(position: .leading, values: .automatic(desiredCount: 4)) { value in
        AxisGridLine(stroke: StrokeStyle(lineWidth: 1)).foregroundStyle(Palette.line2)
        AxisValueLabel {
            if let n = value.as(Int.self) { Text(String(n)).chartLabel() }
        }
    }
}

private var valueAxis: some AxisContent {
    AxisMarks(position: .leading, values: .automatic(desiredCount: 4)) { value in
        AxisGridLine(stroke: StrokeStyle(lineWidth: 1)).foregroundStyle(Palette.line2)
        AxisValueLabel {
            if let n = value.as(Double.self) { Text(Numbers.short(n)).chartLabel() }
        }
    }
}

private extension Text {
    func chartLabel() -> some View {
        self.font(.text(11, .medium, relativeTo: .caption2))
            .foregroundStyle(Palette.muted)
    }
}

extension SeriesPoint {
    /// The points a chart can draw: sessions whose weight led with a number.
    static func weights(_ series: [SeriesPoint]) -> [TrendLine.Point] {
        series.compactMap { p in p.weight.map { TrendLine.Point(label: Days.dayMonth(p.date), value: $0) } }
    }

    static func volumes(_ series: [SeriesPoint]) -> [TrendLine.Point] {
        series.filter { $0.weight != nil }.map { TrendLine.Point(label: Days.dayMonth($0.date), value: $0.volume ?? 0) }
    }
}
