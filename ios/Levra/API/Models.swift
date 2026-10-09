import Foundation

// What /api/v1 sends, field for field as gymllm/api/schema.py and gymllm/api/core.py
// spell it out. Keys arrive in snake_case and are converted by the decoder.
// Weights, distances and durations are text as the user wrote them ("185 lbs",
// "3 miles", "bodyweight"): never numbers on the client.

struct Person: Codable, Hashable {
    let handle: String
    let name: String
    let avatarUrl: String?
    let bio: String
}

struct OwnProfile: Codable, Hashable {
    let handle: String
    let name: String
    let avatarUrl: String?
    let bio: String
    let inviteUrl: String
}

struct Quota: Codable, Hashable {
    let left: Int
    let limit: Int
}

struct Me: Codable, Hashable {
    let email: String
    let firstName: String
    var profile: OwnProfile?
    var weightUnit: String
    /// Nil when the server has no shared model set up.
    let quota: Quota?
    let unseen: Int
}

struct AuthResponse: Codable {
    let token: String
    let user: Me
}

struct Lift: Codable, Hashable, Identifiable {
    let id: Int
    let exercise: String
    let weight: String
    let sets: String
    let reps: String
    let setsReps: String
    let tags: [String]
    let pr: Bool
    /// Only ever present on your own lifts.
    let notes: String?
}

struct CardioEntry: Codable, Hashable, Identifiable {
    let id: Int
    let activity: String
    let distance: String
    let duration: String
    let notes: String?
}

/// One line per exercise, as the session cards show it. An exercise logged at one
/// weight has `detail` ("185 lbs · 5×5"); at several, `parts` (one clause each).
struct ExerciseLine: Codable, Hashable {
    let exercise: String
    let detail: String
    let parts: [String]
    let pr: Bool
}

struct Comment: Codable, Hashable, Identifiable {
    let id: Int
    let body: String
    let at: String?
    let author: Person?
    let canDelete: Bool
}

struct Reactions: Codable, Hashable {
    let kudos: Int
    let kudoed: Bool
    let comments: [Comment]
}

struct MyCard: Codable, Hashable {
    let date: String
    let session: Int
    let title: String
    let iconHint: String
    let statLine: String
    let lifts: [Lift]
    let cardio: [CardioEntry]
    let lines: [ExerciseLine]
    let bodyweight: String?
    let reactions: Reactions?
}

struct FriendCard: Codable, Hashable {
    let owner: Person?
    let date: String
    let session: Int
    let title: String
    let iconHint: String
    let lifts: [Lift]
    let cardio: [CardioEntry]
    let lines: [ExerciseLine]
    let prs: Int
    let reactions: Reactions?
}

struct WeekDay: Codable, Hashable {
    let date: String
    let letter: String
    let day: Int
    let logged: Bool
    let rest: Bool
    let today: Bool
    let future: Bool
    let exercises: Int
    let sets: Int
    let cardio: String
    let bodyweight: String
}

struct RecentSession: Codable, Hashable {
    let date: String
    let session: Int
    let title: String
    let summary: String
}

struct Checklist: Codable, Hashable {
    let logged: Bool
    let profile: Bool
    let friends: Bool
}

struct Home: Codable {
    let today: String
    let week: [WeekDay]
    let streak: Int
    let latest: MyCard?
    let justSaved: Bool
    let firstSave: Bool
    let hasLogged: Bool
    let recent: [RecentSession]
    let friends: [FriendCard]
    let hasFriends: Bool
    /// Nil once every step is done or the card was hidden.
    let checklist: Checklist?
    let quota: Quota?
}

/// A lift as the review screen edits it and POST /sessions takes it.
struct EntryDraft: Codable, Hashable {
    var exercise = ""
    var weight = ""
    var sets = ""
    var reps = ""
    var notes = ""
}

struct CardioDraft: Codable, Hashable {
    var activity = ""
    var distance = ""
    var duration = ""
    var notes = ""
}

struct ParseResult: Codable {
    let date: String
    let dateFromText: Bool
    let entries: [EntryDraft]
    let cardio: [CardioDraft]
    let bodyweight: String?
    /// The routine's name when the workout started from one, else empty.
    let title: String
    let defaultTitle: String
    let visibility: String
    let firstLog: Bool
    let weightUnit: String
    let quota: Quota?
}

struct ParseRequest: Encodable {
    let text: String
    let weightUnit: String
    /// The routine a recording started from: the workout takes its name.
    var routineName: String?
}

struct SaveRequest: Encodable {
    let date: String
    let title: String
    let visibility: String
    let entries: [EntryDraft]
    let cardio: [CardioDraft]
    let bodyweight: String
}

struct SavedSession: Codable, Hashable {
    let date: String
    let session: Int
}

struct SessionRef: Codable, Hashable {
    let session: Int
    let title: String
}

struct DayStats: Codable, Hashable {
    let exercises: Int
    let entries: Int
    let sets: Int
    let reps: Int
    let volume: Double
    let cardioDistance: String
    let cardioMinutes: String
}

struct DayDetail: Codable, Identifiable {
    var id: String { "\(date)#\(session)" }

    let date: String
    let session: Int
    let title: String
    let iconHint: String
    /// Which muscle icon stands for the day: "chest", "run". Nil from an older server.
    let icon: String?
    let statLine: String
    /// The day's workouts when there is more than one, else empty.
    let sessions: [SessionRef]
    let lifts: [Lift]
    let cardio: [CardioEntry]
    let lines: [ExerciseLine]
    let bodyweight: String?
    let stats: DayStats
    let reactions: Reactions?
    let previous: String?
    let next: String?
    /// What the editor starts from, beside the lifts and cardio above.
    let defaultTitle: String
    let visibility: String
    /// The day's weigh-in is edited along with the day's first workout only.
    let editsBodyweight: Bool

    var isEmpty: Bool { lifts.isEmpty && cardio.isEmpty && bodyweight == nil }
}

struct PreferencesRequest: Encodable {
    let weightUnit: String
}

struct Preferences: Codable {
    let weightUnit: String
}

struct AccountDeleted: Decodable {
    let deleted: Bool
}

struct DevSignIn: Encodable {
    let slug: String
}

struct GoogleSignInRequest: Encodable {
    let idToken: String
}
