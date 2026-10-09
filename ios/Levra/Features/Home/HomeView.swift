import SwiftUI

/// Home: the greeting, your week, your latest workout, the way into logging, and
/// what friends have been up to. Mirrors templates/home.html at phone width.
struct HomeView: View {
    @Environment(AppState.self) private var app
    let store: HomeStore
    let openLog: () -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                header
                if let home = store.home {
                    content(home)
                } else if let error = store.error {
                    ErrorBanner(message: error)
                    Button("Try again") { Task { await store.load(app: app) } }
                        .buttonStyle(.pill(.white))
                } else {
                    ProgressView()
                        .frame(maxWidth: .infinity)
                        .padding(.top, 60)
                }
            }
            .padding(.horizontal, Metrics.gutter)
            .padding(.top, 12)
            .padding(.bottom, 28)
        }
        .background(Palette.bg)
        .toolbar(.hidden, for: .navigationBar)
        .refreshable {
            await store.load(app: app)
            await app.refreshMe()
        }
        .task(id: app.changes) { await store.load(app: app) }
    }

    private var header: some View {
        HStack(alignment: .center) {
            Text(app.firstName.isEmpty ? Days.greeting() : "\(Days.greeting()), \(app.firstName)")
                .font(.head(30, relativeTo: .largeTitle))
                .tracking(-0.6)
                .foregroundStyle(Palette.ink)
                .lineLimit(1)
                .minimumScaleFactor(0.7)
            Spacer(minLength: 12)
            Avatar(
                name: app.me?.profile?.name ?? app.firstName,
                url: app.me?.profile?.avatarUrl, size: 40, tone: .you
            )
        }
    }

    @ViewBuilder
    private func content(_ home: Home) -> some View {
        if let error = store.error { ErrorBanner(message: error) }
        // Nothing logged yet: the way in leads, instead of an empty week.
        if home.hasLogged { WeekHero(week: home.week, streak: home.streak) }
        if let latest = home.latest { latestSection(latest, home: home) }
        logPrompt(home)
        if let checklist = home.checklist { checklistSection(checklist) }
        // The checklist stands in for the "set up a profile" and "find friends" notes.
        if home.checklist == nil || home.hasFriends { friendsSection(home) }
        if !home.recent.isEmpty { recentSection(home.recent) }
    }

    // MARK: Your latest workout

    private func latestSection(_ latest: MyCard, home: Home) -> some View {
        let route = Route.day(date: latest.date, session: latest.session, saved: nil)
        let count = activityCount(lines: latest.lines, cardio: latest.cardio)
        return VStack(alignment: .leading, spacing: 10) {
            SectionHead(title: latest.date == home.today ? "Today" : "Just logged") {
                NavigationLink("Details", value: route).buttonStyle(LinkButtonStyle(color: Palette.muted))
            }
            NavigationLink(value: route) {
                VStack(alignment: .leading, spacing: 14) {
                    HStack(alignment: .firstTextBaseline) {
                        (Text(latest.title).font(.text(15, .bold)).foregroundStyle(Palette.ink)
                            + Text(" · " + ([Days.label(latest.date), count].filter { !$0.isEmpty }.joined(separator: " · ")))
                            .font(.text(13, relativeTo: .footnote)).foregroundStyle(Palette.muted))
                            .multilineTextAlignment(.leading)
                        Spacer(minLength: 8)
                        if home.justSaved {
                            Badge(text: home.firstSave ? "First workout logged" : "Saved", tone: .saved)
                        }
                    }
                    SessionRows(lines: latest.lines, cardio: latest.cardio)
                    if let reactions = latest.reactions, reactions.kudos > 0 || !reactions.comments.isEmpty {
                        Palette.line2.frame(height: 1)
                        ReactionsBar(reactions: reactions)
                    }
                }
                .card(radius: 24)
            }
            .buttonStyle(.plain)
        }
    }

    // MARK: The way into logging

    private func logPrompt(_ home: Home) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text(Days.label(home.today, long: true))
                    .font(.text(14, relativeTo: .subheadline))
                    .foregroundStyle(Palette.muted)
                Text(home.hasLogged ? question : "Log your first workout")
                    .font(.head(26, relativeTo: .title))
                    .tracking(-0.5)
                    .foregroundStyle(Palette.ink)
                if !home.hasLogged {
                    Text("Type what you did, the way you'd text a friend. We turn it into a log, and you check it before anything is saved.")
                        .font(.text(15))
                        .foregroundStyle(Palette.ink2)
                }
            }
            Button(action: openLog) {
                HStack(spacing: 12) {
                    Text("Ran 5k, then squats 3×8 at 135…")
                        .font(.text(17))
                        .foregroundStyle(Palette.muted2)
                        .lineLimit(1)
                    Spacer(minLength: 8)
                    Text("Log it")
                        .font(.text(16, .bold))
                        .foregroundStyle(Palette.onYou)
                        .padding(.horizontal, 20)
                        .frame(height: 44)
                        .background(Palette.you, in: Capsule())
                }
                .card(radius: 26, padding: 14, shadow: true)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Log a workout")
            if let quota = home.quota {
                Text(home.hasLogged ? quota.leftText : "\(quota.leftText), out of \(quota.limit) a day.")
                    .font(.text(13, relativeTo: .footnote))
                    .foregroundStyle(Palette.muted)
            }
        }
        .padding(.top, 4)
    }

    private var question: String {
        app.firstName.isEmpty ? "What did you get up to?" : "What did you get up to, \(app.firstName)?"
    }

    // MARK: Getting started

    private func checklistSection(_ checklist: Checklist) -> some View {
        let steps: [(done: Bool, label: String, help: String)] = [
            (checklist.logged, "Log a workout", "Type it, the way you'd text a friend."),
            (checklist.profile, "Set up your profile", "A handle so friends can find you."),
            (checklist.friends, "Add a friend", "Send your invite link or search by @handle."),
        ]
        return VStack(alignment: .leading, spacing: 10) {
            SectionHead("Getting started")
            VStack(alignment: .leading, spacing: 14) {
                ForEach(steps, id: \.label) { step in
                    HStack(alignment: .top, spacing: 12) {
                        Image(systemName: step.done ? "checkmark.circle.fill" : "circle")
                            .font(.system(size: 22))
                            .foregroundStyle(step.done ? Palette.you : Palette.dashed)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(step.label)
                                .font(.text(16, .semibold))
                                .foregroundStyle(step.done ? Palette.muted : Palette.ink)
                                .strikethrough(step.done, color: Palette.muted2)
                            if !step.done {
                                Text(step.help)
                                    .font(.text(13, relativeTo: .footnote))
                                    .foregroundStyle(Palette.muted)
                            }
                        }
                    }
                    .accessibilityElement(children: .combine)
                    .accessibilityLabel(step.done ? "\(step.label), done" : "\(step.label). \(step.help)")
                }
            }
            .card()
        }
    }

    // MARK: Friends

    private func friendsSection(_ home: Home) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHead("Friends")
            if app.me?.profile == nil {
                note("Set up a profile to see friends' workouts, trade high fives and compare stats.")
            } else if !home.hasFriends {
                note("Add friends by @handle or send them your invite link. Their workouts show up here.")
            } else if home.friends.isEmpty {
                Text("Your friends haven't logged anything yet.")
                    .font(.text(15))
                    .foregroundStyle(Palette.muted)
            } else {
                VStack(spacing: 14) {
                    ForEach(home.friends, id: \.self) { SessionCardView(card: $0) }
                }
            }
        }
    }

    private func note(_ text: String) -> some View {
        Text(text)
            .font(.text(15))
            .foregroundStyle(Palette.ink2)
            .card()
    }

    // MARK: Your recent days

    private func recentSection(_ recent: [RecentSession]) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHead("Your recent")
            VStack(spacing: 0) {
                ForEach(Array(recent.enumerated()), id: \.element) { index, item in
                    if index > 0 { Palette.line2.frame(height: 1) }
                    NavigationLink(value: Route.day(date: item.date, session: item.session, saved: nil)) {
                        HStack(alignment: .firstTextBaseline, spacing: 12) {
                            Text(Days.label(item.date))
                                .font(.text(14, .semibold, relativeTo: .subheadline))
                                .foregroundStyle(Palette.ink)
                                .frame(width: 92, alignment: .leading)
                            Text([item.title, item.summary].filter { !$0.isEmpty }.joined(separator: " · "))
                                .font(.text(14, relativeTo: .subheadline))
                                .foregroundStyle(Palette.ink2)
                                .lineLimit(1)
                            Spacer(minLength: 4)
                            Image(systemName: "chevron.right")
                                .font(.system(size: 12, weight: .semibold))
                                .foregroundStyle(Palette.disabled)
                        }
                        .padding(.vertical, 12)
                        .padding(.horizontal, 16)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
            }
            .card(padding: 0)
        }
    }
}

/// High fives and comments on your own latest workout, shown once there are some.
/// Read-only: the Day it leads to is where you answer.
struct ReactionsBar: View {
    let reactions: Reactions

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                if reactions.kudos > 0 {
                    pill(
                        "\(reactions.kudos) high five\(reactions.kudos == 1 ? "" : "s")",
                        symbol: reactions.kudoed ? "hand.raised.fill" : "hand.raised", filled: true
                    )
                }
                if !reactions.comments.isEmpty {
                    let n = reactions.comments.count
                    pill("\(n) comment\(n == 1 ? "" : "s")", symbol: nil, filled: false)
                }
            }
            if let last = reactions.comments.last {
                (Text((last.author?.name ?? "Someone") + "  ").font(.text(14, .semibold, relativeTo: .subheadline))
                    .foregroundStyle(Palette.ink)
                    + Text(last.body).font(.text(14, relativeTo: .subheadline)).foregroundStyle(Palette.ink2))
                    .lineLimit(1)
            }
        }
    }

    private func pill(_ text: String, symbol: String?, filled: Bool) -> some View {
        HStack(spacing: 6) {
            if let symbol { Image(systemName: symbol).font(.system(size: 13, weight: .semibold)) }
            Text(text).font(.text(14, .semibold, relativeTo: .subheadline))
        }
        .foregroundStyle(filled ? Palette.youInk : Palette.ink2)
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
        .background(filled ? Palette.youTint : Palette.field, in: Capsule())
    }
}
