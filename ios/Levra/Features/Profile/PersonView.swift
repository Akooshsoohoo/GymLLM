import SwiftUI

/// Someone's profile: who they are, how you stand with them, and, for a friend,
/// their last 30 days, favourites, week, new bests and recent workouts. Mirrors
/// templates/profile.html. A stranger's shows who it is and nothing else.
struct PersonView: View {
    @Environment(AppState.self) private var app
    let handle: String
    var backTitle = "Back"

    @State private var profile: PersonProfile?
    @State private var error: String?
    @State private var notice: String?
    @State private var confirmingUnfriend = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                BackLink(title: backTitle)
                if let notice { NoteBanner(message: notice) }
                if let error { ErrorBanner(message: error) }
                if let profile {
                    ProfileHeader(person: profile.person, friendCount: profile.friendCount, own: false)
                    actions(profile)
                    ProfileBody(profile: profile)
                } else if error == nil {
                    ProgressView()
                        .frame(maxWidth: .infinity)
                        .padding(.top, 60)
                }
            }
            .padding(.horizontal, Metrics.gutter)
            .padding(.top, 8)
            .padding(.bottom, 28)
        }
        .background(Palette.bg)
        .toolbar(.hidden, for: .navigationBar)
        .dismissesKeyboard()
        .refreshable { await load() }
        .task(id: app.changes) { await load() }
    }

    @ViewBuilder
    private func actions(_ profile: PersonProfile) -> some View {
        let person = profile.person
        HStack(spacing: 10) {
            RelationshipActions(person: person, relationship: profile.relationship, act: act)
            if profile.relationship == Relationship.friends {
                Button("Friends ✓") { confirmingUnfriend = true }
                    .buttonStyle(.pill(.ghost, height: 44))
                    .accessibilityLabel("Friends. Unfriend \(person.name)")
            }
            Spacer(minLength: 0)
        }
        .confirmationDialog("Unfriend \(person.name)?", isPresented: $confirmingUnfriend, titleVisibility: .visible) {
            Button("Unfriend", role: .destructive) { act("remove") }
            Button("Stay friends", role: .cancel) {}
        } message: {
            Text("You'll stop seeing each other's workouts.")
        }
    }

    private func load() async {
        do {
            profile = try await app.api.get("/u/\(handle)")
            error = nil
        } catch let failure {
            error = app.message(for: failure)
        }
    }

    private func act(_ action: String) {
        Task {
            do {
                let change: FriendChange = try await app.api.post("/friends/\(action)/\(handle)")
                notice = change.message.isEmpty ? nil : change.message
                error = nil
                app.didChange()  // loads this again, and Friends behind it
            } catch let failure {
                error = app.message(for: failure)
            }
        }
    }
}

/// The picture, the name, the handle and the bio.
struct ProfileHeader: View {
    let person: Person
    let friendCount: Int
    let own: Bool

    var body: some View {
        HStack(alignment: .center, spacing: 14) {
            Avatar(name: person.name, url: person.avatarUrl, size: 72, tone: own ? .you : .friend)
            VStack(alignment: .leading, spacing: 3) {
                Text(person.name)
                    .font(.head(26, relativeTo: .title))
                    .tracking(-0.4)
                    .foregroundStyle(Palette.ink)
                    .fixedSize(horizontal: false, vertical: true)
                Text("@\(person.handle) · \(friendCount) friend\(friendCount == 1 ? "" : "s")")
                    .font(.text(14, .medium, relativeTo: .subheadline))
                    .foregroundStyle(Palette.muted)
                if !person.bio.isEmpty {
                    Text(person.bio)
                        .font(.text(15))
                        .foregroundStyle(Palette.ink2)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(.top, 2)
                }
            }
        }
    }
}

/// What a profile shows below the name: the same for a friend's and your own.
struct ProfileBody: View {
    let profile: PersonProfile

    private var own: Bool { profile.relationship == Relationship.me }
    private var name: String { profile.person.name }

    var body: some View {
        if !profile.visible {
            EmptyNote(text: hidden) { EmptyView() }
        } else if (profile.total ?? 0) == 0 {
            Text(own ? "You haven't logged anything yet." : "\(name) hasn't logged anything yet.")
                .font(.text(15))
                .foregroundStyle(Palette.ink2)
                .card()
        } else {
            if let last = profile.last30 { stats(last) }
            favourites(profile.favourites ?? [])
            if let week = profile.week { ProfileWeek(week: week, own: own) }
            if let bests = profile.prs, !bests.isEmpty { newBests(bests) }
            if let cards = profile.cards, !cards.isEmpty {
                VStack(alignment: .leading, spacing: 10) {
                    SectionHead("Recent sessions")
                    ForEach(cards, id: \.self) { SessionCardView(card: $0, showOwner: false) }
                }
            }
        }
    }

    private var hidden: String {
        switch profile.relationship {
        case Relationship.incoming: "\(name) wants to be friends. Accept to see each other's training."
        case Relationship.outgoing: "Once \(name) accepts, you'll see each other's training here."
        default: "Add \(name) as a friend to see their training and compare stats."
        }
    }

    private func stats(_ last: Last30) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                StatTile(label: "Workouts", value: String(last.sessions))
                StatTile(label: "Sets", value: String(last.sets))
                StatTile(label: "Cardio", value: String(last.cardioMinutes), unit: "min")
            }
            let streak = profile.streak ?? 0
            Text("Last 30 days" + (streak > 0 ? " · \(streak)-week streak" : ""))
                .font(.text(13, relativeTo: .footnote))
                .foregroundStyle(Palette.muted)
        }
    }

    private func favourites(_ items: [Favourite]) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            CardHead("Favourites")
            if items.isEmpty {
                Text("No lifts logged yet.")
                    .font(.text(15))
                    .foregroundStyle(Palette.muted)
            }
            ForEach(Array(items.enumerated()), id: \.offset) { index, item in
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    Text(String(index + 1))
                        .font(.head(15))
                        .monospacedDigit()
                        .foregroundStyle(own ? Palette.youInk : Palette.friendInk)
                        .frame(width: 18, alignment: .leading)
                    Text(item.exercise.capFirst)
                        .font(.text(15, .medium))
                        .foregroundStyle(Palette.ink)
                    Spacer(minLength: 8)
                    Text("\(item.sessions) session\(item.sessions == 1 ? "" : "s")" + (item.best.isEmpty ? "" : " · best \(item.best)"))
                        .font(.text(13, relativeTo: .footnote))
                        .monospacedDigit()
                        .foregroundStyle(Palette.muted)
                        .multilineTextAlignment(.trailing)
                }
                .accessibilityElement(children: .combine)
            }
        }
        .card()
    }

    private func newBests(_ bests: [PersonalBest]) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            CardHead("New personal bests")
            ForEach(bests, id: \.self) { best in
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    VStack(alignment: .leading, spacing: 1) {
                        Text(best.exercise.capFirst)
                            .font(.text(15, .medium))
                            .foregroundStyle(Palette.ink)
                        Text("\(Days.label(best.date)) · up from \(Numbers.plain(best.previous))")
                            .font(.text(13, relativeTo: .footnote))
                            .foregroundStyle(Palette.muted)
                    }
                    Spacer(minLength: 8)
                    Text(best.weight)
                        .font(.head(17))
                        .monospacedDigit()
                        .foregroundStyle(Palette.ink)
                }
                .accessibilityElement(children: .combine)
            }
        }
        .card()
    }
}

/// "This week" as seven circles: green for you, clay for someone else.
private struct ProfileWeek: View {
    let week: [ProfileDay]
    let own: Bool

    var body: some View {
        let logged = week.filter(\.logged).count
        VStack(alignment: .leading, spacing: 14) {
            CardHead(title: "This week") {
                Text("\(logged) of 7 days")
                    .font(.text(13, .medium, relativeTo: .footnote))
                    .foregroundStyle(Palette.muted)
            }
            HStack(spacing: 0) {
                ForEach(week, id: \.date) { day in
                    VStack(spacing: 6) {
                        dot(day)
                        Text(day.letter)
                            .font(.text(12, .semibold, relativeTo: .caption))
                            .foregroundStyle(day.today ? Palette.ink : Palette.muted2)
                    }
                    .frame(maxWidth: .infinity)
                }
            }
            .accessibilityHidden(true)
        }
        .card()
        .accessibilityElement(children: .combine)
    }

    @ViewBuilder
    private func dot(_ day: ProfileDay) -> some View {
        let tone = own ? Palette.you : Palette.friend
        if day.logged {
            Circle().fill(tone).frame(width: 34, height: 34)
        } else if day.today {
            Circle().strokeBorder(tone, style: StrokeStyle(lineWidth: 2, dash: [4, 3])).frame(width: 34, height: 34)
        } else {
            Circle().fill(Palette.track).frame(width: 34, height: 34)
        }
    }
}
