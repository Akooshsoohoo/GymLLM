import SwiftUI

/// The People half of Friends: find someone by handle, your invite link, an invite
/// someone sent you, requests, your friends, and what they said about your workouts.
struct PeopleTab: View {
    @Environment(AppState.self) private var app
    @Bindable var store: FriendsStore

    @State private var pasted = ""
    @State private var opening: InviteCode?
    @State private var confirmingReset = false
    @State private var copied = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            find
            if let page = store.page {
                // Above the link, not below: the keyboard covers the lower half of the page.
                gotAnInvite
                inviteLink(page.inviteUrl)
                if !page.incoming.isEmpty {
                    people("Requests", page.incoming, relationship: Relationship.incoming)
                }
                VStack(alignment: .leading, spacing: 10) {
                    SectionHead(page.friends.isEmpty ? "Your friends" : "Your friends · \(page.friends.count)")
                    if page.friends.isEmpty {
                        Text("No friends yet. Search for a handle above or send someone your invite link.")
                            .font(.text(15))
                            .foregroundStyle(Palette.muted)
                    } else {
                        list(page.friends, relationship: Relationship.friends)
                    }
                }
                if !page.outgoing.isEmpty {
                    people("Sent requests", page.outgoing, relationship: Relationship.outgoing)
                }
                activity(page.activity)
            } else if store.error == nil {
                ProgressView()
                    .frame(maxWidth: .infinity)
                    .padding(.top, 40)
            }
        }
        .sheet(item: $opening) { invite in
            InviteSheet(code: invite.code) { message in
                opening = nil
                pasted = ""
                store.notice = message
                app.didChange()
            }
        }
    }

    // MARK: Find people

    private var find: some View {
        VStack(alignment: .leading, spacing: 12) {
            CardHead("Find people")
            HStack(spacing: 8) {
                Image(systemName: "magnifyingglass")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(Palette.muted)
                TextField("", text: $store.query, prompt: Text("@handle").foregroundStyle(Palette.muted2))
                    .font(.text(16, .medium))
                    .foregroundStyle(Palette.ink)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
                    .submitLabel(.search)
                    .accessibilityLabel("Search by handle")
                if !store.query.isEmpty {
                    Button {
                        store.query = ""
                    } label: {
                        Image(systemName: "xmark.circle.fill").foregroundStyle(Palette.muted2)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Clear search")
                }
            }
            .padding(.horizontal, 14)
            .frame(height: 46)
            .background(Palette.field, in: RoundedRectangle(cornerRadius: 14, style: .continuous))

            let asked = store.query.trimmed
            if !asked.isEmpty, let page = store.page, page.q == asked {
                if page.results.isEmpty {
                    Text("No one with a handle starting \"\(page.q)\".")
                        .font(.text(14, relativeTo: .subheadline))
                        .foregroundStyle(Palette.muted)
                } else {
                    VStack(spacing: 12) {
                        ForEach(page.results, id: \.handle) { found in
                            PersonRow(person: found.person) { actions(found.person, found.relationship) }
                        }
                    }
                }
            }
        }
        .card()
    }

    // MARK: Invites

    private func inviteLink(_ link: String) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            CardHead("Your invite link")
            Text("Anyone who opens it and signs in can add you with one tap.")
                .font(.text(14, relativeTo: .subheadline))
                .foregroundStyle(Palette.muted)
            Text(link)
                .font(.text(14, .medium, relativeTo: .subheadline))
                .foregroundStyle(Palette.ink)
                .lineLimit(1)
                .truncationMode(.middle)
                .padding(.horizontal, 14)
                .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                .background(Palette.field, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                .accessibilityLabel("Invite link")
                .accessibilityValue(link)
            HStack(spacing: 8) {
                if let url = URL(string: link) {
                    ShareLink(item: url, message: Text("Train with me on Levra")) {
                        Text("Share link")
                    }
                    .buttonStyle(.pill(.primary, height: 40))
                }
                Button(copied ? "Copied" : "Copy") {
                    UIPasteboard.general.string = link
                    copied = true
                    Task {
                        try? await Task.sleep(for: .seconds(2))
                        copied = false
                    }
                }
                .buttonStyle(.pill(.ghost, height: 40))
                .accessibilityLabel(copied ? "Copied" : "Copy invite link")
                Spacer(minLength: 0)
                Button("Make a new link") { confirmingReset = true }
                    .buttonStyle(LinkButtonStyle(color: Palette.muted, size: 13))
            }
        }
        .card()
        .confirmationDialog("Make a new invite link?", isPresented: $confirmingReset, titleVisibility: .visible) {
            Button("Make a new link", role: .destructive) {
                Task { await store.resetInvite(app: app) }
            }
            Button("Keep this one", role: .cancel) {}
        } message: {
            Text("The old one stops working.")
        }
    }

    /// Invite links open the website until the app can claim them, so one a friend
    /// sent is pasted in here: the whole link, or just the code at its end.
    private var gotAnInvite: some View {
        VStack(alignment: .leading, spacing: 12) {
            CardHead("Got an invite?")
            Text("Paste the link a friend sent you.")
                .font(.text(14, relativeTo: .subheadline))
                .foregroundStyle(Palette.muted)
            HStack(spacing: 8) {
                TextField("", text: $pasted, prompt: Text("Invite link or code").foregroundStyle(Palette.muted2))
                    .font(.text(16, .medium))
                    .foregroundStyle(Palette.ink)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
                    .keyboardType(.URL)
                    .submitLabel(.go)
                    .onSubmit(openInvite)
                    .accessibilityLabel("Invite link or code")
                    .padding(.horizontal, 14)
                    .frame(height: 46)
                    .background(Palette.field, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                Button("Open", action: openInvite)
                    .buttonStyle(.pill(.primary, height: 46))
                    .disabled(InviteCode(pasted: pasted) == nil)
                    .accessibilityLabel("Open invite")
            }
        }
        .card()
    }

    private func openInvite() {
        opening = InviteCode(pasted: pasted)
    }

    // MARK: People

    private func people(_ title: String, _ people: [Person], relationship: String) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHead(title)
            list(people, relationship: relationship)
        }
    }

    private func list(_ people: [Person], relationship: String) -> some View {
        VStack(spacing: 12) {
            ForEach(people, id: \.handle) { person in
                PersonRow(person: person) { actions(person, relationship) }
            }
        }
        .card()
    }

    @ViewBuilder
    private func actions(_ person: Person, _ relationship: String) -> some View {
        RelationshipActions(person: person, relationship: relationship, compact: true) { action in
            Task { await store.act(action, on: person.handle, app: app) }
        }
    }

    // MARK: On your sessions

    private func activity(_ events: [ActivityEvent]) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHead("On your sessions")
            if events.isEmpty {
                Text("High fives and comments from friends on your sessions show up here.")
                    .font(.text(15))
                    .foregroundStyle(Palette.muted)
            } else {
                VStack(spacing: 14) {
                    ForEach(Array(events.enumerated()), id: \.offset) { _, event in
                        NavigationLink(value: Route.day(date: event.date, session: event.session, saved: nil)) {
                            activityRow(event)
                        }
                        .buttonStyle(.plain)
                    }
                }
                .card()
            }
        }
    }

    private func activityRow(_ event: ActivityEvent) -> some View {
        let name = event.who?.name ?? "Someone"
        let did = event.kind == "kudos" ? "gave a high five on" : "commented on"
        return HStack(alignment: .top, spacing: 10) {
            Avatar(name: name, url: event.who?.avatarUrl, size: 32, tone: .friend)
            VStack(alignment: .leading, spacing: 3) {
                (Text(name).font(.text(15, .semibold)).foregroundStyle(Palette.ink)
                    + Text(" \(did) your session on \(Days.label(event.date))")
                    .font(.text(15)).foregroundStyle(Palette.ink2))
                    .multilineTextAlignment(.leading)
                    .fixedSize(horizontal: false, vertical: true)
                if !event.body.isEmpty {
                    Text(event.body)
                        .font(.text(14, relativeTo: .subheadline))
                        .foregroundStyle(Palette.ink2)
                        .lineLimit(2)
                        .multilineTextAlignment(.leading)
                }
            }
            Spacer(minLength: 8)
            VStack(alignment: .trailing, spacing: 6) {
                Text(Days.ago(event.at))
                    .font(.text(13, relativeTo: .footnote))
                    .foregroundStyle(Palette.muted)
                if event.new { Circle().fill(Palette.you).frame(width: 8, height: 8) }
            }
        }
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(event.new ? "New. " : "")\(name) \(did) your session on \(Days.label(event.date)). \(event.body)")
    }
}

/// A person, leading to their profile, with what you can do about them on the right.
struct PersonRow<Trailing: View>: View {
    let person: Person
    @ViewBuilder var trailing: Trailing

    var body: some View {
        HStack(spacing: 10) {
            NavigationLink(value: Route.person(handle: person.handle)) {
                HStack(spacing: 10) {
                    Avatar(name: person.name, url: person.avatarUrl, size: 38, tone: .friend)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(person.name)
                            .font(.text(15, .semibold))
                            .foregroundStyle(Palette.ink)
                            .lineLimit(1)
                        Text("@\(person.handle)")
                            .font(.text(13, relativeTo: .footnote))
                            .foregroundStyle(Palette.muted)
                            .lineLimit(1)
                    }
                    Spacer(minLength: 0)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("\(person.name), @\(person.handle)")
            trailing
        }
    }
}

/// The buttons for how you stand with someone: add, cancel, accept or decline, or
/// compare. Mirrors rel_actions in templates/_social.html. `act` takes the
/// server's word for it: request, accept, decline, cancel.
struct RelationshipActions: View {
    let person: Person
    let relationship: String
    /// In a list: small buttons. Off on a profile, where they lead.
    var compact = false
    let act: (String) -> Void

    private var height: CGFloat { compact ? 34 : 44 }

    var body: some View {
        HStack(spacing: 10) {
            switch relationship {
            case Relationship.none:
                Button("Add friend") { act("request") }
                    .buttonStyle(.pill(.primary, height: height))
                    .accessibilityLabel("Add \(person.name) as a friend")
            case Relationship.outgoing:
                Text("Requested")
                    .font(.text(compact ? 13 : 15, .medium, relativeTo: .footnote))
                    .foregroundStyle(Palette.muted)
                Button("Cancel") { act("cancel") }
                    .buttonStyle(LinkButtonStyle(color: Palette.ink2, size: compact ? 13 : 15))
                    .accessibilityLabel("Cancel request to \(person.name)")
            case Relationship.incoming:
                Button("Accept") { act("accept") }
                    .buttonStyle(.pill(.primary, height: height))
                    .accessibilityLabel("Accept \(person.name)")
                Button("Decline") { act("decline") }
                    .buttonStyle(LinkButtonStyle(color: Palette.ink2, size: compact ? 13 : 15))
                    .accessibilityLabel("Decline \(person.name)")
            case Relationship.friends:
                NavigationLink(compact ? "Compare" : "Compare with you", value: Route.compare(handle: person.handle))
                    .buttonStyle(.pill(compact ? .ghost : .primary, height: height))
                    .accessibilityLabel("Compare with \(person.name)")
            default:
                EmptyView()
            }
        }
    }
}

/// The code at the end of an invite link, from whatever was pasted: the whole link
/// (https://levraapp.com/invite/AbC123), with or without a query, or the bare code.
struct InviteCode: Identifiable, Hashable {
    let code: String
    var id: String { code }

    init?(pasted: String) {
        var text = pasted.trimmed
        if let marker = text.range(of: "/invite/") { text = String(text[marker.upperBound...]) }
        text = String(text.prefix { !"/?#".contains($0) })
        // Codes are URL-safe base64 (secrets.token_urlsafe).
        let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "-_"))
        guard !text.isEmpty, text.count <= 64, text.unicodeScalars.allSatisfy(allowed.contains) else {
            return nil
        }
        code = text
    }
}

/// Whose invite it is, and the one tap that makes you friends.
struct InviteSheet: View {
    @Environment(AppState.self) private var app
    @Environment(\.dismiss) private var close
    let code: String
    /// They are now your friend; the message says so.
    let added: (String) -> Void

    @State private var invite: FriendChange?
    @State private var error: String?
    @State private var busy = false

    var body: some View {
        VStack(spacing: 16) {
            if let invite {
                Avatar(name: invite.person.name, url: invite.person.avatarUrl, size: 72, tone: .friend)
                Text(title(invite))
                    .font(.head(24))
                    .foregroundStyle(Palette.ink)
                    .multilineTextAlignment(.center)
                Text(detail(invite))
                    .font(.text(15))
                    .foregroundStyle(Palette.ink2)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                if let error { ErrorBanner(message: error) }
                Spacer(minLength: 0)
                if invite.relationship == Relationship.me || invite.relationship == Relationship.friends {
                    Button("Done") { close() }
                        .buttonStyle(.pill(.primary, height: 54, fill: true))
                } else {
                    Button("Add \(invite.person.name)", action: add)
                        .buttonStyle(.pill(.primary, height: 54, fill: true))
                        .disabled(busy)
                    Button("Not now") { close() }
                        .buttonStyle(LinkButtonStyle(color: Palette.muted, size: 15))
                }
            } else if let error {
                ErrorBanner(message: error)
                Spacer(minLength: 0)
                Button("Close") { close() }
                    .buttonStyle(.pill(.white, height: 54, fill: true))
            } else {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .padding(Metrics.gutter)
        .padding(.top, 16)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Palette.bg)
        .presentationDetents([.medium])
        .presentationBackground(Palette.bg)
        .task {
            do {
                invite = try await app.api.get("/invite/\(code)")
            } catch let failure {
                error = app.message(for: failure)
            }
        }
    }

    private func title(_ invite: FriendChange) -> String {
        switch invite.relationship {
        case Relationship.me: "This is your own invite link"
        case Relationship.friends: "You and \(invite.person.name) are already friends"
        default: "\(invite.person.name) invited you"
        }
    }

    private func detail(_ invite: FriendChange) -> String {
        switch invite.relationship {
        case Relationship.me: "Send it to a friend. They can add you with one tap."
        case Relationship.friends: "Their workouts are in your Friends activity."
        default: "Be friends on Levra to see each other's workouts, trade high fives and compare stats."
        }
    }

    private func add() {
        busy = true
        Task {
            do {
                let change: FriendChange = try await app.api.post("/invite/\(code)")
                added(change.message.isEmpty ? "You and \(change.person.name) are now friends." : change.message)
            } catch let failure {
                error = app.message(for: failure)
            }
            busy = false
        }
    }
}
