import XCTest

/// Friends: the feed with a high five and a comment, People with search, a friend's
/// profile and Compare, Me with a profile edit; then a brand-new person setting up
/// a profile and joining by a pasted invite link.
///
/// Needs the local server, like CoreLoopUITests. `testFriends` gives and takes back
/// a high five, posts and deletes a comment, and sets alex's bio.
/// `testNewPersonJoinsByInvite` leaves a new account behind, friends with alex.
final class FriendsUITests: XCTestCase {
    private let app = XCUIApplication()

    override func setUp() {
        continueAfterFailure = false
    }

    private var friendsTab: XCUIElement { button(startingWith: "Friends") }

    /// The People half of Friends, whose label carries a count when something is new.
    private var people: XCUIElement { button(startingWith: "People") }

    private func button(startingWith text: String) -> XCUIElement {
        app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", text)).firstMatch
    }

    func testFriends() {
        launchAsAlex(app)

        // The feed: a high five given and taken back.
        friendsTab.tap()
        let give = app.buttons["Give a high five"].firstMatch
        XCTAssertTrue(give.waitForExistence(timeout: 10))
        shot("30-feed")
        give.tap()
        let takeBack = app.buttons["Take back high five"].firstMatch
        XCTAssertTrue(takeBack.waitForExistence(timeout: 10))
        XCTAssertEqual(takeBack.value as? String, "1")
        takeBack.tap()
        XCTAssertTrue(takeBack.waitForNonExistence(timeout: 10))

        // A comment, posted and deleted.
        app.buttons["Comment"].firstMatch.tap()
        let box = app.textFields["Add a comment"]
        XCTAssertTrue(box.waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["No comments yet."].exists)
        box.tap()
        box.typeText("Strong work")
        app.buttons["Post"].tap()
        XCTAssertTrue(app.staticTexts["Strong work"].waitForExistence(timeout: 10))
        shot("31-comments")
        app.buttons["Delete comment"].tap()
        XCTAssertTrue(app.staticTexts["Strong work"].waitForNonExistence(timeout: 10))
        app.buttons["Done"].tap()

        // People: friends, the invite link, what was said about your workouts.
        people.tap()
        XCTAssertTrue(app.staticTexts.labelled("Your friends · ").waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["Your invite link"].exists)
        XCTAssertTrue(app.staticTexts["On your sessions"].exists)
        shot("32-people")

        // Search by handle.
        let search = app.textFields["Search by handle"]
        search.tap()
        search.typeText("zz")
        XCTAssertTrue(app.staticTexts.labelled("No one with a handle starting").waitForExistence(timeout: 10))
        search.typeText(XCUIKeyboardKey.delete.rawValue + XCUIKeyboardKey.delete.rawValue + "sa")
        let sam = app.buttons["Sam Dev, @sam"]
        XCTAssertTrue(sam.firstMatch.waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts.labelled("No one with a handle starting").waitForNonExistence(timeout: 10))
        shot("33-people-search")

        // A friend's profile, then the two of you side by side.
        sam.firstMatch.tap()
        XCTAssertTrue(app.buttons["Compare with Sam Dev"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["Favourites"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["Recent sessions"].exists)
        shot("34-profile")
        app.buttons["Compare with Sam Dev"].tap()
        XCTAssertTrue(app.staticTexts["Lifts you both do"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["Sessions per week"].exists)
        shot("35-compare")
        app.buttons["All"].tap()
        XCTAssertTrue(app.staticTexts["Muscle split"].waitForExistence(timeout: 10))
        app.buttons["Back"].tap()
        XCTAssertTrue(app.buttons["Friends. Unfriend Sam Dev"].waitForExistence(timeout: 10))
        app.buttons["Back to Friends"].tap()
        XCTAssertTrue(app.staticTexts["Your invite link"].waitForExistence(timeout: 10))

        // Me: your own profile, edited.
        Thread.sleep(forTimeInterval: 0.8)  // the profile is still sliding away
        app.buttons["Me"].tap()
        XCTAssertTrue(app.buttons["Edit profile"].waitForExistence(timeout: 10))
        shot("36-me")
        XCTAssertTrue(app.staticTexts.labelled("@alex · ").waitForExistence(timeout: 10))
        app.buttons["Edit profile"].tap()
        let bio = app.textFields["Bio (optional)"]
        XCTAssertTrue(bio.waitForExistence(timeout: 10))
        Thread.sleep(forTimeInterval: 0.6)  // the sheet is still sliding up
        bio.coordinate(withNormalizedOffset: CGVector(dx: 0.98, dy: 0.5)).tap()
        bio.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: 40) + "Lifts before work\n")
        app.buttons["Save"].tap()
        XCTAssertTrue(app.staticTexts["Lifts before work"].waitForExistence(timeout: 10))
    }

    func testNewPersonJoinsByInvite() {
        launchAsAlex(app)

        // Alex's invite link, as a friend would be sent it.
        friendsTab.tap()
        people.tap()
        let link = app.staticTexts["Invite link"]
        XCTAssertTrue(link.waitForExistence(timeout: 10))
        let invite = link.value as? String ?? ""
        XCTAssertTrue(invite.contains("/invite/"), "No invite link on People: \(invite)")
        app.buttons["Me"].tap()
        app.buttons["Settings"].tap()
        app.tapClear(app.buttons["Sign out"])

        // Somebody new: Friends is profile setup until there is a profile.
        XCTAssertTrue(app.buttons["New person"].waitForExistence(timeout: 10))
        app.buttons["New person"].tap()
        XCTAssertTrue(app.staticTexts["Log your first workout"].waitForExistence(timeout: 10))
        friendsTab.tap()
        XCTAssertTrue(app.staticTexts["Set up your profile"].waitForExistence(timeout: 10))
        let handle = app.textFields["Handle"]
        XCTAssertTrue(handle.waitForExistence(timeout: 10))
        XCTAssertTrue((handle.value as? String ?? "").hasPrefix("riley_new"))
        shot("37-profile-setup")

        // A handle that won't do, then one that will.
        let wipe = String(repeating: XCUIKeyboardKey.delete.rawValue, count: 22)
        handle.coordinate(withNormalizedOffset: CGVector(dx: 0.98, dy: 0.5)).tap()
        handle.typeText(wipe + "ab\n")
        app.buttons["Create profile"].tap()
        XCTAssertTrue(app.staticTexts.labelled("lowercase letters, numbers and underscores").waitForExistence(timeout: 10))
        handle.coordinate(withNormalizedOffset: CGVector(dx: 0.98, dy: 0.5)).tap()
        handle.typeText(wipe + "riley\(Int.random(in: 100_000...999_999))\n")
        app.buttons["Create profile"].tap()
        XCTAssertTrue(app.staticTexts["Profile created. Find friends below."].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts.labelled("No friends yet").waitForExistence(timeout: 10))
        shot("38-people-empty")

        // The pasted link: whose it is, then friends in one tap.
        let paste = app.textFields["Invite link or code"]
        app.tapClear(paste)
        paste.typeText(invite + "\n")
        XCTAssertTrue(app.staticTexts["Alex Dev invited you"].waitForExistence(timeout: 10))
        shot("39-invite")
        app.buttons["Add Alex Dev"].tap()
        XCTAssertTrue(app.staticTexts["You and Alex Dev are now friends."].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["Your friends · 1"].waitForExistence(timeout: 10))

        // And Alex's workouts are in the feed.
        app.buttons["Activity"].tap()
        XCTAssertTrue(app.buttons["Give a high five"].firstMatch.waitForExistence(timeout: 10))
        shot("40-feed-new")
    }
}
