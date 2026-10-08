import SwiftUI

/// Bricolage Grotesque for headings and numbers, Instrument Sans for everything
/// else. Both are bundled (Resources/Fonts, listed under UIAppFonts). Sizes are the
/// site's, and scale with Dynamic Type.
extension Font {
    enum HeadWeight: String {
        case semibold = "BricolageGrotesque-SemiBold"
        case bold = "BricolageGrotesque-Bold"
        case extrabold = "BricolageGrotesque-ExtraBold"
    }

    enum TextWeight: String {
        case regular = "InstrumentSans-Regular"
        case medium = "InstrumentSans-Medium"
        case semibold = "InstrumentSans-SemiBold"
        case bold = "InstrumentSans-Bold"
    }

    static func head(
        _ size: CGFloat, _ weight: HeadWeight = .bold, relativeTo style: TextStyle = .title2
    ) -> Font {
        .custom(weight.rawValue, size: size, relativeTo: style)
    }

    static func text(
        _ size: CGFloat, _ weight: TextWeight = .regular, relativeTo style: TextStyle = .body
    ) -> Font {
        .custom(weight.rawValue, size: size, relativeTo: style)
    }
}

enum Metrics {
    /// Screen side padding.
    static let gutter: CGFloat = 20
    /// Space the floating tab bar takes at the bottom of a scrolling screen.
    static let tabBarHeight: CGFloat = 64
}
