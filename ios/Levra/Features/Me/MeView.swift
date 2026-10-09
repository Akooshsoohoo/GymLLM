import SwiftUI

/// Me: your profile as friends see it, then your units and the way out. Mirrors
/// your own templates/profile.html. Without a profile it offers to set one up.
struct MeView: View {
    @Environment(AppState.self) private var app
    @State private var profile: PersonProfile?
    @State private var unit = "lbs"
    @State private var error: String?
    @State private var editing: ProfileEditView.Mode?

    private struct Key: Hashable {
        let handle: String?
        let changes: Int
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("Me")
                    .font(.head(32, relativeTo: .largeTitle))
                    .foregroundStyle(Palette.ink)
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

                settings
                Button("Sign out") { app.signOut() }
                    .buttonStyle(.pill(.white, height: 54, fill: true))
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

    private var settings: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHead("Settings")
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Weight unit")
                        .font(.head(17))
                        .foregroundStyle(Palette.ink)
                    Text("Used when you don't say one")
                        .font(.text(13, relativeTo: .footnote))
                        .foregroundStyle(Palette.muted)
                }
                Spacer()
                SegmentedToggle(
                    options: [("lbs", "lbs"), ("kg", "kg")], selection: $unit, label: "Weight unit"
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
        }
    }
}

extension ProfileEditView.Mode: Identifiable {
    var id: Self { self }
}
