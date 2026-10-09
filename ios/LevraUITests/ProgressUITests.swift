import XCTest

/// Progress and Day: the three tabs under a range, the week calendar and rest days,
/// search, an exercise's history, then a day's date picker, share picture and editor.
///
/// Needs the local server, like CoreLoopUITests. `testProgressAndDay` renames one of
/// alex's seeded workouts; `testEditThenDelete` logs a workout and deletes it again.
final class ProgressUITests: XCTestCase {
    private let app = XCUIApplication()

    override func setUp() {
        continueAfterFailure = false
    }

    func testProgressAndDay() {
        launchAsAlex(app)

        // Overview, then a shorter range: the grouping follows it.
        app.buttons["Progress"].tap()
        XCTAssertTrue(app.staticTexts["Muscle groups"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["Workouts per month"].exists)
        shot("10-progress")
        app.buttons["90d"].tap()
        XCTAssertTrue(app.staticTexts["Workouts per week"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["Exercise progress"].exists)

        // The calendar: back a week and home again.
        app.tapClear(app.buttons["Previous week"])
        XCTAssertTrue(app.buttons["Back to this week"].waitForExistence(timeout: 10))
        shot("11-progress-week")
        app.tapClear(app.buttons["Back to this week"])
        XCTAssertTrue(app.buttons["Back to this week"].waitForNonExistence(timeout: 10))

        // An empty day flips to rest and back.
        let empty = app.buttons.labelled("Tap to mark as a rest day")
        if empty.exists {
            app.tapClear(empty)
            let rest = app.buttons.labelled("rest day. Tap to clear")
            XCTAssertTrue(rest.waitForExistence(timeout: 10))
            shot("12-progress-rest")
            app.tapClear(rest)
            XCTAssertTrue(rest.waitForNonExistence(timeout: 10))
        }

        // Sessions, searched.
        app.tapClear(app.buttons["Sessions"])
        let search = app.textFields["Search your workouts"]
        XCTAssertTrue(search.waitForExistence(timeout: 10))
        shot("13-sessions")
        search.tap()
        search.typeText("squat")
        XCTAssertTrue(app.staticTexts.labelled("found").waitForExistence(timeout: 10))
        XCTAssertFalse(app.buttons.labelled("deadlift").exists)
        shot("14-search")
        app.buttons["Clear search"].tap()

        // Exercises, and one of them over time.
        app.buttons["Exercises"].tap()
        let squat = app.buttons.labelled("Back squat")
        XCTAssertTrue(squat.waitForExistence(timeout: 10))
        shot("15-exercises")
        app.tapClear(squat)
        XCTAssertTrue(app.staticTexts["Top weight per session"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["Volume per session"].exists)
        shot("16-exercise")

        // From its history to a day.
        app.tapClear(app.buttons.labelled("lbs ·"))
        XCTAssertTrue(app.buttons["Edit this workout"].waitForExistence(timeout: 10))
        shot("17-day")

        // The date picker.
        app.buttons.labelled("Pick a date").tap()
        XCTAssertTrue(app.buttons["Done"].waitForExistence(timeout: 5))
        shot("18-day-picker")
        app.buttons["Done"].tap()

        // The share picture.
        app.buttons["Share this workout"].tap()
        XCTAssertTrue(app.buttons["Share picture"].waitForExistence(timeout: 10))
        shot("19-share")
        app.buttons["Done"].tap()

        // The editor: rename it.
        app.buttons["Edit this workout"].tap()
        let title = app.textFields["Title"]
        XCTAssertTrue(title.waitForExistence(timeout: 10))
        Thread.sleep(forTimeInterval: 0.6)  // the editor is still sliding up
        title.tap()
        title.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: 30) + "Leg day")
        shot("20-day-edit")
        app.buttons["Save changes"].tap()
        XCTAssertTrue(app.staticTexts["Leg day"].waitForExistence(timeout: 10))

        // Previous day logged, then back out to Progress.
        app.buttons.labelled("Previous day logged").tap()
        XCTAssertTrue(app.staticTexts["Leg day"].waitForNonExistence(timeout: 10))
        app.buttons["Back to Progress"].tap()
        XCTAssertTrue(app.staticTexts["Top weight per session"].waitForExistence(timeout: 10))
    }

    func testEditThenDelete() {
        launchAsAlex(app)

        // Log one to work on.
        app.buttons["Log a workout"].firstMatch.tap()
        let words = app.descendants(matching: .any)["Describe your workout"]
        XCTAssertTrue(words.waitForExistence(timeout: 5))
        words.tap()
        words.typeText("benched 185 for 3 sets of 5, then ran 2 miles")
        app.buttons["Log it"].tap()
        XCTAssertTrue(app.staticTexts["Here's what we heard."].waitForExistence(timeout: 15))
        app.buttons["Save workout"].tap()
        XCTAssertTrue(app.staticTexts["Saved"].waitForExistence(timeout: 15))

        // Change a weight and drop the run.
        app.buttons["Edit this workout"].tap()
        let weight = app.textFields["Weight"].firstMatch
        XCTAssertTrue(weight.waitForExistence(timeout: 10))
        XCTAssertEqual(weight.value as? String, "185 lbs")
        weight.coordinate(withNormalizedOffset: CGVector(dx: 0.98, dy: 0.5)).tap()
        weight.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: 7) + "205 lbs")
        app.buttons["Remove run"].tap()
        shot("21-day-edit-rows")
        app.buttons["Save changes"].tap()
        XCTAssertTrue(app.staticTexts.labelled("205 lbs").waitForExistence(timeout: 10))
        XCTAssertFalse(app.staticTexts["Run"].exists)

        // Delete it.
        app.buttons["Edit this workout"].tap()
        let delete = app.buttons["Delete this workout"]
        XCTAssertTrue(delete.waitForExistence(timeout: 10))
        app.tapClear(delete)
        let confirm = app.buttons["Delete workout"]
        XCTAssertTrue(confirm.waitForExistence(timeout: 5))
        shot("22-day-delete")
        confirm.tap()
        XCTAssertTrue(app.buttons["Save changes"].waitForNonExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts.labelled("205 lbs").waitForNonExistence(timeout: 10))
    }
}
