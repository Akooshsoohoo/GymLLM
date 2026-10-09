import XCTest

/// The core loop, end to end: dev sign-in, Home, Log, Review with an edited value,
/// Save, and the Day it lands on.
///
/// Needs the local server: `python ios/scripts/dev_server.py`. Each run saves one
/// workout to the dev account "alex" in the local SQLite database. Screenshots are
/// attached to the test report, and also written to SHOTS_DIR when that is set
/// (pass it to xcodebuild as TEST_RUNNER_SHOTS_DIR, and TEST_RUNNER_SHOTS_NAME to
/// label them). For dark mode, run `xcrun simctl ui booted appearance dark` first.
final class CoreLoopUITests: XCTestCase {
    private let app = XCUIApplication()

    override func setUp() {
        continueAfterFailure = false
    }

    func testCoreLoop() {
        app.launchArguments += ["-resetSignIn"]
        app.launch()

        // Welcome, then a seeded account.
        XCTAssertTrue(app.buttons["Continue with Google"].waitForExistence(timeout: 10))
        shot("01-welcome")
        app.buttons["Alex"].tap()

        // Home.
        XCTAssertTrue(app.staticTexts["Friends"].waitForExistence(timeout: 10))
        shot("02-home")

        // Log.
        app.buttons["Log a workout"].firstMatch.tap()
        let words = app.descendants(matching: .any)["Describe your workout"]
        XCTAssertTrue(words.waitForExistence(timeout: 5))
        words.tap()
        words.typeText("benched 185 for 3 sets of 5, then ran 2 miles")
        shot("03-log")
        app.buttons["Log it"].tap()

        // Review: fix the weight in place, add a time to the run.
        XCTAssertTrue(app.staticTexts["Here's what we heard."].waitForExistence(timeout: 15))
        shot("04-review")
        let weight = app.textFields["Weight"].firstMatch
        XCTAssertEqual(weight.value as? String, "185 lbs")
        weight.coordinate(withNormalizedOffset: CGVector(dx: 0.98, dy: 0.5)).tap()  // caret at the end
        weight.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: 7) + "190 lbs")
        XCTAssertEqual(weight.value as? String, "190 lbs")
        let time = app.textFields["Time"].firstMatch
        time.tap()
        time.typeText("18 min")
        shot("05-review-edited")

        // Day, with what was edited.
        app.tapSave("Save workout", expecting: app.staticTexts["Saved"])
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format: "label CONTAINS '190 lbs'")).firstMatch.exists)
        shot("06-day")

        // Back on Home, the workout leads.
        app.buttons["Back to Home"].tap()
        XCTAssertTrue(app.buttons["Details"].waitForExistence(timeout: 10))
        XCTAssertFalse(app.staticTexts["Saved"].exists)

        // The Home tab, tapped from a day, also goes back to the top of Home.
        app.buttons["Details"].tap()
        XCTAssertTrue(app.buttons["Back to Home"].waitForExistence(timeout: 10))
        app.buttons["Home"].tap()
        XCTAssertTrue(app.buttons["Details"].waitForExistence(timeout: 10))
        shot("07-home-after")
    }
}
