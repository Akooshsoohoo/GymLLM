import SwiftUI

/// What the Friends tab is showing, kept while you are on another tab.
@MainActor
@Observable
final class FriendsStore {
    enum Section: String {
        case feed, people
    }

    var section: Section = .feed
    var query = ""

    private(set) var feed: Feed?
    private(set) var cards: [FriendCard] = []
    private(set) var loadingOlder = false
    private(set) var page: FriendsPage?
    var error: String?
    /// Something that just went right: "Friend request sent to Sam."
    var notice: String?

    func load(app: AppState) async {
        do {
            switch section {
            case .feed:
                let first: Feed = try await app.api.get("/feed")
                feed = first
                cards = first.cards
            case .people:
                let handle = query.trimmed
                // Wait for a pause in the typing before asking.
                if !handle.isEmpty { try await Task.sleep(for: .milliseconds(300)) }
                page = try await app.api.get("/friends", query: handle.isEmpty ? [:] : ["q": handle])
                // Opening the list is what marks requests and reactions as seen.
                if (app.me?.unseen ?? 0) > 0 { await app.refreshMe() }
            }
            error = nil
        } catch let failure {
            error = app.message(for: failure)
        }
    }

    func loadOlder(app: AppState) async {
        guard let before = feed?.nextBefore, !loadingOlder else { return }
        loadingOlder = true
        defer { loadingOlder = false }
        do {
            let next: Feed = try await app.api.get("/feed", query: ["before": before])
            feed = next
            cards += next.cards
            error = nil
        } catch let failure {
            error = app.message(for: failure)
        }
    }

    /// request, accept, decline, cancel or remove, then the list again.
    func act(_ action: String, on handle: String, app: AppState) async {
        do {
            let change: FriendChange = try await app.api.post("/friends/\(action)/\(handle)")
            notice = change.message.isEmpty ? nil : change.message
            error = nil
            app.didChange()
        } catch let failure {
            error = app.message(for: failure)
        }
    }

    func resetInvite(app: AppState) async {
        do {
            let reset: InviteReset = try await app.api.post("/profile/invite-reset")
            notice = reset.message
            error = nil
            await app.refreshMe()
            app.didChange()
        } catch let failure {
            error = app.message(for: failure)
        }
    }
}

/// Friends: what they have been up to, and the people themselves. Mirrors
/// templates/feed.html and friends.html at phone width. Without a profile it is
/// the profile setup screen: the server sends everything here back as
/// `profile_required` until there is one.
struct FriendsScreen: View {
    @Environment(AppState.self) private var app
    @Bindable var store: FriendsStore

    private struct Key: Hashable {
        let section: FriendsStore.Section
        let query: String
        let changes: Int
        let hasProfile: Bool
    }

    var body: some View {
        Group {
            if app.me == nil {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if app.me?.profile == nil {
                ProfileEditView(mode: .setup) { _ in
                    store.section = .people
                    store.notice = "Profile created. Find friends below."
                }
            } else {
                signedUp
            }
        }
        .background(Palette.bg)
        .toolbar(.hidden, for: .navigationBar)
        .task { if app.me == nil { await app.refreshMe() } }
    }

    private var signedUp: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("Friends")
                    .font(.head(32, relativeTo: .largeTitle))
                    .foregroundStyle(Palette.ink)
                SegmentedToggle(
                    options: [("feed", "Activity"), ("people", peopleLabel)],
                    selection: Binding(
                        get: { store.section.rawValue },
                        set: { store.section = FriendsStore.Section(rawValue: $0) ?? .feed }
                    ),
                    label: "Friends", fill: true
                )
                if let notice = store.notice { NoteBanner(message: notice) }
                if let error = store.error { ErrorBanner(message: error) }
                switch store.section {
                case .feed: feed
                case .people: PeopleTab(store: store)
                }
            }
            .padding(.horizontal, Metrics.gutter)
            .padding(.top, 20)
            .padding(.bottom, 28)
        }
        .scrollDismissesKeyboard(.interactively)
        .refreshable { await store.load(app: app) }
        .task(
            id: Key(
                section: store.section, query: store.query.trimmed, changes: app.changes,
                hasProfile: app.me?.profile != nil
            )
        ) { await store.load(app: app) }
    }

    private var peopleLabel: String {
        let unseen = app.me?.unseen ?? 0
        return unseen > 0 ? "People · \(unseen < 10 ? String(unseen) : "9+")" : "People"
    }

    @ViewBuilder
    private var feed: some View {
        if let feed = store.feed {
            if !feed.hasFriends {
                EmptyNote(text: "When you have friends, their workouts show up here.") {
                    Button("Find friends") { store.section = .people }
                        .buttonStyle(.pill(.primary))
                }
            } else if store.cards.isEmpty {
                EmptyNote(text: "Your friends haven't logged anything yet.") { EmptyView() }
            } else {
                LazyVStack(spacing: 14) {
                    ForEach(store.cards, id: \.self) { SessionCardView(card: $0) }
                }
                if feed.nextBefore != nil {
                    Button(store.loadingOlder ? "Loading…" : "Older activity") {
                        Task { await store.loadOlder(app: app) }
                    }
                    .buttonStyle(.pill(.ghost, height: 44, fill: true))
                    .disabled(store.loadingOlder)
                }
            }
        } else if store.error == nil {
            ProgressView()
                .frame(maxWidth: .infinity)
                .padding(.top, 60)
        }
    }
}
