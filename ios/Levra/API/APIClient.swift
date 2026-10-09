import Foundation

/// The server's error shape, {"error": {"code", "message"}}, or a stand-in for a
/// request that never got an answer. `message` is written for the user.
struct APIError: LocalizedError, Equatable {
    let status: Int
    let code: String
    let message: String

    var errorDescription: String? { message }
    /// The sign-in is missing, expired or no longer valid: back to Welcome.
    var isSignedOut: Bool { status == 401 }
    /// Friends, the feed and the rest need a profile first.
    var needsProfile: Bool { code == "profile_required" }

    static let offline = APIError(
        status: 0, code: "offline", message: "Couldn't reach Levra. Check your connection and try again."
    )
    static let unreadable = APIError(
        status: 0, code: "unreadable", message: "Something went wrong. Please try again."
    )
}

/// Talks to /api/v1. Adds the bearer token and `today=` (the user's local date:
/// the server never guesses it) to every request.
final class APIClient {
    /// The simulator in a Debug build talks to the Mac's local Flask; everything
    /// else talks to the live site. LEVRA_BASE_URL in the scheme's environment
    /// overrides both.
    static let defaultBaseURL: URL = {
        if let override = ProcessInfo.processInfo.environment["LEVRA_BASE_URL"],
           let url = URL(string: override) {
            return url
        }
        #if DEBUG && targetEnvironment(simulator)
        return URL(string: "http://localhost:5001")!
        #else
        return URL(string: "https://levraapp.com")!
        #endif
    }()

    let baseURL: URL
    var token: String?
    private let session: URLSession

    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    private let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        return e
    }()

    init(baseURL: URL = APIClient.defaultBaseURL, token: String? = nil) {
        self.baseURL = baseURL
        self.token = token
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 45  // reading a log can take a while
        config.httpCookieStorage = nil  // the API never takes the cookie session
        config.httpShouldSetCookies = false
        session = URLSession(configuration: config)
    }

    func get<T: Decodable>(_ path: String, query: [String: String] = [:]) async throws -> T {
        try await send("GET", path, query: query, body: nil)
    }

    func post<T: Decodable>(_ path: String, _ body: some Encodable) async throws -> T {
        try await send("POST", path, body: try encoder.encode(body))
    }

    func put<T: Decodable>(_ path: String, _ body: some Encodable) async throws -> T {
        try await send("PUT", path, body: try encoder.encode(body))
    }

    /// A POST with nothing to say: a high five, a friend request.
    func post<T: Decodable>(_ path: String) async throws -> T {
        try await send("POST", path, body: Data("{}".utf8))
    }

    func delete<T: Decodable>(_ path: String) async throws -> T {
        try await send("DELETE", path, body: nil)
    }

    private func send<T: Decodable>(
        _ method: String, _ path: String, query: [String: String] = [:], body: Data?
    ) async throws -> T {
        var components = URLComponents(
            url: baseURL.appendingPathComponent("api/v1" + path), resolvingAgainstBaseURL: false
        )!
        var items = [URLQueryItem(name: "today", value: Days.today())]
        items += query.sorted { $0.key < $1.key }.map { URLQueryItem(name: $0.key, value: $0.value) }
        components.queryItems = items

        var request = URLRequest(url: components.url!)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let token {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        if let body {
            request.httpBody = body
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch is CancellationError {
            throw CancellationError()
        } catch let error as URLError where error.code == .cancelled {
            throw CancellationError()
        } catch {
            throw APIError.offline
        }
        guard let http = response as? HTTPURLResponse else { throw APIError.unreadable }
        guard (200..<300).contains(http.statusCode) else {
            if let envelope = try? decoder.decode(ErrorEnvelope.self, from: data) {
                throw APIError(
                    status: http.statusCode, code: envelope.error.code, message: envelope.error.message
                )
            }
            throw APIError(
                status: http.statusCode, code: "server_error", message: APIError.unreadable.message
            )
        }
        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            #if DEBUG
            print("Could not decode \(T.self) from \(method) \(path): \(error)")
            #endif
            throw APIError.unreadable
        }
    }

    private struct ErrorEnvelope: Decodable {
        struct Body: Decodable {
            let code: String
            let message: String
        }

        let error: Body
    }
}
