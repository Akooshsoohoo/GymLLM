import Foundation

// Routines, the manual form's names, the checklist and a day's visibility, as
// gymllm/api/record.py sends them.

/// A routine on the list.
struct RoutineRow: Codable, Hashable, Identifiable {
    let id: Int
    let name: String
    let blockCount: Int

    var blocksText: String { "\(blockCount) block\(blockCount == 1 ? "" : "s")" }
}

struct RoutineList: Codable {
    let routines: [RoutineRow]
}

struct RoutineBlock: Codable, Hashable {
    var name = ""
    var body = ""
}

/// A routine with its blocks, in order.
struct Routine: Codable, Hashable, Identifiable {
    let id: Int
    let name: String
    let blocks: [RoutineBlock]
}

struct RoutineRequest: Encodable {
    let name: String
    let blocks: [RoutineBlock]
}

/// What the manual form suggests as you type a name.
struct ManualNames: Codable {
    let exercises: [String]
    let activities: [String]
}

struct VisibilityRequest: Encodable {
    let visibility: String
}

struct DayVisibility: Codable {
    let date: String
    let visibility: String
}

/// An answer with nothing in it the app needs.
struct Done: Decodable {}
