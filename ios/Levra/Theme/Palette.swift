import SwiftUI

/// Theme "Fern". Every colour is a set in Assets.xcassets with a light and a dark
/// value, generated from the tokens at the top of static/style.css by
/// ios/scripts/colors.py and named the same. Green (`you`) is the user, clay
/// (`friend`) is other people. Views take colours from here, never a hex value.
enum Palette {
    static let bg = Color(.bg)
    static let bgClear = Color(.bgClear)
    static let surface = Color(.surface)
    static let surface2 = Color(.surface2)
    static let field = Color(.field)
    static let ink = Color(.ink)
    static let ink2 = Color(.ink2)
    static let muted = Color(.muted)
    static let muted2 = Color(.muted2)
    static let line = Color(.line)
    static let line2 = Color(.line2)
    static let chipBorder = Color(.chipBorder)
    static let dashed = Color(.dashed)
    static let track = Color(.track)
    static let disabled = Color(.disabled)

    static let you = Color(.you)
    static let onYou = Color(.onYou)
    static let youFaint = Color(.youFaint)
    static let youRule = Color(.youRule)
    static let youPillText = Color(.youPillText)
    static let youTint = Color(.youTint)
    static let youInk = Color(.youInk)

    static let friend = Color(.friend)
    static let onFriend = Color(.onFriend)
    static let friendTint = Color(.friendTint)
    static let friendInk = Color(.friendInk)

    static let primary = Color(.primary)
    static let onPrimary = Color(.onPrimary)
    static let tabBg = Color(.tabBg)

    static let danger = Color(.danger)
    static let dangerTint = Color(.dangerTint)
    static let dangerInk = Color(.dangerInk)
    static let neutralTint = Color(.neutralTint)
    static let neutralInk = Color(.neutralInk)
    static let rest = Color(.rest)
    static let restInk = Color(.restInk)

    static let shadowCard = Color(.shadowCard)
    static let shadowToggle = Color(.shadowToggle)
}
