import CoreTransferable
import SwiftUI
import UniformTypeIdentifiers

/// The share image: the green poster at 4:5, drawn at 360×450 points and rendered
/// at 3× for a 1080×1350 picture. Name and date on top, the day's muscle icon top
/// right, the workout's name with its numbers under it, then one row per lift or
/// activity. Always the light green poster, whatever the theme, and never the
/// weigh-in. The site draws the same thing on a canvas (renderShareCard in
/// static/app.js).
struct SharePoster: View {
    struct Row: Hashable {
        let name: String
        let detail: String
        /// The weights of an exercise logged at several, on a line of their own.
        var sub = ""

        /// How much of the poster's room the row takes, in plain rows.
        var cost: Double { sub.isEmpty ? 1 : sub.count > 46 ? 2 : 1.5 }
    }

    static let size = CGSize(width: 360, height: 450)
    private static let edge: CGFloat = 27
    /// The rows get the room seven plain ones would take.
    private static let budget = 7.0

    let top: String
    let title: String
    let statLine: String
    let icon: String?
    let rows: [Row]

    init(day: DayDetail, name: String) {
        top = [name, Days.short(day.date)].filter { !$0.isEmpty }.joined(separator: " · ").uppercased()
        title = day.title
        statLine = day.statLine
        icon = day.icon
        rows = day.lines.map {
            Row(
                name: $0.exercise.capFirst + ($0.pr ? " · new best" : ""), detail: $0.detail,
                sub: $0.parts.joined(separator: ", ")
            )
        } + day.cardio.map {
            Row(name: $0.activity.capFirst, detail: $0.distance.isEmpty ? $0.duration : $0.distance)
        }
    }

    /// The rows that fit. Unless they all do, one plain row's room is kept for
    /// "+ 3 more".
    private var shown: [Row] {
        if rows.reduce(0, { $0 + $1.cost }) <= Self.budget { return rows }
        var used = 0.0
        var fit: [Row] = []
        for row in rows {
            if used + row.cost + 1 > Self.budget { break }
            used += row.cost
            fit.append(row)
        }
        return fit.isEmpty ? Array(rows.prefix(1)) : fit
    }

    var body: some View {
        let shown = shown
        let more = rows.count - shown.count
        ZStack(alignment: .topTrailing) {
            Palette.you
            // Where the site's canvas puts it: 504 of 1080 wide, 50 in and 166 down.
            MuscleIcon(icon, size: 168, glyph: Palette.you)
                .padding(.top, 55)
                .padding(.trailing, 17)
            VStack(alignment: .leading, spacing: 0) {
                HStack {
                    Text(top).lineLimit(1)
                    Spacer(minLength: 12)
                    Text("LEVRA")
                }
                .font(.custom(Font.TextWeight.bold.rawValue, fixedSize: 10))
                .tracking(1)

                Spacer(minLength: 0)

                Text(title)
                    .font(.custom(Font.HeadWeight.extrabold.rawValue, fixedSize: 50))
                    .tracking(-1.4)
                    .lineLimit(1)
                    .minimumScaleFactor(0.48)
                if !statLine.isEmpty {
                    Text(statLine)
                        .font(.custom(Font.TextWeight.semibold.rawValue, fixedSize: 14.5))
                        .lineLimit(1)
                        .padding(.top, 6)
                }
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(shown, id: \.self) { row in line(row) }
                    if more > 0 { line(Row(name: "+ \(more) more", detail: "")) }
                }
                .padding(.top, 14)
            }
            .padding(Self.edge)
        }
        .foregroundStyle(Palette.onYou)
        .frame(width: Self.size.width, height: Self.size.height)
        .environment(\.colorScheme, .light)
    }

    private func line(_ row: Row) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Palette.youRule.frame(height: 1)
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Text(row.name).lineLimit(1)
                Spacer(minLength: 0)
                Text(row.detail).lineLimit(1).layoutPriority(1)
            }
            .font(.custom(Font.TextWeight.semibold.rawValue, fixedSize: 12))
            .padding(.top, 7)
            if !row.sub.isEmpty {
                Text("↳ " + row.sub)
                    .font(.custom(Font.TextWeight.medium.rawValue, fixedSize: 10))
                    .lineLimit(2)
                    .padding(.top, 3)
            }
        }
        .padding(.bottom, 7)
    }

    /// The poster as a 1080×1350 picture.
    @MainActor
    func image() -> UIImage? {
        let renderer = ImageRenderer(content: self)
        renderer.scale = 3
        renderer.isOpaque = true
        return renderer.uiImage
    }
}

/// The picture as a PNG file, for the share sheet.
struct PosterFile: Transferable {
    let png: Data
    let name: String

    static var transferRepresentation: some TransferRepresentation {
        DataRepresentation(exportedContentType: .png) { $0.png }
            .suggestedFileName { $0.name }
    }
}

/// What "Share" opens: the picture as it will go out, and the way to send it.
struct ShareSheet: View {
    @Environment(\.dismiss) private var close
    let day: DayDetail
    let name: String

    @State private var picture: UIImage?
    @State private var failed = false

    var body: some View {
        VStack(spacing: 16) {
            HStack {
                Text("Share this workout")
                    .font(.head(19))
                    .foregroundStyle(Palette.ink)
                Spacer()
                Button("Done") { close() }
                    .buttonStyle(LinkButtonStyle(color: Palette.muted, size: 15))
            }
            if let picture {
                Image(uiImage: picture)
                    .resizable()
                    .scaledToFit()
                    .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
                    .accessibilityLabel("The picture that will be shared: \(day.title), \(Days.label(day.date, long: true))")
                if let png = picture.pngData() {
                    ShareLink(
                        item: PosterFile(png: png, name: "levra-\(day.date).png"),
                        preview: SharePreview(day.title, image: Image(uiImage: picture))
                    ) {
                        Text("Share picture")
                    }
                    .buttonStyle(.pill(.primary, height: 54, fill: true))
                }
            } else if failed {
                ErrorBanner(message: "We couldn't make the picture. Please try again.")
            } else {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            Text("Body weight and notes are never included when you share.")
                .font(.text(13, relativeTo: .footnote))
                .foregroundStyle(Palette.muted)
                .multilineTextAlignment(.center)
        }
        .padding(Metrics.gutter)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(Palette.bg)
        .presentationDetents([.large])
        .task {
            picture = SharePoster(day: day, name: name).image()
            failed = picture == nil
        }
    }
}
