import SwiftUI
import UIKit

/// One of the site's muscle icons: a figure with the muscles a day worked filled in,
/// in the colour around it. Drawn from static/muscle-icons.js by
/// ios/scripts/muscle_icons.py; the server picks which (`icon` on a day).
struct MuscleIcon: View {
    private let name: String
    private let hasGlyph: Bool
    let size: CGFloat
    /// The colour of an activity's badge glyph: what the icon sits on.
    let glyph: Color

    init(_ icon: String?, size: CGFloat, glyph: Color) {
        // An icon newer than this build falls back to the whole figure.
        let name = "muscle-\(icon ?? "full")"
        self.name = UIImage(named: name) == nil ? "muscle-full" : name
        hasGlyph = UIImage(named: "\(self.name)-glyph") != nil
        self.size = size
        self.glyph = glyph
    }

    var body: some View {
        ZStack {
            Image(name).resizable()
            if hasGlyph {
                Image("\(name)-glyph").resizable().foregroundStyle(glyph)
            }
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }
}
