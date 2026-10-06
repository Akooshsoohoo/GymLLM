import SwiftUI

@main
struct LevraApp: App {
    @State private var app = AppState()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(app)
                .tint(Palette.you)
                .onOpenURL { GoogleAuth.handle($0) }
        }
    }
}

/// Welcome when signed out, the tabs when signed in.
struct RootView: View {
    @Environment(AppState.self) private var app

    var body: some View {
        ZStack {
            Palette.bg.ignoresSafeArea()
            switch app.phase {
            case .launching:
                BrandMark(size: 17)
            case .signedOut:
                WelcomeView()
                    .transition(.opacity)
            case .signedIn:
                MainTabs()
                    .transition(.opacity)
            }
        }
        .animation(.easeOut(duration: 0.2), value: app.phase)
        .task { await app.start() }
    }
}

/// The green dot and the name.
struct BrandMark: View {
    var size: CGFloat = 17

    var body: some View {
        HStack(spacing: 8) {
            Circle().fill(Palette.you).frame(width: 14, height: 14)
            Text("Levra")
                .font(.head(size))
                .foregroundStyle(Palette.ink)
        }
        .accessibilityElement(children: .combine)
    }
}
