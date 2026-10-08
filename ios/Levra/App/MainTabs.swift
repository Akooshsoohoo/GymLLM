import SwiftUI

/// Somewhere a tab's stack can go.
enum Route: Hashable {
    /// One of your own days. `saved` marks the workout just logged.
    case day(date: String, session: Int?, saved: SavedKind?)

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

/// The five tabs of templates/base.html: Home, Progress, the raised centre button,
/// Friends, Me. This stage builds Home and the log flow; Progress and Friends say
/// they are on their way, and the centre button opens Log until Record exists.
struct MainTabs: View {
    enum Tab: Hashable { case home, progress, friends, me }

    @Environment(AppState.self) private var app
    @State private var tab: Tab = .home
    @State private var store = HomeStore()
    @State private var homePath: [Route] = []
    @State private var logging = false

    var body: some View {
        Group {
            switch tab {
            case .home:
                NavigationStack(path: $homePath) {
                    HomeView(store: store, openLog: { logging = true })
                        .navigationDestination(for: Route.self) { route in
                            switch route {
                            case let .day(date, session, saved):
                                DayView(date: date, session: session, saved: saved)
                            }
                        }
                }
            case .progress:
                ComingSoon(
                    title: "Progress",
                    message: "Charts, personal bests and your training calendar are coming to the app. For now they're at levraapp.com."
                )
            case .friends:
                ComingSoon(
                    title: "Friends",
                    message: "The feed, high fives and comparing with friends are coming to the app. For now they're at levraapp.com."
                )
            case .me:
                MeView()
            }
        }
        .safeAreaInset(edge: .bottom, spacing: 0) {
            TabBar(tab: $tab, unseen: app.me?.unseen ?? 0, reselect: { homePath = [] }) { logging = true }
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

/// A tab whose screens arrive in a later stage.
private struct ComingSoon: View {
    let title: String
    let message: String

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(title)
                .font(.head(32, relativeTo: .largeTitle))
                .foregroundStyle(Palette.ink)
            Text(message)
                .font(.text(16))
                .foregroundStyle(Palette.ink2)
                .card()
            Spacer()
        }
        .padding(.horizontal, Metrics.gutter)
        .padding(.top, 20)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Palette.bg)
    }
}

/// Who you are, your units, and the way out. The rest of Me comes with Friends.
private struct MeView: View {
    @Environment(AppState.self) private var app
    @State private var unit = "lbs"
    @State private var error: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("Me")
                    .font(.head(32, relativeTo: .largeTitle))
                    .foregroundStyle(Palette.ink)

                HStack(spacing: 14) {
                    Avatar(
                        name: app.me?.profile?.name ?? app.firstName,
                        url: app.me?.profile?.avatarUrl, size: 56, tone: .you
                    )
                    VStack(alignment: .leading, spacing: 2) {
                        Text(app.me?.profile?.name ?? app.firstName)
                            .font(.head(19))
                            .foregroundStyle(Palette.ink)
                        Text([app.me?.profile.map { "@\($0.handle)" }, app.me?.email].compactMap { $0 }.joined(separator: " · "))
                            .font(.text(13, .medium, relativeTo: .footnote))
                            .foregroundStyle(Palette.muted)
                            .lineLimit(1)
                            .truncationMode(.middle)
                    }
                }
                .card()

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

                if let error { ErrorBanner(message: error) }

                Button("Sign out") { app.signOut() }
                    .buttonStyle(.pill(.white, height: 54, fill: true))
            }
            .padding(.horizontal, Metrics.gutter)
            .padding(.top, 20)
            .padding(.bottom, 24)
        }
        .background(Palette.bg)
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
}
