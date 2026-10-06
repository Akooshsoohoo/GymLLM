import SwiftUI

/// The green "This week" card on Home: days logged, the streak, seven bars.
struct WeekHero: View {
    let week: [WeekDay]
    let streak: Int

    private var logged: Int { week.filter(\.logged).count }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("This week")
                        .font(.text(14, .semibold, relativeTo: .subheadline))
                    (Text("\(logged) ").font(.head(44, .extrabold, relativeTo: .largeTitle))
                        + Text("of 7 days").font(.head(22, .semibold, relativeTo: .title2)))
                        .tracking(-0.5)
                }
                Spacer()
                if streak > 0 {
                    Text("\(streak)-week streak")
                        .font(.text(13, .semibold, relativeTo: .footnote))
                        .foregroundStyle(Palette.youPillText)
                        .padding(.horizontal, 12)
                        .padding(.vertical, 7)
                        .background(Palette.onYou, in: Capsule())
                }
            }
            HStack(spacing: 6) {
                ForEach(week, id: \.date) { day in
                    RoundedRectangle(cornerRadius: 4)
                        .fill(day.logged ? Palette.onYou : day.rest ? Palette.rest : Palette.youFaint)
                        .frame(height: 8)
                }
            }
            .accessibilityHidden(true)
        }
        .foregroundStyle(Palette.onYou)
        .padding(20)
        .background(Palette.you, in: RoundedRectangle(cornerRadius: 26, style: .continuous))
        .accessibilityElement(children: .combine)
    }
}

/// "This week" as seven circles, on the Log screen.
struct WeekDots: View {
    let week: [WeekDay]
    let streak: Int

    private var logged: Int { week.filter(\.logged).count }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .firstTextBaseline) {
                Text("This week")
                    .font(.head(17))
                    .foregroundStyle(Palette.ink)
                Spacer()
                Text("\(logged) of 7 days" + (streak > 0 ? " · \(streak)-week streak" : ""))
                    .font(.text(13, .medium, relativeTo: .footnote))
                    .foregroundStyle(Palette.muted)
            }
            HStack(spacing: 0) {
                ForEach(week, id: \.date) { day in
                    VStack(spacing: 6) {
                        dot(day)
                        Text(day.letter)
                            .font(.text(12, .semibold, relativeTo: .caption))
                            .foregroundStyle(day.today ? Palette.ink : Palette.muted2)
                    }
                    .frame(maxWidth: .infinity)
                }
            }
            .accessibilityHidden(true)
        }
        .card()
        .accessibilityElement(children: .combine)
    }

    @ViewBuilder
    private func dot(_ day: WeekDay) -> some View {
        let outline = StrokeStyle(lineWidth: 2, dash: [4, 3])
        if day.logged {
            Circle().fill(Palette.you).frame(width: 34, height: 34)
        } else if day.rest {
            Circle().fill(Palette.rest).frame(width: 34, height: 34)
                .overlay { if day.today { Circle().strokeBorder(Palette.restInk, style: outline) } }
        } else if day.today {
            Circle().strokeBorder(Palette.you, style: outline).frame(width: 34, height: 34)
        } else {
            Circle().fill(Palette.track).frame(width: 34, height: 34)
        }
    }
}

extension Quota {
    /// "17 free logs left today"
    var leftText: String { "\(left) free log\(left == 1 ? "" : "s") left today" }
}
