import Foundation

// What the Progress and day-edit endpoints send (gymllm/api/progress.py, with the
// serialisers at the bottom of gymllm/api/schema.py). Numbers here are the ones the
// server worked out for charts; the weights people typed stay text.

struct ProgressTotals: Codable, Hashable {
    let sessions: Int
    let entries: Int
    let exercises: Int
    let volume: Double
    let cardio: Int
    let cardioDistance: String
    let cardioMinutes: String
}

/// One bar of "Workouts per week".
struct PeriodCount: Codable, Hashable {
    let label: String
    let title: String
    let sessions: Int
    let current: Bool
}

struct WeekCard: Codable, Hashable {
    let start: String
    let end: String
    let previous: String?
    /// Nil on this week: there is nothing after it.
    let next: String?
    let isThisWeek: Bool
    let days: [WeekDay]
}

struct RestRule: Codable, Hashable, Identifiable {
    let id: Int
    /// "weekdays" or "interval".
    let kind: String
    /// Monday is 0.
    let weekdays: [Int]?
    let intervalDays: Int?
    let anchorDate: String?
}

struct RestRules: Codable {
    let restRules: [RestRule]
}

struct RestRuleRequest: Encodable {
    let kind: String
    var weekdays: [Int]?
    var intervalDays: Int?
    var anchorDate: String?
}

struct RestDayRequest: Encodable {
    let rest: Bool
}

struct RestDay: Codable {
    let date: String
    let rest: Bool
}

struct BodyweightPeriod: Codable, Hashable {
    let key: String
    let label: String
    /// Nil for a period without a reading.
    let weight: Double?
}

/// Your own weigh-ins over the range. Never in anyone else's payload.
struct BodyweightTrend: Codable, Hashable {
    let latest: String
    let latestDate: String
    let change: Double?
    let unit: String
    let since: String?
    let chartUnit: String
    let charted: Int
    let periods: [BodyweightPeriod]
}

/// One session of an exercise: its top weight, and weight × reps summed.
struct SeriesPoint: Codable, Hashable {
    let date: String
    /// Nil when no weight led with a number ("bodyweight").
    let weight: Double?
    let volume: Double?
    let reps: Int?
}

struct LiftProgress: Codable, Hashable {
    let exercise: String
    let first: Double
    let latest: Double
    let change: Double?
    let pct: Int?
    let unit: String
    let series: [SeriesPoint]
}

struct TagCount: Codable, Hashable {
    let tag: String
    let count: Int
}

struct TopExercise: Codable, Hashable {
    let exercise: String
    let entries: Int
    let sessions: Int
    let best: String?
    let last: String
}

struct PersonalBest: Codable, Hashable {
    let exercise: String
    let date: String
    let session: Int
    let weight: String
    let value: Double
    let previous: Double
}

struct ProgressOverview: Codable {
    let range: String
    let by: String
    /// Everything you have ever logged, whatever the range.
    let total: Int
    let totals: ProgressTotals
    let streak: Int
    let perPeriod: [PeriodCount]
    let week: WeekCard
    let restRules: [RestRule]
    let bodyweight: BodyweightTrend?
    let lifts: [LiftProgress]
    let tags: [TagCount]
    let topExercises: [TopExercise]
    let prs: [PersonalBest]
    let weightUnit: String

    var isEmptyRange: Bool { totals.entries == 0 && totals.cardio == 0 && bodyweight == nil }
}

// MARK: Sessions

/// A line of a Sessions tile. Lifts and cardio alike, so the name is just `name`.
struct TileLine: Codable, Hashable {
    let name: String
    let detail: String
    let parts: [String]
    let pr: Bool
}

struct SessionTile: Codable, Hashable {
    let date: String
    let session: Int
    let title: String
    let iconHint: String
    let lines: [TileLine]
    let bodyweight: String?
}

struct SessionMonth: Codable, Hashable {
    let key: String
    let label: String
    let days: [SessionTile]
}

struct SessionList: Codable {
    let range: String
    let months: [SessionMonth]
    let shown: Int
    let total: Int
}

// MARK: Exercises

struct ExerciseRow: Codable, Hashable {
    let exercise: String
    let entries: Int
    let sessions: Int
    let first: String
    let last: String
    let best: String?
    /// Top weight per session, oldest first.
    let spark: [Double]
}

struct CardioRow: Codable, Hashable {
    let activity: String
    let count: Int
    let distance: String
    let minutes: String
    let last: String
}

struct ExerciseList: Codable {
    let range: String
    let exercises: [ExerciseRow]
    let cardio: [CardioRow]
    let total: Int
}

struct ExerciseBest: Codable, Hashable {
    let date: String
    let value: Double
    let weight: String
}

/// One logged line of an exercise, with the day it belongs to.
struct ExerciseEntry: Codable, Hashable, Identifiable {
    let id: Int
    let date: String
    let session: Int
    let weight: String
    let sets: String
    let reps: String
    let setsReps: String
    let notes: String?
}

struct ExerciseDetail: Codable {
    let name: String
    let tags: [String]
    /// Every entry ever, whatever the range.
    let total: Int
    let sessions: Int
    let best: ExerciseBest?
    let volume: Double
    let lastDate: String?
    let series: [SeriesPoint]
    let progress: LiftProgress?
    let entries: [ExerciseEntry]
    let range: String
    let weightUnit: String
}

// MARK: Editing a workout

/// One row of PUT /day/<when>/sessions/<n>. With an id it changes that row, or
/// removes it when `delete` is set; without one it is a new row.
struct LiftEdit: Encodable {
    var id: Int?
    var delete: Bool?
    var exercise: String?
    var weight: String?
    var sets: String?
    var reps: String?
    var notes: String?
}

struct CardioEdit: Encodable {
    var id: Int?
    var delete: Bool?
    var activity: String?
    var distance: String?
    var duration: String?
    var notes: String?
}

struct DayEditRequest: Encodable {
    let date: String
    let title: String
    let visibility: String
    /// Left out unless this workout carries the day's weigh-in; "" clears it.
    let bodyweight: String?
    let lifts: [LiftEdit]
    let cardio: [CardioEdit]
}

struct DayEditResult: Codable, Hashable {
    let date: String
    let session: Int
    /// No lifts or cardio are left in this workout...
    let removed: Bool
    /// ...but the weigh-in edited with it still is.
    let weighInLeft: Bool
}
