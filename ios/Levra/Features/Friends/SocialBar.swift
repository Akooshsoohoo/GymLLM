import SwiftUI

/// The workout a high five or a comment is about.
struct SessionKey: Hashable {
    let handle: String
    let date: String
    let session: Int

    var path: String { "\(handle)/\(date)/\(session)" }
}

extension Reactions {
    static let none = Reactions(kudos: 0, kudoed: false, comments: [])
}

/// Someone's workout as a card: who, what they did, then high fives and comments.
/// Lifts and cardio only: the API never sends anyone else's notes or body weight.
/// Mirrors session_card in templates/_social.html.
struct SessionCardView: View {
    @Environment(AppState.self) private var app
    let card: FriendCard
    /// Off on a profile, where every card is the same person's.
    var showOwner = true

    @State private var reactions: Reactions

    init(card: FriendCard, showOwner: Bool = true) {
        self.card = card
        self.showOwner = showOwner
        _reactions = State(initialValue: card.reactions ?? .none)
    }

    private var own: Bool {
        guard let handle = card.owner?.handle else { return false }
        return handle == app.me?.profile?.handle
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            header
            SessionRows(lines: card.lines, cardio: card.cardio)
            if let handle = card.owner?.handle, app.me?.profile != nil {
                Palette.line2.frame(height: 1)
                SocialBar(
                    key: SessionKey(handle: handle, date: card.date, session: card.session),
                    own: own, reactions: $reactions
                )
            }
        }
        .card(radius: 24)
    }

    @ViewBuilder
    private var header: some View {
        if showOwner, let owner = card.owner {
            NavigationLink(value: Route.person(handle: owner.handle)) {
                HStack(spacing: 12) {
                    Avatar(name: owner.name, url: owner.avatarUrl, size: 42, tone: own ? .you : .friend)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(owner.name)
                            .font(.text(16, .semibold))
                            .foregroundStyle(Palette.ink)
                        Text(meta(count: true))
                            .font(.text(13, relativeTo: .footnote))
                            .foregroundStyle(Palette.muted)
                            .lineLimit(1)
                    }
                    Spacer(minLength: 0)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("\(owner.name), \(meta(count: true))")
        } else if own {
            NavigationLink(value: Route.day(date: card.date, session: card.session, saved: nil)) {
                HStack {
                    when
                    Spacer(minLength: 8)
                    Image(systemName: "chevron.right")
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(Palette.disabled)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
        } else {
            when
        }
    }

    private var when: some View {
        Text(meta(count: false))
            .font(.text(15, .bold))
            .foregroundStyle(Palette.ink)
    }

    private func meta(count: Bool) -> String {
        [card.title, Days.label(card.date), count ? activityCount(lines: card.lines, cardio: card.cardio) : ""]
            .filter { !$0.isEmpty }
            .joined(separator: " · ")
    }
}

/// High five and comments under a workout. On someone else's the high five is a
/// toggle; on your own it is a count. Comments open in a sheet.
struct SocialBar: View {
    @Environment(AppState.self) private var app
    let key: SessionKey
    let own: Bool
    @Binding var reactions: Reactions

    @State private var commenting = false
    @State private var busy = false
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                if own {
                    pill("High five · \(reactions.kudos)", symbol: "hand.raised", on: reactions.kudos > 0)
                        .accessibilityLabel("\(reactions.kudos) high five\(reactions.kudos == 1 ? "" : "s")")
                } else {
                    Button(action: highFive) {
                        pill(
                            "High five · \(reactions.kudos)",
                            symbol: reactions.kudoed ? "hand.raised.fill" : "hand.raised", on: reactions.kudoed
                        )
                    }
                    .buttonStyle(.plain)
                    .disabled(busy)
                    .accessibilityLabel(reactions.kudoed ? "Take back high five" : "Give a high five")
                    .accessibilityValue(String(reactions.kudos))
                }
                Button {
                    commenting = true
                } label: {
                    let n = reactions.comments.count
                    pill(n == 0 ? "Comment" : "\(n) comment\(n == 1 ? "" : "s")", symbol: nil, on: false)
                }
                .buttonStyle(.plain)
            }
            if let last = reactions.comments.last {
                (Text((last.author?.name.split(separator: " ").first.map(String.init) ?? "Someone") + "  ")
                    .font(.text(14, .semibold, relativeTo: .subheadline)).foregroundStyle(Palette.ink)
                    + Text(last.body).font(.text(14, relativeTo: .subheadline)).foregroundStyle(Palette.ink2))
                    .lineLimit(1)
            }
            if let error {
                Text(error)
                    .font(.text(13, .medium, relativeTo: .footnote))
                    .foregroundStyle(Palette.dangerInk)
            }
        }
        .sheet(isPresented: $commenting) {
            CommentsSheet(key: key, reactions: $reactions)
        }
    }

    private func pill(_ text: String, symbol: String?, on: Bool) -> some View {
        HStack(spacing: 6) {
            if let symbol { Image(systemName: symbol).font(.system(size: 13, weight: .semibold)) }
            Text(text).font(.text(14, .semibold, relativeTo: .subheadline)).monospacedDigit()
        }
        .foregroundStyle(on ? Palette.youInk : Palette.ink2)
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
        .background(on ? Palette.youTint : Palette.field, in: Capsule())
        .contentShape(Capsule())
    }

    private func highFive() {
        busy = true
        Task {
            do {
                let result: KudosResult = try await app.api.post("/kudos/\(key.path)")
                reactions = Reactions(kudos: result.count, kudoed: result.mine, comments: reactions.comments)
                error = nil
            } catch let failure {
                error = app.message(for: failure)
            }
            busy = false
        }
    }
}

/// "From friends" on one of your own days: the high fives, every comment, and the
/// way to answer. Mirrors thread in templates/_social.html.
struct FromFriends: View {
    let key: SessionKey
    @State private var reactions: Reactions
    @State private var commenting = false

    init(key: SessionKey, reactions: Reactions) {
        self.key = key
        _reactions = State(initialValue: reactions)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("From friends")
                    .font(.head(17))
                    .foregroundStyle(Palette.ink)
                Spacer()
                if reactions.kudos > 0 {
                    HStack(spacing: 6) {
                        Image(systemName: "hand.raised.fill").font(.system(size: 13, weight: .semibold))
                        Text("\(reactions.kudos) high five\(reactions.kudos == 1 ? "" : "s")")
                            .font(.text(14, .semibold, relativeTo: .subheadline))
                    }
                    .foregroundStyle(Palette.youInk)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 8)
                    .background(Palette.youTint, in: Capsule())
                }
            }
            ForEach(reactions.comments) { CommentRow(comment: $0) }
            Button(reactions.comments.isEmpty ? "Add a comment" : "Reply") { commenting = true }
                .buttonStyle(.pill(.ghost, height: 38))
        }
        .card()
        .sheet(isPresented: $commenting) {
            CommentsSheet(key: key, reactions: $reactions)
        }
    }
}

/// Every comment on a workout, and a box to add one. You can delete your own, and
/// any on your own workout.
struct CommentsSheet: View {
    @Environment(AppState.self) private var app
    @Environment(\.dismiss) private var close
    let key: SessionKey
    @Binding var reactions: Reactions

    @State private var draft = ""
    @State private var busy = false
    @State private var error: String?
    @FocusState private var typing: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("Comments")
                    .font(.head(22))
                    .foregroundStyle(Palette.ink)
                Spacer()
                Button("Done") { close() }
                    .buttonStyle(LinkButtonStyle(size: 16))
            }
            .padding(.horizontal, Metrics.gutter)
            .padding(.top, 20)
            .padding(.bottom, 12)

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    if reactions.comments.isEmpty {
                        Text("No comments yet.")
                            .font(.text(15))
                            .foregroundStyle(Palette.muted)
                    }
                    ForEach(reactions.comments) { comment in
                        CommentRow(comment: comment) { delete(comment) }
                    }
                    if let error { ErrorBanner(message: error) }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, Metrics.gutter)
                .padding(.vertical, 8)
            }

            HStack(spacing: 8) {
                TextField("", text: $draft, prompt: Text("Add a comment").foregroundStyle(Palette.muted2))
                    .font(.text(16))
                    .foregroundStyle(Palette.ink)
                    .focused($typing)
                    .submitLabel(.send)
                    .onSubmit(post)
                    .accessibilityLabel("Add a comment")
                    .padding(.horizontal, 14)
                    .frame(height: 46)
                    .background(Palette.surface, in: Capsule())
                    .onChange(of: draft) { _, new in
                        if new.count > 500 { draft = String(new.prefix(500)) }
                    }
                Button("Post", action: post)
                    .buttonStyle(.pill(.primary, height: 46))
                    .disabled(busy || draft.trimmed.isEmpty)
            }
            .padding(.horizontal, Metrics.gutter)
            .padding(.vertical, 12)
        }
        .background(Palette.bg)
        .presentationDetents([.medium, .large])
        .presentationBackground(Palette.bg)
    }

    private func post() {
        let body = draft.trimmed
        guard !body.isEmpty, !busy else { return }
        send {
            reactions = try await app.api.post("/comments/\(key.path)", CommentRequest(body: body))
            draft = ""
        }
    }

    private func delete(_ comment: Comment) {
        send {
            let left: Reactions = try await app.api.delete("/comments/\(comment.id)")
            // The server answers with nothing when the workout is no longer yours to see.
            reactions = Reactions(
                kudos: reactions.kudos, kudoed: reactions.kudoed,
                comments: left.comments.isEmpty ? reactions.comments.filter { $0.id != comment.id } : left.comments
            )
        }
    }

    private func send(_ work: @escaping () async throws -> Void) {
        busy = true
        Task {
            do {
                try await work()
                error = nil
            } catch let failure {
                error = app.message(for: failure)
            }
            busy = false
        }
    }
}

/// One comment: who, how long ago, what they said.
struct CommentRow: View {
    @Environment(AppState.self) private var app
    let comment: Comment
    var delete: (() -> Void)?

    private var mine: Bool {
        guard let handle = comment.author?.handle else { return false }
        return handle == app.me?.profile?.handle
    }

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Avatar(
                name: comment.author?.name ?? "", url: comment.author?.avatarUrl, size: 32,
                tone: mine ? .you : .friend
            )
            VStack(alignment: .leading, spacing: 2) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(comment.author?.name ?? "Someone")
                        .font(.text(14, .semibold, relativeTo: .subheadline))
                        .foregroundStyle(Palette.ink)
                    Text(Days.ago(comment.at))
                        .font(.text(13, relativeTo: .footnote))
                        .foregroundStyle(Palette.muted)
                    Spacer(minLength: 8)
                    if comment.canDelete, let delete {
                        Button("Delete", action: delete)
                            .buttonStyle(LinkButtonStyle(color: Palette.muted, size: 13))
                            .accessibilityLabel("Delete comment")
                    }
                }
                Text(comment.body)
                    .font(.text(15))
                    .foregroundStyle(Palette.ink2)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}
