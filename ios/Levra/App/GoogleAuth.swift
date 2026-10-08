import GoogleSignIn
import UIKit

/// Google Sign-In, the app's only third-party code. It hands back an ID token,
/// which POST /auth/google swaps for Levra's own token.
@MainActor
enum GoogleAuth {
    /// The iOS OAuth client ID (GIDClientID in Info.plist, from GOOGLE_IOS_CLIENT_ID
    /// in project.yml), or nil until the owner has created one.
    static var clientID: String? {
        let value = Bundle.main.object(forInfoDictionaryKey: "GIDClientID") as? String
        return value.flatMap { $0.isEmpty ? nil : $0 }
    }

    /// Nil if the user backed out of the Google sheet.
    static func idToken() async throws -> String? {
        guard let clientID else {
            throw APIError(status: 503, code: "not_configured", message: "Google sign-in isn't set up yet.")
        }
        let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
        guard var presenter = scenes.compactMap(\.keyWindow).first?.rootViewController else {
            throw APIError.unreadable
        }
        while let next = presenter.presentedViewController { presenter = next }

        GIDSignIn.sharedInstance.configuration = GIDConfiguration(clientID: clientID)
        do {
            let result = try await GIDSignIn.sharedInstance.signIn(withPresenting: presenter)
            guard let token = result.user.idToken?.tokenString else { throw APIError.unreadable }
            return token
        } catch let error as GIDSignInError where error.code == .canceled {
            return nil
        }
    }

    static func handle(_ url: URL) {
        _ = GIDSignIn.sharedInstance.handle(url)
    }

    static func signOut() {
        GIDSignIn.sharedInstance.signOut()
    }
}
