import XCTest

/// Record, routines and the rest: a recording that outlives the app, a routine made,
/// started, changed and deleted, the manual form's suggestions, a day's visibility,
/// Settings, and hiding the getting-started checklist.
///
/// Needs the local server, like CoreLoopUITests. `testRecordSurvivesBeingKilled`
/// saves one workout to alex; `testSettingsAndChecklist` leaves one new account behind.
final class RecordUITests: XCTestCase {
    private let app = XCUIApplication()

    override func setUp() {
        continueAfterFailure = false
    }

    private func field(_ label: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any)[label]
    }

    func testRecordSurvivesBeingKilled() {
        launchAsAlex(app)

        // Idle, then live with two blocks.
        app.buttons["Record a workout"].tap()
        XCTAssertTrue(app.buttons["Start workout"].waitForExistence(timeout: 10))
        shot("50-record-idle")
        app.buttons["Start workout"].tap()
        let notes = field("Block 1 notes", in: app)
        XCTAssertTrue(notes.waitForExistence(timeout: 10))
        notes.tap()
        notes.typeText("Bench 185, 3 sets of 5")
        app.buttons["+ Add a block"].tap()
        let name = app.textFields["Block 2 name"]
        XCTAssertTrue(name.waitForExistence(timeout: 10))
        name.tap()
        name.typeText("Cardio")
        let more = field("Block 2 notes", in: app)
        more.tap()
        more.typeText("Ran 2 miles")
        shot("51-record-live")

        // Killed and opened again: still signed in, still recording, nothing lost.
        app.terminate()
        let again = XCUIApplication()
        again.launch()
        let back = again.buttons["Back to your workout"]
        XCTAssertTrue(back.waitForExistence(timeout: 15))
        shot("52-record-tab")
        back.tap()
        XCTAssertTrue(field("Block 1 notes", in: again).waitForExistence(timeout: 10))
        XCTAssertEqual(field("Block 1 notes", in: again).value as? String, "Bench 185, 3 sets of 5")
        XCTAssertEqual(again.textFields["Block 2 name"].value as? String, "Cardio")
        XCTAssertEqual(field("Block 2 notes", in: again).value as? String, "Ran 2 miles")

        // Close keeps it running; Stop finishes it.
        again.buttons["Close"].tap()
        XCTAssertTrue(back.waitForExistence(timeout: 10))
        back.tap()
        again.buttons["Stop"].tap()
        XCTAssertTrue(again.staticTexts["Finish workout?"].waitForExistence(timeout: 10))
        XCTAssertTrue(again.staticTexts.labelled("2 blocks").exists)
        shot("53-record-finish")
        again.buttons["Log it"].tap()
        XCTAssertTrue(again.staticTexts["Here's what we heard."].waitForExistence(timeout: 15))
        again.buttons["Save workout"].tap()
        XCTAssertTrue(again.staticTexts["Saved"].waitForExistence(timeout: 15))
        XCTAssertTrue(again.buttons["Record a workout"].exists)  // the recording is done with

        // Who can see the day, changed where it is shown.
        let who = again.otherElements["Who can see this"]
        again.tapClear(who.buttons["Private"])
        XCTAssertTrue(again.staticTexts.labelled("Only you.").waitForExistence(timeout: 10))
        shot("54-day-private")
        who.buttons["Friends"].tap()
        XCTAssertTrue(again.staticTexts.labelled("Your friends, in their feed.").waitForExistence(timeout: 10))
    }

    /// Save the routine editor and wait for the list. After typing, the simulator
    /// brings its keyboard back on the next touch and the save bar moves out from
    /// under the tap, so a tap that didn't take is made once more.
    private func saveRoutine(expecting name: String) {
        app.buttons["Save routine"].tap()
        if !app.staticTexts[name].waitForExistence(timeout: 3), app.buttons["Save routine"].exists {
            app.buttons["Save routine"].tap()
        }
        XCTAssertTrue(app.staticTexts[name].waitForExistence(timeout: 10))
    }

    func testRoutines() {
        launchAsAlex(app)
        let routine = "Push \(Int.random(in: 1000...9999))"

        // A new routine, with a line left to fill in.
        app.buttons["Record a workout"].tap()
        XCTAssertTrue(app.buttons["Manage routines"].waitForExistence(timeout: 10))
        app.buttons["Manage routines"].tap()
        XCTAssertTrue(app.buttons["New routine"].waitForExistence(timeout: 10))
        app.buttons["New routine"].tap()
        let name = app.textFields["Name"]
        XCTAssertTrue(name.waitForExistence(timeout: 10))
        name.tap()
        name.typeText(routine)
        let block = field("Block 1, what to do", in: app)
        block.tap()
        block.typeText("Bench press 185 lbs, 3 sets of ___\nDips 3 sets of 8")
        shot("55-routine-edit")
        saveRoutine(expecting: routine)
        shot("56-routines")

        // Started: the recorder opens on its blocks, and the unfilled line is skipped.
        app.buttons["Start \(routine)"].tap()
        let notes = field("Block 1 notes", in: app)
        XCTAssertTrue(notes.waitForExistence(timeout: 10))
        XCTAssertTrue((notes.value as? String ?? "").contains("Dips 3 sets of 8"))
        XCTAssertTrue(app.staticTexts[routine].exists)
        shot("57-record-routine")
        app.buttons["Stop"].tap()
        XCTAssertTrue(app.staticTexts["1 line left blank, skipped."].waitForExistence(timeout: 10))
        app.buttons["Keep going"].tap()

        // Discarded: back to the start.
        app.buttons["Discard workout"].tap()
        XCTAssertTrue(app.buttons["Discard"].waitForExistence(timeout: 5))
        app.buttons["Discard"].tap()
        XCTAssertTrue(app.buttons["Start workout"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.buttons.labelled("Start \(routine)").exists)

        // Renamed, then deleted.
        app.buttons["Manage routines"].tap()
        app.tapClear(app.buttons["Edit \(routine)"])
        XCTAssertTrue(name.waitForExistence(timeout: 10))
        XCTAssertEqual(name.value as? String, routine)
        name.coordinate(withNormalizedOffset: CGVector(dx: 0.98, dy: 0.5)).tap()
        name.typeText(" B")
        saveRoutine(expecting: "\(routine) B")
        app.tapClear(app.buttons["Delete \(routine) B"])
        XCTAssertTrue(app.buttons["Delete"].waitForExistence(timeout: 5))
        app.buttons["Delete"].tap()
        XCTAssertTrue(app.staticTexts["\(routine) B"].waitForNonExistence(timeout: 10))
    }

    func testSettingsAndChecklist() {
        launchAsAlex(app)

        // The manual form offers names as you type one.
        app.buttons["Record a workout"].tap()
        XCTAssertTrue(app.buttons["Add manually"].waitForExistence(timeout: 10))
        app.buttons["Add manually"].tap()
        let exercise = app.textFields["Exercise"].firstMatch
        XCTAssertTrue(exercise.waitForExistence(timeout: 10))
        exercise.tap()
        exercise.typeText("barbell ben")
        let pick = app.buttons["Use Barbell Bench Press"]
        XCTAssertTrue(pick.waitForExistence(timeout: 10))
        shot("58-manual")
        pick.tap()
        XCTAssertEqual(exercise.value as? String, "Barbell Bench Press")
        app.buttons["Cancel"].tap()

        // Settings: the theme, then back to following the phone.
        app.buttons["Me"].tap()
        app.buttons["Settings"].tap()
        let theme = app.otherElements["Theme"]
        XCTAssertTrue(theme.waitForExistence(timeout: 10))
        shot("59-settings")
        theme.buttons["Dark"].tap()
        XCTAssertTrue(theme.buttons["Dark"].isSelected)
        shot("60-settings-dark")
        theme.buttons["Light"].tap()
        shot("61-settings-light")
        theme.buttons["System"].tap()
        app.tapClear(app.buttons["Sign out"])

        // Somebody new hides the getting-started card for good.
        XCTAssertTrue(app.buttons["New person"].waitForExistence(timeout: 10))
        app.buttons["New person"].tap()
        XCTAssertTrue(app.staticTexts["Getting started"].waitForExistence(timeout: 10))
        shot("62-checklist")
        app.tapClear(app.buttons["Hide getting started"])
        XCTAssertTrue(app.staticTexts["Getting started"].waitForNonExistence(timeout: 10))
        app.buttons["Progress"].tap()
        app.buttons["Home"].tap()
        XCTAssertTrue(app.staticTexts["Log your first workout"].waitForExistence(timeout: 10))
        XCTAssertFalse(app.staticTexts["Getting started"].exists)
    }
}
