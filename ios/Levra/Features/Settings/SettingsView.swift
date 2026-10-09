import SwiftUI
import UIKit

/// Light, dark, or whatever the phone is set to. Kept on the device.
enum Theme: String, CaseIterable {
    case light, dark, system

    static let key = "theme"

    private var style: UIUserInterfaceStyle {
        switch self {
        case .light: .light
        case .dark: .dark
        case .system: .unspecified
        }
    }

    /// Set on the window, so sheets and covers follow it too.
    @MainActor
    static func apply(_ raw: String) {
        let style = (Theme(rawValue: raw) ?? .system).style
        for case let scene as UIWindowScene in UIApplication.shared.connectedScenes {
            for window in scene.windows { window.overrideUserInterfaceStyle = style }
        }
    }
}

/// Settings: units, theme and the way out. Pushed from Me.
struct SettingsView: View {
    @Environment(AppState.self) private var app
    @AppStorage(Theme.key) private var theme = Theme.system.rawValue
    @State private var unit = "lbs"
    @State private var error: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                BackLink(title: "Me")
                Text("Settings")
                    .font(.head(32, relativeTo: .largeTitle))
                    .foregroundStyle(Palette.ink)
                if let error { ErrorBanner(message: error) }

                row("Weight unit", "Used when you don't say one") {
                    SegmentedToggle(
                        options: [("lbs", "lbs"), ("kg", "kg")], selection: $unit, label: "Weight unit"
                    )
                }
                VStack(alignment: .leading, spacing: 12) {
                    title("Theme", "System follows your phone")
                    SegmentedToggle(
                        options: [("light", "Light"), ("dark", "Dark"), ("system", "System")],
                        selection: $theme, label: "Theme", fill: true
                    )
                }
                .card()

                if let email = app.me?.email {
                    Text("Signed in as \(email)")
                        .font(.text(13, relativeTo: .footnote))
                        .foregroundStyle(Palette.muted)
                        .lineLimit(1)
                        .truncationMode(.middle)
                }
                Button("Sign out") { app.signOut() }
                    .buttonStyle(.pill(.white, height: 54, fill: true))
                if app.recording != nil {
                    Text("The workout you're recording stays on this phone until you sign back in.")
                        .font(.text(13, relativeTo: .footnote))
                        .foregroundStyle(Palette.muted)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(.horizontal, Metrics.gutter)
            .padding(.top, 8)
            .padding(.bottom, 24)
        }
        .background(Palette.bg)
        .toolbar(.hidden, for: .navigationBar)
        .onAppear { unit = app.weightUnit }
        .onChange(of: unit) { _, new in
            guard new != app.weightUnit else { return }
            Task {
                do {
                    try await app.setWeightUnit(new)
                    error = nil
                } catch let failure {
                    error = app.message(for: failure)
                    unit = app.weightUnit
                }
            }
        }
    }

    private func title(_ title: String, _ help: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title)
                .font(.head(17))
                .foregroundStyle(Palette.ink)
            Text(help)
                .font(.text(13, relativeTo: .footnote))
                .foregroundStyle(Palette.muted)
        }
    }

    private func row(_ name: String, _ help: String, @ViewBuilder control: () -> some View) -> some View {
        HStack {
            title(name, help)
            Spacer()
            control()
        }
        .card()
    }
}
