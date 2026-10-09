import XCTest

extension XCTestCase {
    /// Start signed out and come in as the seeded account "alex".
    func launchAsAlex(_ app: XCUIApplication) {
        app.launchArguments += ["-resetSignIn"]
        app.launch()
        XCTAssertTrue(app.buttons["Alex"].waitForExistence(timeout: 10))
        app.buttons["Alex"].tap()
        XCTAssertTrue(app.staticTexts["Friends"].waitForExistence(timeout: 10))
    }

    /// Attach a screenshot to the report, and write it to SHOTS_DIR when that is set.
    func shot(_ name: String) {
        Thread.sleep(forTimeInterval: 0.6)  // let a push or a fade finish
        let screenshot = XCUIScreen.main.screenshot()
        let attachment = XCTAttachment(screenshot: screenshot)
        let label = ProcessInfo.processInfo.environment["SHOTS_NAME"] ?? "light"
        attachment.name = "\(name)-\(label)"
        attachment.lifetime = .keepAlways
        add(attachment)
        if let dir = ProcessInfo.processInfo.environment["SHOTS_DIR"] {
            try? screenshot.pngRepresentation.write(
                to: URL(fileURLWithPath: dir).appendingPathComponent("\(name)-\(label).png")
            )
        }
    }
}

extension XCUIApplication {
    /// Tap something that may sit under the tab bar: bring it up the screen first.
    func tapClear(_ element: XCUIElement, file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertTrue(element.waitForExistence(timeout: 10), file: file, line: line)
        for _ in 0..<12 where element.frame.maxY > frame.height - 150 || element.frame.minY < 110 {
            let up = element.frame.maxY > frame.height - 150
            let from = coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
            from.press(forDuration: 0.05, thenDragTo: from.withOffset(CGVector(dx: 0, dy: up ? -260 : 260)))
        }
        element.tap()
    }
}

extension XCUIElementQuery {
    /// The first element whose label holds `text`.
    func labelled(_ text: String) -> XCUIElement {
        containing(NSPredicate(format: "label CONTAINS[c] %@", text)).firstMatch
    }
}
