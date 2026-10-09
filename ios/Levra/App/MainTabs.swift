import SwiftUI

/// Somewhere a tab's stack can go.
enum Route: Hashable {
    /// One of your own days. `saved` marks the workout just logged.
    case day(date: String, session: Int?, saved: SavedKind?)
    /// One exercise over time, starting on the range Progress was showing.
    case exercise(name: String, range: String)
    /// Someone's profile.
    case person(handle: String)
    /// You beside a friend.
    case compare(handle: String)

    enum SavedKind: Hashable { case saved, first }
}

/// Home's data, shared with the Log screen (which shows the same week and the
/// number of free logs left).
@MainActor
@Observable
final class HomeStore {
    private(set) var home: Home?
    var error: String?

    func load(app: AppState, saved: SavedSession? = nil) async {
        var query: [String: String] = [:]
        if let saved {
            query = ["saved": saved.date, "session": String(saved.session)]
        }
        do {
            home = try await app.api.get("/home", query: query)
            error = nil
        } catch let failure {
            error = app.message(for: failure)
        }
    }
}

extension View {
    /// Where a tab's stack goes for each Route. `backTitle` is what a day's back
    /// button says: the tab it leads to.
    func routes(backTitle: String) -> some View {
        navigationDestination(for: Route.self) { route in
            switch route {
            case let .day(date, session, saved):
                DayView(date: date, session: session, saved: saved, backTitle: backTitle)
            case let .exercise(name, range):
                ExerciseView(name: name, range: range)
            case let .person(handle):
                PersonView(handle: handle, backTitle: backTitle)
            case let .compare(handle):
                CompareView(handle: handle)
            }
        }
    }
}

/// The five tabs of templates/base.html: Home, Progress, the raised centre button,
/// Friends, Me. The centre button opens Log until Record exists.
struct MainTabs: View {
    enum Tab: Hashable { case home, progress, friends, me }

    @Environment(AppState.self) private var app
    @State private var tab: Tab = .home
    @State private var store = HomeStore()
    @State private var progress = ProgressStore()
    @State private var friends = FriendsStore()
    @State private var homePath: [Route] = []
    @State private var progressPath: [Route] = []
    @State private var friendsPath: [Route] = []
    @State private var mePath: [Route] = []
    @State private var logging = false

    var body: some View {
        Group {
            switch tab {
            case .home:
                NavigationStack(path: $homePath) {
                    HomeView(store: store, openLog: { logging = true })
                        .routes(backTitle: "Home")
                }
            case .progress:
                NavigationStack(path: $progressPath) {
                    ProgressScreen(store: progress, openLog: { logging = true })
                        .routes(backTitle: "Progress")
                }
            case .friends:
                NavigationStack(path: $friendsPath) {
                    FriendsScreen(store: friends)
                        .routes(backTitle: "Friends")
                }
            case .me:
                NavigationStack(path: $mePath) {
                    MeView()
                        .routes(backTitle: "Me")
                }
            }
        }
        .safeAreaInset(edge: .bottom, spacing: 0) {
            TabBar(tab: $tab, unseen: app.me?.unseen ?? 0, reselect: {
                homePath = []
                progressPath = []
                friendsPath = []
                mePath = []
            }) { logging = true }
        }
        .ignoresSafeArea(.keyboard, edges: .bottom)
        .fullScreenCover(isPresented: $logging) {
            LogFlow(store: store) { saved, first in
                logging = false
                tab = .home
                homePath = [.day(date: saved.date, session: saved.session, saved: first ? .first : .saved)]
                Task {
                    await store.load(app: app, saved: saved)
                    await app.refreshMe()
                }
            }
        }
    }
}

private struct TabBar: View {
    @Binding var tab: MainTabs.Tab
    let unseen: Int
    /// The tab already showing was tapped again: back to its top.
    let reselect: () -> Void
    let log: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 0) {
            item(.home, "Home", "house")
            item(.progress, "Progress", "chart.bar")
            Button(action: log) {
                VStack(spacing: 3) {
                    Image(systemName: "plus")
                        .font(.system(size: 22, weight: .semibold))
                        .foregroundStyle(Palette.onPrimary)
                        .frame(width: 58, height: 58)
                        .background(Palette.primary, in: Circle())
                        .overlay { Circle().strokeBorder(Palette.bg, lineWidth: 4) }
                        .padding(.top, -28)
                    Text("Log").tabLabel(active: false)
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Log a workout")
            item(.friends, "Friends", "person.2", badge: unseen)
            item(.me, "Me", "person.crop.circle")
        }
        .padding(.top, 9)
        .padding(.horizontal, 6)
        .frame(height: Metrics.tabBarHeight, alignment: .top)
        .background(alignment: .top) {
            Palette.tabBg
                .overlay(alignment: .top) { Palette.line.frame(height: 1) }
                .ignoresSafeArea(edges: .bottom)
        }
    }

    private func item(_ value: MainTabs.Tab, _ label: String, _ symbol: String, badge: Int = 0) -> some View {
        let active = tab == value
        return Button {
            if active { reselect() }
            tab = value
        } label: {
            VStack(spacing: 5) {
                Image(systemName: active ? symbol + ".fill" : symbol)
                    .font(.system(size: 20, weight: .medium))
                    .frame(height: 24)
                    .overlay(alignment: .topTrailing) {
                        if badge > 0 {
                            Text(badge < 10 ? String(badge) : "9+")
                                .font(.text(11, .bold, relativeTo: .caption2))
                                .foregroundStyle(Palette.onYou)
                                .padding(.horizontal, 5)
                                .frame(minWidth: 18, minHeight: 18)
                                .background(Palette.you, in: Capsule())
                                .offset(x: 12, y: -5)
                        }
                    }
                Text(label).tabLabel(active: active)
            }
            .foregroundStyle(active ? Palette.ink : Palette.muted2)
            .frame(maxWidth: .infinity)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(badge > 0 ? "\(label), \(badge) new" : label)
        .accessibilityAddTraits(active ? .isSelected : [])
    }
}

private extension Text {
    func tabLabel(active: Bool) -> some View {
        self.font(.custom(Font.TextWeight.semibold.rawValue, fixedSize: 12))
            .foregroundStyle(active ? Palette.ink : Palette.muted2)
    }
}
