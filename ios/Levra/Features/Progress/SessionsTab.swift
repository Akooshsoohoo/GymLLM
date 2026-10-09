import SwiftUI

/// The Sessions tab: every workout in the range under month headings, and a box
/// that keeps the ones holding every word typed. Mirrors templates/search.html.
struct SessionsTab: View {
    @Bindable var store: ProgressStore
    let data: SessionList

    private var searching: Bool { !store.query.trimmed.isEmpty }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 8) {
                Image(systemName: "magnifyingglass")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(Palette.muted)
                TextField(
                    "", text: $store.query,
                    prompt: Text("Search exercises, names, dates").foregroundStyle(Palette.muted2)
                )
                .font(.text(16, .medium))
                .foregroundStyle(Palette.ink)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
                .submitLabel(.search)
                .accessibilityLabel("Search your workouts")
                if !store.query.isEmpty {
                    Button {
                        store.query = ""
                    } label: {
                        Image(systemName: "xmark.circle.fill").foregroundStyle(Palette.muted2)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Clear search")
                }
            }
            .padding(.horizontal, 14)
            .frame(height: 46)
            .background(Palette.surface, in: RoundedRectangle(cornerRadius: 14, style: .continuous))

            if data.months.isEmpty {
                if searching {
                    EmptyNote(text: "No workouts match \"\(store.query.trimmed)\".") {
                        Button("Clear search") { store.query = "" }.buttonStyle(.pill(.ghost, height: 44))
                    }
                } else {
                    EmptyRange { store.setRange("all") }
                }
            } else {
                if searching {
                    Text("\(data.shown) workout\(data.shown == 1 ? "" : "s") found")
                        .font(.text(13, .medium, relativeTo: .footnote))
                        .foregroundStyle(Palette.muted)
                }
                ForEach(data.months, id: \.key) { month in
                    HStack(alignment: .firstTextBaseline) {
                        Text(month.label)
                            .font(.head(19))
                            .foregroundStyle(Palette.ink)
                        Spacer()
                        Text("\(month.days.count) session\(month.days.count == 1 ? "" : "s")")
                            .font(.text(13, .medium, relativeTo: .footnote))
                            .foregroundStyle(Palette.muted)
                    }
                    .padding(.top, 4)
                    .accessibilityElement(children: .combine)
                    .accessibilityAddTraits(.isHeader)
                    ForEach(month.days, id: \.self) { tile in
                        NavigationLink(value: Route.day(date: tile.date, session: tile.session, saved: nil)) {
                            SessionTileView(tile: tile)
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
        }
    }
}

private struct SessionTileView: View {
    let tile: SessionTile

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(tile.title)
                    .font(.head(17))
                    .foregroundStyle(Palette.ink)
                    .lineLimit(1)
                Spacer(minLength: 8)
                Text(Days.label(tile.date))
                    .font(.text(13, .medium, relativeTo: .footnote))
                    .foregroundStyle(Palette.muted)
            }
            ForEach(tile.lines, id: \.self) { line in
                VStack(alignment: .leading, spacing: 2) {
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text(line.name.capFirst)
                            .font(.text(15, .medium))
                            .foregroundStyle(Palette.ink)
                        if line.pr { Badge(text: "New best") }
                        Spacer(minLength: 8)
                        Text(line.detail)
                            .font(.text(15))
                            .monospacedDigit()
                            .foregroundStyle(Palette.ink2)
                            .multilineTextAlignment(.trailing)
                    }
                    if !line.parts.isEmpty {
                        Text(line.parts.joined(separator: ", "))
                            .font(.text(14, relativeTo: .subheadline))
                            .foregroundStyle(Palette.ink2)
                    }
                }
            }
            if let weight = tile.bodyweight {
                Text("Body weight \(weight)")
                    .font(.text(13, relativeTo: .footnote))
                    .foregroundStyle(Palette.muted)
            }
        }
        .card()
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isButton)
    }
}
