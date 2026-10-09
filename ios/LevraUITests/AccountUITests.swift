import XCTest

/// Deleting an account: somebody new logs a workout, then deletes the account from
/// Settings and lands back on Welcome. Also the links to the terms and the privacy
/// policy, and the muscle icon on a saved day.
///
/// Needs the local server, like CoreLoopUITests. Only ever deletes the blank "New"
/// account it has just made, never a seeded one, and leaves nothing of it behind.
final class AccountUITests: XCTestCase {
    private let app = XCUIApplication()

    override func setUp() {
        continueAfterFailure = false
    }

    func testDeleteAccount() {
        app.launchArguments += ["-resetSignIn"]
        app.launch()

        // Welcome links to the terms and the privacy policy.
        let newPerson = app.buttons["New person"]
        XCTAssertTrue(newPerson.waitForExistence(timeout: 10))
        XCTAssertTrue(app.links["Terms"].exists)
        XCTAssertTrue(app.links["Privacy Policy"].exists)
        shot("70-welcome-legal")

        // Somebody new, with one workout to their name.
        newPerson.tap()
        XCTAssertTrue(app.staticTexts["Log your first workout"].waitForExistence(timeout: 10))
        app.buttons["Log a workout"].firstMatch.tap()
        let words = app.descendants(matching: .any)["Describe your workout"]
        XCTAssertTrue(words.waitForExistence(timeout: 5))
        words.tap()
        words.typeText("benched 185 for 3 sets of 5, then ran 2 miles")
        app.buttons["Log it"].tap()
        XCTAssertTrue(app.staticTexts["Here's what we heard."].waitForExistence(timeout: 15))
        app.tapSave("Save workout", expecting: app.staticTexts["First workout logged"])
        shot("71-day-icon")

        // Settings: asked first, and "Keep my account" keeps it.
        app.buttons["Me"].tap()
        app.buttons["Settings"].tap()
        let delete = app.buttons["Delete account"]
        app.tapClear(delete)
        XCTAssertTrue(app.staticTexts["Delete your account?"].waitForExistence(timeout: 5))
        shot("72-delete-account")
        app.buttons["Keep my account"].tap()
        XCTAssertTrue(app.staticTexts["Settings"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.links["Privacy"].exists && app.links["Terms"].exists)

        // Deleted: back on Welcome, signed out.
        app.tapClear(delete)
        XCTAssertTrue(app.buttons["Delete everything"].waitForExistence(timeout: 5))
        app.buttons["Delete everything"].tap()
        XCTAssertTrue(app.buttons["Continue with Google"].waitForExistence(timeout: 15))
        XCTAssertFalse(app.buttons["Me"].exists)
        shot("73-welcome-after-delete")

        // And still signed out after a restart: nothing was kept on the phone.
        app.terminate()
        let again = XCUIApplication()
        again.launch()
        XCTAssertTrue(again.buttons["Continue with Google"].waitForExistence(timeout: 15))
    }
}
