import Foundation

// What the Friends endpoints send, field for field as gymllm/api/friends.py and the
// Friends part of gymllm/api/schema.py spell it out. Nothing here carries anyone
// else's notes or body weight: the server never sends them.

/// How you stand with someone: "self", "friends", "outgoing" (you asked),
/// "incoming" (they asked) or "none".
enum Relationship {
    static let me = "self"
    static let friends = "friends"
    static let outgoing = "outgoing"
    static let incoming = "incoming"
    static let none = "none"
}

struct ProfileDraft: Codable, Hashable {
    var handle: String
    var name: String
    var bio: String
}

/// GET /profile: your profile, or what the setup form starts from.
struct ProfileForm: Codable {
    let profile: OwnProfile?
    let suggested: ProfileDraft
    let inviter: Person?
}

struct ProfileSaved: Codable {
    let profile: OwnProfile
    let created: Bool
}

struct InviteReset: Codable {
    let inviteUrl: String
    let message: String
}

struct FoundPerson: Codable, Hashable {
    let handle: String
    let name: String
    let avatarUrl: String?
    let bio: String
    let relationship: String

    var person: Person { Person(handle: handle, name: name, avatarUrl: avatarUrl, bio: bio) }
}

/// A high five or a comment someone left on one of your workouts.
struct ActivityEvent: Codable, Hashable {
    let kind: String
    let who: Person?
    let date: String
    let session: Int
    let at: String?
    let body: String
    let new: Bool
}

struct FriendsPage: Codable {
    let q: String
    let results: [FoundPerson]
    let incoming: [Person]
    let outgoing: [Person]
    let friends: [Person]
    let activity: [ActivityEvent]
    let inviteUrl: String
}

/// What a friend request, an accept, an unfriend or an invite answers with.
struct FriendChange: Codable {
    let person: Person
    let relationship: String
    let message: String
}

struct Feed: Codable {
    let cards: [FriendCard]
    let nextBefore: String?
    let hasFriends: Bool
}

struct KudosResult: Codable {
    let count: Int
    let mine: Bool
}

struct CommentRequest: Encodable {
    let body: String
}

struct EmptyBody: Encodable {}

/// A day of the week on a profile. Unlike WeekDay, it has no weigh-in.
struct ProfileDay: Codable, Hashable {
    let date: String
    let letter: String
    let day: Int
    let logged: Bool
    let today: Bool
    let future: Bool
}

struct Last30: Codable, Hashable {
    let sessions: Int
    let sets: Int
    let cardioMinutes: Int
}

struct Favourite: Codable, Hashable {
    let exercise: String
    let sessions: Int
    let best: String
}

/// GET /u/<handle>. Everything after `visible` is there only when you may see
/// their training: yourself or a friend.
struct PersonProfile: Codable {
    let person: Person
    let relationship: String
    let friendCount: Int
    let visible: Bool
    let week: [ProfileDay]?
    let streak: Int?
    let last30: Last30?
    let favourites: [Favourite]?
    let prs: [PersonalBest]?
    let cards: [FriendCard]?
    let total: Int?
}

struct CompareTotal: Codable, Hashable {
    let label: String
    let mine: Double
    let theirs: Double
    /// "mine", "theirs" or nil when level or not comparable.
    let lead: String?
    /// The two people's units, when they differ and so nobody leads.
    let units: [String]?
}

struct CompareBest: Codable, Hashable {
    let sessions: Int
    let value: Double?
    let text: String
}

struct SharedLift: Codable, Hashable {
    let exercise: String
    let mine: CompareBest
    let theirs: CompareBest
    let lead: String?
    let diff: Double?
    let unit: String
}

struct CompareFavourite: Codable, Hashable {
    let exercise: String
    let shared: Bool
}

struct CompareFavourites: Codable, Hashable {
    let mine: [CompareFavourite]
    let theirs: [CompareFavourite]
}

struct MuscleShare: Codable, Hashable {
    let tag: String
    let mine: Int
    let theirs: Int
}

struct WeekPair: Codable, Hashable {
    let label: String
    let mine: Int
    let theirs: Int
}

struct Comparison: Codable {
    let me: Person?
    let other: Person
    let range: String
    let empty: Bool
    let totals: [CompareTotal]
    let shared: [SharedLift]
    let favourites: CompareFavourites
    let muscles: [MuscleShare]
    let weekly: [WeekPair]
}
