import SwiftUI

// MARK: Buttons

/// The fully rounded button. `primary` is ink in light mode and green in dark.
struct PillButtonStyle: ButtonStyle {
    enum Kind { case primary, you, white, ghost }

    var kind: Kind = .primary
    var height: CGFloat = 48
    /// Stretch to the width on offer.
    var fill = false

    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.text(height >= 54 ? 17 : height >= 44 ? 16 : 14, .bold))
            .lineLimit(1)
            .padding(.horizontal, height >= 44 ? 22 : 14)
            .frame(height: height)
            .frame(maxWidth: fill ? .infinity : nil)
            .foregroundStyle(foreground)
            .background(background, in: Capsule())
            .overlay {
                if kind == .ghost { Capsule().strokeBorder(Palette.chipBorder, lineWidth: 1.5) }
            }
            .opacity(isEnabled ? 1 : 0.45)
            .scaleEffect(configuration.isPressed ? 0.97 : 1)
            .animation(.easeOut(duration: 0.15), value: configuration.isPressed)
    }

    private var foreground: Color {
        switch kind {
        case .primary: Palette.onPrimary
        case .you: Palette.onYou
        case .white, .ghost: Palette.ink
        }
    }

    private var background: Color {
        switch kind {
        case .primary: Palette.primary
        case .you: Palette.you
        case .white: Palette.surface
        case .ghost: .clear
        }
    }
}

extension ButtonStyle where Self == PillButtonStyle {
    static func pill(_ kind: PillButtonStyle.Kind = .primary, height: CGFloat = 48, fill: Bool = false)
        -> PillButtonStyle {
        PillButtonStyle(kind: kind, height: height, fill: fill)
    }
}

/// A quiet text link: "Details", "+ Add", "Remove".
struct LinkButtonStyle: ButtonStyle {
    var color: Color = Palette.youInk
    var size: CGFloat = 14

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.text(size, .semibold))
            .foregroundStyle(color)
            .opacity(configuration.isPressed ? 0.6 : 1)
            .contentShape(Rectangle())
    }
}

// MARK: Surfaces

extension View {
    /// A flat card on the page. Only the log card passes `shadow`.
    func card(radius: CGFloat = 20, padding: CGFloat = 16, shadow: Bool = false) -> some View {
        self
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Palette.surface, in: RoundedRectangle(cornerRadius: radius, style: .continuous))
            .shadow(color: shadow ? Palette.shadowCard : .clear, radius: 12, x: 0, y: 10)
    }
}

struct SectionHead<Trailing: View>: View {
    let title: String
    @ViewBuilder var trailing: Trailing

    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(title)
                .font(.head(19))
                .foregroundStyle(Palette.ink)
            Spacer(minLength: 12)
            trailing
        }
    }
}

extension SectionHead where Trailing == EmptyView {
    init(_ title: String) {
        self.init(title: title) { EmptyView() }
    }
}

struct StatTile: View {
    let label: String
    let value: String
    /// Said small after the value: "9 weeks", "105k lbs".
    var unit = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label)
                .font(.text(13, .medium, relativeTo: .footnote))
                .foregroundStyle(Palette.muted)
            (Text(value).font(.head(30, .extrabold, relativeTo: .title)).foregroundStyle(Palette.ink)
                + Text(unit.isEmpty ? "" : " \(unit)")
                .font(.text(14, .semibold, relativeTo: .subheadline)).foregroundStyle(Palette.muted))
                .lineLimit(1)
                .minimumScaleFactor(0.6)
        }
        .card(radius: 18, padding: 14)
        .accessibilityElement(children: .combine)
    }
}

/// An alert band for something that went wrong, in the user's words not ours.
struct ErrorBanner: View {
    let message: String

    var body: some View {
        Text(message)
            .font(.text(15, .medium))
            .foregroundStyle(Palette.dangerInk)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
            .background(Palette.dangerTint, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
    }
}

/// A quiet green band for something that went right: "Friend request sent to Sam."
struct NoteBanner: View {
    let message: String

    var body: some View {
        Text(message)
            .font(.text(15, .medium))
            .foregroundStyle(Palette.youInk)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
            .background(Palette.youTint, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
    }
}

/// "‹ Friends" at the top of a pushed screen, which hides the navigation bar.
struct BackLink: View {
    @Environment(\.dismiss) private var back
    var title = "Back"

    var body: some View {
        Button {
            back()
        } label: {
            Label(title, systemImage: "chevron.left").labelStyle(.titleAndIcon)
        }
        .buttonStyle(LinkButtonStyle(color: Palette.muted, size: 15))
        .accessibilityLabel(title == "Back" ? "Back" : "Back to \(title)")
    }
}

/// A labelled one-line field on the surface, as the day editor's title is.
struct FormField: View {
    let label: String
    @Binding var text: String
    var prompt = ""
    var prefix: String?
    var limit = 0
    var plain = false

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(label)
                .font(.text(13, .semibold, relativeTo: .footnote))
                .foregroundStyle(Palette.muted)
            HStack(spacing: 2) {
                if let prefix {
                    Text(prefix).font(.text(16, .medium)).foregroundStyle(Palette.muted)
                }
                TextField("", text: $text, prompt: Text(prompt).foregroundStyle(Palette.muted2))
                    .font(.text(16, .medium))
                    .foregroundStyle(Palette.ink)
                    .autocorrectionDisabled(plain)
                    .textInputAutocapitalization(plain ? .never : .sentences)
                    .accessibilityLabel(label)
                    .onChange(of: text) { _, new in
                        if limit > 0, new.count > limit { text = String(new.prefix(limit)) }
                    }
            }
            .padding(.horizontal, 14)
            .frame(height: 46)
            .background(Palette.surface, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        }
    }
}

// MARK: Small pieces

struct Badge: View {
    enum Tone { case best, saved }

    let text: String
    var tone: Tone = .best

    var body: some View {
        Text(tone == .best ? text.uppercased() : text)
            .font(.text(tone == .best ? 11 : 12, .bold, relativeTo: .caption2))
            .tracking(tone == .best ? 0.44 : 0)
            .foregroundStyle(tone == .best ? Palette.onYou : Palette.youInk)
            .padding(.horizontal, tone == .best ? 7 : 10)
            .padding(.vertical, tone == .best ? 3 : 4)
            .background(tone == .best ? Palette.you : Palette.youTint, in: Capsule())
            .fixedSize()
    }
}

/// A person's picture, or their initials on a tint: green for you, clay for others.
struct Avatar: View {
    enum Tone { case you, friend }

    let name: String
    var url: String?
    var size: CGFloat = 42
    var tone: Tone = .friend

    var body: some View {
        ZStack {
            Circle().fill(tone == .you ? Palette.youTint : Palette.friendTint)
            Text(initials)
                .font(.head(size * 0.4, .bold))
                .foregroundStyle(tone == .you ? Palette.youInk : Palette.friendInk)
            if let url, let parsed = URL(string: url) {
                AsyncImage(url: parsed) { image in
                    image.resizable().scaledToFill()
                } placeholder: {
                    Color.clear
                }
                .clipShape(Circle())
            }
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }

    private var initials: String {
        let letters = name.split(separator: " ").prefix(2).compactMap(\.first)
        return letters.isEmpty ? "?" : String(letters).uppercased()
    }
}

/// A suggestion chip: surface-2 with a chip border.
struct Chip: View {
    let text: String
    var active = false
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(text)
                .font(.text(14, .medium, relativeTo: .subheadline))
                .foregroundStyle(active ? Palette.onPrimary : Palette.ink)
                .padding(.horizontal, 14)
                .padding(.vertical, 9)
                .background(active ? Palette.primary : Palette.surface2, in: Capsule())
                .overlay { Capsule().strokeBorder(active ? .clear : Palette.chipBorder, lineWidth: 1.5) }
        }
        .buttonStyle(.plain)
    }
}

/// Two or three options on a `field` track; the chosen one lifts onto the surface.
struct SegmentedToggle: View {
    let options: [(value: String, label: String)]
    @Binding var selection: String
    var label: String
    /// Stretch across the width on offer, the options sharing it equally.
    var fill = false

    var body: some View {
        HStack(spacing: 0) {
            ForEach(options, id: \.value) { option in
                let on = option.value == selection
                Button {
                    selection = option.value
                } label: {
                    Text(option.label)
                        .font(.text(14, .semibold, relativeTo: .subheadline))
                        .foregroundStyle(on ? Palette.ink : Palette.muted)
                        .lineLimit(1)
                        .fixedSize()
                        .padding(.horizontal, fill ? 4 : 14)
                        .padding(.vertical, 8)
                        .frame(maxWidth: fill ? .infinity : nil)
                        .background {
                            if on {
                                Capsule().fill(Palette.surface)
                                    .shadow(color: Palette.shadowToggle, radius: 1.5, x: 0, y: 1)
                            }
                        }
                        .contentShape(Capsule())
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(on ? .isSelected : [])
            }
        }
        .padding(3)
        .background(Palette.field, in: Capsule())
        .animation(.easeOut(duration: 0.15), value: selection)
        .accessibilityElement(children: .contain)
        .accessibilityLabel(label)
    }
}

/// A value that edits in place. Filled, it sits on `field`; empty, it is a dashed
/// outline reading "+ weight".
struct ValuePill: View {
    let name: String
    @Binding var text: String
    var unit: String?
    var keyboard: UIKeyboardType = .default

    @FocusState private var focused: Bool

    private var placeholder: String { "+ \(name)" }
    private var isEmpty: Bool { text.isEmpty && !focused }

    var body: some View {
        HStack(spacing: 4) {
            // The hidden text sizes the pill to its value; the field sits on top.
            Text(text.isEmpty ? placeholder : text)
                .lineLimit(1)
                .padding(.trailing, 2)
                .hidden()
                .overlay(alignment: .leading) {
                    TextField(
                        "", text: $text,
                        prompt: Text(placeholder).foregroundStyle(Palette.muted)
                    )
                    .focused($focused)
                    .keyboardType(keyboard)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
                    .accessibilityLabel(name.capFirst)
                }
            if let unit, !text.isEmpty {
                Text(unit).foregroundStyle(Palette.muted)
            }
        }
        .font(.text(15, .semibold))
        .foregroundStyle(Palette.ink)
        .padding(.horizontal, 12)
        .frame(minHeight: 38)
        .background(isEmpty ? Color.clear : Palette.field, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .strokeBorder(
                    focused ? Palette.you : isEmpty ? Palette.dashed : .clear,
                    style: StrokeStyle(lineWidth: 1.5, dash: isEmpty ? [5, 4] : [])
                )
        }
        .contentShape(Rectangle())
        .onTapGesture { focused = true }
    }
}

/// A workout's lines: the name on the left, "225 lbs · 5×5" on the right.
struct SessionRows: View {
    let lines: [ExerciseLine]
    let cardio: [CardioEntry]

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(lines, id: \.self) { line in
                VStack(alignment: .leading, spacing: 2) {
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text(line.exercise.capFirst)
                            .font(.text(15, .medium))
                            .foregroundStyle(Palette.ink)
                        if line.pr { Badge(text: "New best") }
                        Spacer(minLength: 8)
                        if !line.detail.isEmpty { detail(line.detail) }
                    }
                    if !line.parts.isEmpty {
                        Text(line.parts.joined(separator: ", "))
                            .font(.text(14, relativeTo: .subheadline))
                            .foregroundStyle(Palette.ink2)
                    }
                }
            }
            ForEach(cardio) { c in
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(c.activity.capFirst)
                        .font(.text(15, .medium))
                        .foregroundStyle(Palette.ink)
                    Spacer(minLength: 8)
                    detail([c.distance, c.duration].filter { !$0.isEmpty }.joined(separator: " · "))
                }
            }
        }
    }

    private func detail(_ text: String) -> some View {
        Text(text)
            .font(.text(15, relativeTo: .body))
            .monospacedDigit()
            .foregroundStyle(Palette.ink2)
            .multilineTextAlignment(.trailing)
    }
}

/// "3 exercises · 1 cardio", counted the way the site's cards do.
func activityCount(lines: [ExerciseLine], cardio: [CardioEntry]) -> String {
    var parts: [String] = []
    if !lines.isEmpty { parts.append("\(lines.count) exercise\(lines.count == 1 ? "" : "s")") }
    if !cardio.isEmpty { parts.append("\(cardio.count) cardio") }
    return parts.joined(separator: " · ")
}

extension View {
    /// Put the keyboard away when this screen comes up: a search left focused on the
    /// screen below would otherwise keep it over the tab bar.
    func dismissesKeyboard() -> some View {
        onAppear {
            UIApplication.shared.sendAction(
                #selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil
            )
        }
    }
}

// MARK: Layout

/// Lays its children out in rows, wrapping like text. A child wider than the row
/// is held to the row's width.
struct FlowLayout: Layout {
    var spacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let placed = arrange(width: proposal.width ?? .infinity, subviews: subviews)
        return CGSize(width: proposal.width ?? placed.width, height: placed.height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let placed = arrange(width: bounds.width, subviews: subviews)
        for (subview, frame) in zip(subviews, placed.frames) {
            subview.place(
                at: CGPoint(x: bounds.minX + frame.minX, y: bounds.minY + frame.minY),
                proposal: ProposedViewSize(frame.size)
            )
        }
    }

    private func arrange(width: CGFloat, subviews: Subviews) -> (frames: [CGRect], width: CGFloat, height: CGFloat) {
        var frames: [CGRect] = []
        var x: CGFloat = 0, y: CGFloat = 0, rowHeight: CGFloat = 0, widest: CGFloat = 0
        for subview in subviews {
            var size = subview.sizeThatFits(ProposedViewSize(width: width, height: nil))
            size.width = min(size.width, width)
            if x > 0, x + size.width > width {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }
            frames.append(CGRect(origin: CGPoint(x: x, y: y), size: size))
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
            widest = max(widest, x - spacing)
        }
        return (frames, widest, y + rowHeight)
    }
}
