import SwiftUI

/// Set up your profile, or change it: a handle, a name, a line about you. Mirrors
/// templates/profile_edit.html. Setup is what the Friends tab shows until there is
/// a profile; editing comes up as a sheet from Me.
struct ProfileEditView: View {
    enum Mode { case setup, edit }

    @Environment(AppState.self) private var app
    let mode: Mode
    var cancel: (() -> Void)?
    /// Saved. True when this made the profile.
    let done: (Bool) -> Void

    @State private var draft: ProfileDraft?
    @State private var error: String?
    @State private var saving = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                HStack(alignment: .firstTextBaseline) {
                    Text(mode == .setup ? "Set up your profile" : "Edit profile")
                        .font(.head(mode == .setup ? 32 : 26, relativeTo: .largeTitle))
                        .foregroundStyle(Palette.ink)
                    Spacer(minLength: 8)
                    if let cancel {
                        Button("Cancel", action: cancel)
                            .buttonStyle(LinkButtonStyle(color: Palette.muted, size: 16))
                    }
                }
                if mode == .setup {
                    Text("Friends find you by your handle. They see the workouts you share with them, never your notes or your body weight. Logging works the same with or without a profile.")
                        .font(.text(15))
                        .foregroundStyle(Palette.ink2)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if let error { ErrorBanner(message: error) }
                if draft != nil {
                    form
                } else if error == nil {
                    ProgressView()
                        .frame(maxWidth: .infinity)
                        .padding(.top, 40)
                } else {
                    Button("Try again") { Task { await load() } }
                        .buttonStyle(.pill(.white))
                }
            }
            .padding(.horizontal, Metrics.gutter)
            .padding(.top, 20)
            .padding(.bottom, 28)
        }
        .scrollDismissesKeyboard(.interactively)
        .background(Palette.bg)
        .task { await load() }
    }

    private var form: some View {
        let binding = Binding(
            get: { draft ?? ProfileDraft(handle: "", name: "", bio: "") },
            set: { draft = $0 }
        )
        return VStack(alignment: .leading, spacing: 16) {
            VStack(alignment: .leading, spacing: 6) {
                FormField(label: "Handle", text: binding.handle, prefix: "@", limit: 20, plain: true)
                Text("3 to 20 letters, numbers or underscores.")
                    .font(.text(13, relativeTo: .footnote))
                    .foregroundStyle(Palette.muted)
            }
            FormField(label: "Name", text: binding.name, limit: 60)
            FormField(
                label: "Bio (optional)", text: binding.bio,
                prompt: "Powerlifting, 5am club, training for a half marathon…", limit: 160
            )
            Button(mode == .setup ? "Create profile" : "Save", action: save)
                .buttonStyle(.pill(.primary, height: 54, fill: true))
                .disabled(saving || binding.wrappedValue.handle.trimmed.isEmpty)
                .padding(.top, 4)
        }
    }

    private func load() async {
        guard draft == nil else { return }
        do {
            let form: ProfileForm = try await app.api.get("/profile")
            draft = form.suggested
            error = nil
        } catch let failure {
            error = app.message(for: failure)
        }
    }

    private func save() {
        guard let draft else { return }
        saving = true
        Task {
            do {
                let saved: ProfileSaved = try await app.api.put("/profile", draft)
                app.setProfile(saved.profile)
                error = nil
                done(saved.created)
            } catch let failure {
                error = app.message(for: failure)
            }
            saving = false
        }
    }
}
