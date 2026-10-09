import SwiftUI

/// Me: your profile as friends see it, and the way into Settings. Mirrors
/// your own templates/profile.html. Without a profile it offers to set one up.
struct MeView: View {
    @Environment(AppState.self) private var app
    @State private var profile: PersonProfile?
    @State private var error: String?
    @State private var editing: ProfileEditView.Mode?

    private struct Key: Hashable {
        let handle: String?
        let changes: Int
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                HStack {
                    Text("Me")
                        .font(.head(32, relativeTo: .largeTitle))
                        .foregroundStyle(Palette.ink)
                    Spacer()
                    NavigationLink(value: Route.settings) {
                        Image(systemName: "gearshape")
                            .font(.system(size: 17, weight: .semibold))
                            .foregroundStyle(Palette.ink)
                            .frame(width: 40, height: 40)
                            .background(Palette.surface, in: Circle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Settings")
                }
                if let error { ErrorBanner(message: error) }

                if let own = app.me?.profile {
                    ProfileHeader(
                        person: Person(handle: own.handle, name: own.name, avatarUrl: own.avatarUrl, bio: own.bio),
                        friendCount: profile?.friendCount ?? 0, own: true
                    )
                    Button("Edit profile") { editing = .edit }
                        .buttonStyle(.pill(.ghost, height: 44))
                    if let profile, profile.person.handle == own.handle {
                        ProfileBody(profile: profile)
                    }
                } else if app.me != nil {
                    noProfile
                }
            }
            .padding(.horizontal, Metrics.gutter)
            .padding(.top, 20)
            .padding(.bottom, 24)
        }
        .background(Palette.bg)
        .toolbar(.hidden, for: .navigationBar)
        .refreshable {
            await app.refreshMe()
            await load()
        }
        .task(id: Key(handle: app.me?.profile?.handle, changes: app.changes)) { await load() }
        .sheet(item: $editing) { mode in
            ProfileEditView(mode: mode, cancel: { editing = nil }) { _ in editing = nil }
                .presentationBackground(Palette.bg)
        }
    }

    private func load() async {
        guard let handle = app.me?.profile?.handle else {
            profile = nil
            return
        }
        do {
            profile = try await app.api.get("/u/\(handle)")
            error = nil
        } catch let failure {
            error = app.message(for: failure)
        }
    }

    private var noProfile: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 14) {
                Avatar(name: app.firstName, size: 56, tone: .you)
                VStack(alignment: .leading, spacing: 2) {
                    Text(app.firstName)
                        .font(.head(19))
                        .foregroundStyle(Palette.ink)
                    Text(app.me?.email ?? "")
                        .font(.text(13, .medium, relativeTo: .footnote))
                        .foregroundStyle(Palette.muted)
                        .lineLimit(1)
                        .truncationMode(.middle)
                }
            }
            Text("Set up a profile to see friends' workouts, trade high fives and compare stats.")
                .font(.text(15))
                .foregroundStyle(Palette.ink2)
                .fixedSize(horizontal: false, vertical: true)
            Button("Set up your profile") { editing = .setup }
                .buttonStyle(.pill(.primary, height: 44))
        }
        .card()
    }
}

extension ProfileEditView.Mode: Identifiable {
    var id: Self { self }
}
