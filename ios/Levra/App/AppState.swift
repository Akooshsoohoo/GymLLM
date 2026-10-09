import Foundation
import Observation

/// Who is signed in, and the one API client everything shares.
@MainActor
@Observable
final class AppState {
    enum Phase { case launching, signedOut, signedIn }

    private(set) var phase: Phase = .launching
    private(set) var me: Me?
    let api = APIClient()
    /// Goes up whenever a workout or a rest day changes, so screens already on
    /// show load again.
    private(set) var changes = 0

    func didChange() { changes += 1 }

    var firstName: String { me?.firstName ?? "" }
    var weightUnit: String { me?.weightUnit ?? "lbs" }

    /// Picks up a saved sign-in, if there is one.
    func start() async {
        guard phase == .launching else { return }
        #if DEBUG
        // The UI tests start signed out however the last run ended.
        if ProcessInfo.processInfo.arguments.contains("-resetSignIn") { TokenStore.clear() }
        #endif
        guard let token = TokenStore.load() else {
            phase = .signedOut
            return
        }
        api.token = token
        phase = .signedIn
        await refreshMe()
    }

    func refreshMe() async {
        do {
            me = try await api.get("/me")
        } catch {
            _ = message(for: error)  // signs out if the token is no good; else keep what we have
        }
    }

    func signIn(devAccount slug: String) async throws {
        finishSignIn(try await api.post("/auth/dev", DevSignIn(slug: slug)))
    }

    func signIn(googleIDToken token: String) async throws {
        finishSignIn(try await api.post("/auth/google", GoogleSignInRequest(idToken: token)))
    }

    private func finishSignIn(_ auth: AuthResponse) {
        TokenStore.save(auth.token)
        api.token = auth.token
        me = auth.user
        phase = .signedIn
    }

    func signOut() {
        TokenStore.clear()
        GoogleAuth.signOut()
        api.token = nil
        me = nil
        phase = .signedOut
    }

    func setWeightUnit(_ unit: String) async throws {
        let saved: Preferences = try await api.put("/preferences", PreferencesRequest(weightUnit: unit))
        me?.weightUnit = saved.weightUnit
    }

    /// Your profile was just made or changed.
    func setProfile(_ profile: OwnProfile) {
        me?.profile = profile
        didChange()
    }

    /// What to tell the user about a failed request, or nil when there is nothing
    /// to say: the task was cancelled, or the sign-in ran out and they are back on
    /// Welcome.
    func message(for error: Error) -> String? {
        if error is CancellationError { return nil }
        guard let api = error as? APIError else { return APIError.unreadable.message }
        if api.isSignedOut, phase == .signedIn {
            signOut()
            return nil
        }
        // The server says there is no profile: ask again who we are, and the Friends
        // screens turn into profile setup.
        if api.needsProfile {
            Task { await refreshMe() }
            return nil
        }
        return api.message
    }
}
