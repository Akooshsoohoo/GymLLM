import SwiftUI

/// Signed out: what Levra does in one picture, then "Continue with Google".
struct WelcomeView: View {
    @Environment(AppState.self) private var app
    @State private var busy = false
    @State private var error: String?

    var body: some View {
        GeometryReader { screen in
            VStack(spacing: 0) {
                photo
                    .frame(height: min(470, screen.size.height * 0.5))
                VStack(alignment: .leading, spacing: 14) {
                    BrandMark()
                    Text("Log your workout like you'd text a friend.")
                        .font(.head(34, relativeTo: .largeTitle))
                        .tracking(-0.68)
                        .lineSpacing(-4)
                        .foregroundStyle(Palette.ink)
                        .fixedSize(horizontal: false, vertical: true)
                    Text("Lifting, running, yoga, a walk home. Just say what you did and we'll keep track.")
                        .font(.text(16))
                        .foregroundStyle(Palette.ink2)
                        .fixedSize(horizontal: false, vertical: true)
                    Spacer(minLength: 12)
                    if let error { ErrorBanner(message: error) }
                    Button(action: continueWithGoogle) {
                        HStack(spacing: 10) {
                            Image(.googleMark)
                                .resizable()
                                .frame(width: 14, height: 14)
                                .frame(width: 20, height: 20)
                                .background(Palette.bg, in: Circle())
                            Text("Continue with Google")
                        }
                    }
                    .buttonStyle(.pill(.primary, height: 56, fill: true))
                    Text("Free. Private until you add friends.")
                        .font(.text(13, relativeTo: .footnote))
                        .foregroundStyle(Palette.muted)
                        .frame(maxWidth: .infinity)
                    legal
                    #if DEBUG
                    devAccounts
                    #endif
                }
                .padding(.horizontal, 28)
                .padding(.top, 28)
                .padding(.bottom, 16)
            }
        }
        .ignoresSafeArea(edges: .top)
        .background(Palette.bg)
        .disabled(busy)
    }

    /// Stands in for a real photo (friends mid-workout, candid, warm light), with a
    /// sentence going in and a logged workout coming out.
    private var photo: some View {
        ZStack(alignment: .bottom) {
            LinearGradient(
                stops: [
                    .init(color: Palette.friendTint, location: 0),
                    .init(color: Palette.line2, location: 0.55),
                    .init(color: Palette.line, location: 1),
                ],
                startPoint: .topLeading, endPoint: .bottomTrailing
            )
            RadialGradient(
                colors: [Palette.friend.opacity(0.4), .clear],
                center: UnitPoint(x: 0.9, y: 0.1), startRadius: 0, endRadius: 280
            )
            RadialGradient(
                colors: [Palette.you.opacity(0.55), .clear],
                center: UnitPoint(x: 0.18, y: 1), startRadius: 0, endRadius: 320
            )
            VStack(alignment: .trailing, spacing: 10) {
                Text("benched 135 for 3 sets of 8, then ran 2 miles")
                    .font(.text(15, .medium))
                    .foregroundStyle(Palette.onYou)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 10)
                    .background(
                        Palette.you,
                        in: UnevenRoundedRectangle(
                            topLeadingRadius: 18, bottomLeadingRadius: 18, bottomTrailingRadius: 4,
                            topTrailingRadius: 18, style: .continuous
                        )
                    )
                    .padding(.leading, 40)
                VStack(spacing: 10) {
                    demoRow("Barbell bench press", "3 × 8 · 135 lbs")
                    demoRow("Running", "2 miles")
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 14)
                .background(Palette.surface, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
                .shadow(color: Palette.shadowCard, radius: 12, x: 0, y: 10)
            }
            .padding(.horizontal, 24)
            .padding(.bottom, 28)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("Example: a typed sentence becomes a logged workout")
        }
        .clipped()
    }

    /// The terms and the privacy policy, on the website.
    private var legal: some View {
        let terms = app.api.page("terms").absoluteString
        let privacy = app.api.page("privacy").absoluteString
        let line = "By continuing you agree to the [Terms](\(terms)) and the [Privacy Policy](\(privacy))."
        return Text((try? AttributedString(markdown: line)) ?? AttributedString(line))
            .font(.text(12, relativeTo: .caption))
            .foregroundStyle(Palette.muted)
            .tint(Palette.ink2)
            .multilineTextAlignment(.center)
            .frame(maxWidth: .infinity)
    }

    private func demoRow(_ name: String, _ detail: String) -> some View {
        HStack {
            Text(name).font(.text(15, .medium)).foregroundStyle(Palette.ink)
            Spacer(minLength: 8)
            Text(detail).font(.text(15)).monospacedDigit().foregroundStyle(Palette.ink2)
        }
    }

    private func continueWithGoogle() {
        run {
            guard let token = try await GoogleAuth.idToken() else { return }
            try await app.signIn(googleIDToken: token)
        }
    }

    private func run(_ work: @escaping () async throws -> Void) {
        busy = true
        error = nil
        Task {
            do {
                try await work()
            } catch let failure {
                error = app.message(for: failure)
            }
            busy = false
        }
    }

    #if DEBUG
    /// The seeded accounts of the local server (POST /auth/dev), and a blank one.
    /// Debug builds only.
    private var devAccounts: some View {
        HStack(spacing: 8) {
            Text("Dev")
                .font(.text(13, .medium, relativeTo: .footnote))
                .foregroundStyle(Palette.muted)
            ForEach(["alex", "sam", "jordan"], id: \.self) { slug in
                Button(slug.capFirst) {
                    run { try await app.signIn(devAccount: slug) }
                }
                .buttonStyle(.pill(.ghost, height: 34))
            }
            // Somebody with no profile and nothing logged, a new one each time.
            Button("New") {
                let tag = String(UUID().uuidString.lowercased().filter { $0 != "-" }.prefix(8))
                run { try await app.signIn(devAccount: "new-\(tag)") }
            }
            .buttonStyle(.pill(.ghost, height: 34))
            .accessibilityLabel("New person")
        }
        .frame(maxWidth: .infinity)
    }
    #endif
}
