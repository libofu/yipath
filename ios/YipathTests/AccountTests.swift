import StoreKitTest
import XCTest
@testable import Yipath

// MARK: - Helpers

private let profileJSON = #"{"birth_date":"2000-01-01","birth_hour":12,"birth_minute":0,"mbti":"ENFP"}"#
private func entitlementJSON(_ status: String, expires: String? = nil, product: String? = nil) -> Data {
    let e = expires.map { "\"\($0)\"" } ?? "null"
    let p = product.map { "\"\($0)\"" } ?? "null"
    return #"{"status":"\#(status)","trial_ends_at":"2026-10-10T05:12:33Z","expires_at":\#(e),"product_id":\#(p)}"#.data(using: .utf8)!
}
private let sessionAnon = #"{"user_id":1,"token":"anon","has_profile":true}"#.data(using: .utf8)!

/// Answers each request by (method, path) from a table; anything unlisted is a 404.
private func routes(_ table: [String: (Int, Data)]) -> (URLRequest) throws -> (Int, Data) {
    return { request in
        let key = "\(request.httpMethod ?? "GET") \(request.url?.path ?? "")"
        return table[key] ?? (404, Data())
    }
}

// MARK: - API client: the new calls

final class AccountAPITests: XCTestCase {
    override func tearDown() { StubURLProtocol.handler = nil }

    func testSignInSendsTokenAndNonce() async throws {
        StubURLProtocol.handler = routes(["POST /auth/apple": (200, #"{"user_id":7,"token":"t1","has_profile":false}"#.data(using: .utf8)!)])
        let session = try await makeClient().signInWithApple(identityToken: "apple.jwt.token", nonce: "raw-nonce")
        XCTAssertEqual(session, SessionInfo(token: "t1", hasProfile: false))
        let body = try JSONSerialization.jsonObject(with: StubURLProtocol.lastBody!) as! [String: Any]
        XCTAssertEqual(body["identity_token"] as? String, "apple.jwt.token")
        XCTAssertEqual(body["nonce"] as? String, "raw-nonce")
    }

    func testMissingProfileIsNilNotAnError() async throws {
        StubURLProtocol.handler = routes(["GET /profile": (404, Data())])
        let result = try await makeClient().profile(token: "t")
        XCTAssertNil(result)
        StubURLProtocol.handler = routes(["GET /profile": (200, profileJSON.data(using: .utf8)!)])
        let found = try await makeClient().profile(token: "t")
        XCTAssertEqual(found?.mbti, "ENFP")
    }

    func testDeleteAccountUsesDELETE() async throws {
        StubURLProtocol.handler = routes(["DELETE /account": (204, Data())])
        try await makeClient().deleteAccount(token: "t")
        XCTAssertEqual(StubURLProtocol.lastRequest?.httpMethod, "DELETE")
        XCTAssertEqual(StubURLProtocol.lastRequest?.value(forHTTPHeaderField: "Authorization"), "Bearer t")
    }

    func testVerifyTransactionPostsTheJWS() async throws {
        StubURLProtocol.handler = routes(["POST /subscription/verify": (200, entitlementJSON("subscribed", expires: "2026-11-07T00:00:00Z", product: "com.libofu.yipath.monthly"))])
        let e = try await makeClient().verifyTransaction("a.b.c", token: "t")
        XCTAssertEqual(e.status, .subscribed)
        XCTAssertEqual(e.productId, "com.libofu.yipath.monthly")
        XCTAssertNotNil(e.expiresAt)
        let body = try JSONSerialization.jsonObject(with: StubURLProtocol.lastBody!) as! [String: Any]
        XCTAssertEqual(body["signed_transaction"] as? String, "a.b.c")
    }

    func testStatusCodesMapToSpecificErrors() async {
        let cases: [(String, Int, Data, APIError)] = [
            ("GET /reading/today", 402, Data(), .paymentRequired),
            ("GET /reading/today", 409, #"{"detail":"profile required"}"#.data(using: .utf8)!, .conflict("profile required")),
            ("POST /subscription/verify", 400, #"{"detail":"x"}"#.data(using: .utf8)!, .invalidPurchase),
            ("POST /subscription/verify", 409, #"{"detail":"this subscription belongs to another account"}"#.data(using: .utf8)!,
             .conflict("this subscription belongs to another account")),
        ]
        for (route, status, body, expected) in cases {
            StubURLProtocol.handler = routes([route: (status, body)])
            do {
                if route.contains("verify") { _ = try await makeClient().verifyTransaction("x", token: "t") }
                else { _ = try await makeClient().reading(.today, on: Date(), token: "t") }
                XCTFail("expected \(expected)")
            } catch {
                XCTAssertEqual(error as? APIError, expected, route)
            }
        }
    }

    func testOtherBadRequestsAreNotMistakenForPurchaseProblems() async {
        StubURLProtocol.handler = routes(["GET /reading/today": (400, Data())])
        do {
            _ = try await makeClient().reading(.today, on: Date(), token: "t")
            XCTFail("expected an error")
        } catch {
            XCTAssertEqual(error as? APIError, .server(400))
        }
    }

    func testEntitlementDecodesWithAndWithoutFractionalSeconds() throws {
        for stamp in ["2026-10-10T05:12:33Z", "2026-10-10T05:12:33.123456Z", "2026-10-10T05:12:33+00:00"] {
            let json = #"{"status":"trial","trial_ends_at":"\#(stamp)","expires_at":null,"product_id":null}"#.data(using: .utf8)!
            let e = try JSONDecoder().decode(Entitlement.self, from: json)
            XCTAssertEqual(e.status, .trial, stamp)
            XCTAssertNil(e.expiresAt)
            XCTAssertEqual(e.trialEndsAt.timeIntervalSince1970, 1_791_609_153, accuracy: 1, stamp)
        }
        XCTAssertTrue(Entitlement(status: .trial, trialEndsAt: Date()).isActive)
        XCTAssertFalse(Entitlement(status: .expired, trialEndsAt: Date()).isActive)
    }

    func testNewErrorsAreFriendlyChinese() {
        for e in [APIError.paymentRequired, .invalidPurchase, .conflict("profile required"), .conflict("belongs to another account")] {
            XCTAssertTrue(e.errorDescription!.unicodeScalars.contains { $0.value > 0x4E00 })
        }
        XCTAssertTrue(APIError.conflict("this subscription belongs to another account").errorDescription!.contains("其他账号"))
    }
}

// MARK: - App state: sign-in, paywall, deletion

@MainActor
final class AccountStateTests: XCTestCase {
    override func setUp() { TokenStore.delete(); ProfileStore.delete() }
    override func tearDown() { StubURLProtocol.handler = nil; TokenStore.delete(); ProfileStore.delete() }

    func testSignInRestoresAnExistingProfile() async throws {
        StubURLProtocol.handler = routes([
            "POST /auth/apple": (200, #"{"user_id":1,"token":"t1","has_profile":true}"#.data(using: .utf8)!),
            "GET /profile": (200, profileJSON.data(using: .utf8)!),
            "GET /subscription": (200, entitlementJSON("trial")),
        ])
        let state = AppState(api: makeClient())
        XCTAssertEqual(state.stage, .signedOut)
        try await state.signIn(identityToken: "jwt", nonce: "n")
        XCTAssertEqual(state.stage, .ready)
        XCTAssertEqual(state.profile?.mbti, "ENFP")
        XCTAssertEqual(state.entitlement?.status, .trial)
        XCTAssertEqual(TokenStore.load(), "t1")
        XCTAssertEqual(ProfileStore.load()?.mbti, "ENFP")
    }

    func testAReinstallDoesNotInheritAnOldKeychainLogin() {
        // Simulate: the Keychain still holds a token, but UserDefaults was wiped with the app.
        UserDefaults.standard.removeObject(forKey: AppState.launchedBeforeKey)
        TokenStore.save("left-over-from-previous-install")
        let fresh = AppState(api: makeClient())
        XCTAssertEqual(fresh.stage, .signedOut)
        XCTAssertNil(TokenStore.load())
        // ...but on every later launch the login is kept
        TokenStore.save("real-login")
        ProfileStore.save(Profile(birthDate: day("2000-01-01")))
        XCTAssertEqual(AppState(api: makeClient()).stage, .ready)
    }

    func testALoginWithoutALocalProfileFetchesItFromTheServer() async throws {
        TokenStore.save("t")
        _ = AppState(api: makeClient())   // marks this install as launched before
        TokenStore.save("t")
        StubURLProtocol.handler = routes(["GET /profile": (200, profileJSON.data(using: .utf8)!), "GET /subscription": (200, entitlementJSON("trial"))])
        let state = AppState(api: makeClient())
        XCTAssertEqual(state.stage, .needsProfile)
        await state.restoreProfileIfPossible()
        XCTAssertEqual(state.stage, .ready)
        XCTAssertEqual(state.profile?.mbti, "ENFP")
    }

    func testRestoreStaysOnTheFormWhenTheServerHasNoProfileOrIsOffline() async throws {
        TokenStore.save("t")
        let state = AppState(api: makeClient())
        StubURLProtocol.handler = routes(["GET /profile": (404, Data())])
        await state.restoreProfileIfPossible()
        XCTAssertEqual(state.stage, .needsProfile)
        StubURLProtocol.handler = { _ in throw URLError(.notConnectedToInternet) }
        await state.restoreProfileIfPossible()
        XCTAssertEqual(state.stage, .needsProfile)
    }

    func testRestoreSignsOutAnExpiredLogin() async throws {
        TokenStore.save("t")
        let state = AppState(api: makeClient())
        StubURLProtocol.handler = routes(["GET /profile": (401, Data())])
        await state.restoreProfileIfPossible()
        XCTAssertEqual(state.stage, .signedOut)
        XCTAssertNil(TokenStore.load())
    }

    func testSignInWithANewAccountNeedsAProfileThenIsReady() async throws {
        StubURLProtocol.handler = routes([
            "POST /auth/apple": (200, #"{"user_id":2,"token":"t2","has_profile":false}"#.data(using: .utf8)!),
            "PUT /profile": (204, Data()),
            "GET /subscription": (200, entitlementJSON("trial")),
        ])
        let state = AppState(api: makeClient())
        try await state.signIn(identityToken: "jwt", nonce: "n")
        XCTAssertEqual(state.stage, .needsProfile)
        try await state.updateProfile(Profile(birthDate: day("1990-05-17"), mbti: "INFJ"))
        XCTAssertEqual(state.stage, .ready)
        // a relaunch picks up where it left off
        XCTAssertEqual(AppState(api: makeClient()).stage, .ready)
    }

    func testLoginWithoutProfileSurvivesARelaunch() async throws {
        StubURLProtocol.handler = routes([
            "POST /auth/apple": (200, #"{"user_id":2,"token":"t2","has_profile":false}"#.data(using: .utf8)!),
            "GET /subscription": (200, entitlementJSON("trial")),
        ])
        try await AppState(api: makeClient()).signIn(identityToken: "jwt", nonce: "n")
        XCTAssertEqual(AppState(api: makeClient()).stage, .needsProfile)
    }

    func testPaymentRequiredOpensThePaywall() async throws {
        StubURLProtocol.handler = routes([
            "POST /profile": (200, sessionAnon),
            "GET /reading/today": (402, Data()),
            "GET /subscription": (200, entitlementJSON("expired")),
        ])
        let state = AppState(api: makeClient())
        try await state.onboardAnonymously(Profile(birthDate: day("2000-01-01")))
        XCTAssertFalse(state.showPaywall)
        await state.load(.today)
        XCTAssertTrue(state.showPaywall)
        XCTAssertEqual(state.entitlement?.status, .expired)
        guard case .failed(let message) = state.readings[.today]! else { return XCTFail("expected failure") }
        XCTAssertEqual(message, APIError.paymentRequired.errorDescription)
    }

    func testAVerifiedPurchaseClosesThePaywallAndAllowsReloading() async throws {
        StubURLProtocol.handler = routes([
            "POST /profile": (200, sessionAnon),
            "GET /reading/today": (402, Data()),
            "GET /subscription": (200, entitlementJSON("expired")),
            "POST /subscription/verify": (200, entitlementJSON("subscribed", expires: "2026-11-07T00:00:00Z", product: "com.libofu.yipath.monthly")),
        ])
        let state = AppState(api: makeClient())
        try await state.onboardAnonymously(Profile(birthDate: day("2000-01-01")))
        await state.load(.today)
        XCTAssertTrue(state.showPaywall)

        try await state.submitTransaction("a.b.c")
        XCTAssertFalse(state.showPaywall)
        XCTAssertEqual(state.entitlement?.status, .subscribed)
        guard case .idle = state.readings[.today]! else { return XCTFail("the failed reading should be reset so it reloads") }
    }

    func testARejectedPurchaseKeepsThePaywallOpen() async throws {
        StubURLProtocol.handler = routes([
            "POST /profile": (200, sessionAnon),
            "GET /subscription": (200, entitlementJSON("expired")),
            "POST /subscription/verify": (400, #"{"detail":"signature check failed"}"#.data(using: .utf8)!),
        ])
        let state = AppState(api: makeClient())
        try await state.onboardAnonymously(Profile(birthDate: day("2000-01-01")))
        state.showPaywall = true
        do { try await state.submitTransaction("forged"); XCTFail("expected an error") }
        catch { XCTAssertEqual(error as? APIError, .invalidPurchase) }
        XCTAssertTrue(state.showPaywall)
        XCTAssertEqual(state.entitlement?.status, .expired)
    }

    func testDeleteAccountErasesServerSideThenClearsTheDevice() async throws {
        var deleteCalled = false
        StubURLProtocol.handler = { request in
            if request.httpMethod == "DELETE" { deleteCalled = true; return (204, Data()) }
            if request.httpMethod == "POST" { return (200, sessionAnon) }
            return (200, entitlementJSON("trial"))
        }
        let state = AppState(api: makeClient())
        try await state.onboardAnonymously(Profile(birthDate: day("2000-01-01")))
        try await state.deleteAccount()
        XCTAssertTrue(deleteCalled)
        XCTAssertEqual(state.stage, .signedOut)
        XCTAssertNil(TokenStore.load())
        XCTAssertNil(ProfileStore.load())
        XCTAssertNil(state.entitlement)
    }

    func testDeleteAccountStillClearsTheDeviceIfTheServerAlreadyForgotUs() async throws {
        StubURLProtocol.handler = { request in
            if request.httpMethod == "DELETE" { return (401, Data()) }
            if request.httpMethod == "POST" { return (200, sessionAnon) }
            return (200, entitlementJSON("trial"))
        }
        let state = AppState(api: makeClient())
        try await state.onboardAnonymously(Profile(birthDate: day("2000-01-01")))
        try await state.deleteAccount()
        XCTAssertEqual(state.stage, .signedOut)
    }

    func testDeleteAccountKeepsTheLoginIfTheServerIsUnreachable() async throws {
        StubURLProtocol.handler = { request in
            if request.httpMethod == "DELETE" { throw URLError(.notConnectedToInternet) }
            if request.httpMethod == "POST" { return (200, sessionAnon) }
            return (200, entitlementJSON("trial"))
        }
        let state = AppState(api: makeClient())
        try await state.onboardAnonymously(Profile(birthDate: day("2000-01-01")))
        do { try await state.deleteAccount(); XCTFail("should report the failure") }
        catch { XCTAssertEqual(error as? APIError, .network) }
        XCTAssertEqual(state.stage, .ready, "the account still exists, so don't pretend it was deleted")
    }
}

// MARK: - Sign in helpers

final class SignInHelperTests: XCTestCase {
    func testNonceIsRandomLongEnoughAndUsesSafeCharacters() {
        let a = SignInView.randomNonce(), b = SignInView.randomNonce()
        XCTAssertEqual(a.count, 32)
        XCTAssertNotEqual(a, b)
        XCTAssertTrue(a.allSatisfy { $0.isLetter || $0.isNumber || "-._".contains($0) })
    }

    func testSHA256MatchesTheKnownVector() {
        // SHA-256("abc"), the standard test vector; the server compares against the same hex digest
        XCTAssertEqual(SignInView.sha256Hex("abc"), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
    }
}

// MARK: - StoreKit: a real purchase against the local test configuration

@MainActor
final class SubscriptionManagerTests: XCTestCase {
    override func setUp() { TokenStore.delete(); ProfileStore.delete() }
    override func tearDown() { StubURLProtocol.handler = nil; TokenStore.delete(); ProfileStore.delete() }

    private func session() throws -> SKTestSession {
        let s = try SKTestSession(configurationFileNamed: "Yipath")
        s.resetToDefaultState()
        s.disableDialogs = true       // buy without showing Apple's payment sheet
        s.clearTransactions()
        return s
    }

    func testBothProductsLoadWithPrices() async throws {
        _ = try session()
        let manager = SubscriptionManager(appState: AppState(api: makeClient()))
        await manager.loadProducts()
        XCTAssertEqual(manager.products.map(\.id), SubscriptionManager.productIDs)
        XCTAssertTrue(manager.products[0].displayPrice.contains("18"))
        XCTAssertTrue(manager.products[1].displayPrice.contains("128"))
        XCTAssertNil(manager.message)
    }

    func testAPurchaseIsPassedToTheServerAsASignedTransaction() async throws {
        let store = try session()
        var verifyBodies: [Data] = []
        StubURLProtocol.handler = { request in
            switch (request.httpMethod ?? "", request.url?.path ?? "") {
            case ("POST", "/profile"): return (200, sessionAnon)
            case ("POST", "/subscription/verify"):
                verifyBodies.append(StubURLProtocol.lastBody ?? Data())
                return (200, entitlementJSON("subscribed", expires: "2026-11-07T00:00:00Z", product: "com.libofu.yipath.monthly"))
            default: return (200, entitlementJSON("expired"))
            }
        }
        let state = AppState(api: makeClient())
        try await state.onboardAnonymously(Profile(birthDate: day("2000-01-01")))
        let manager = SubscriptionManager(appState: state)

        try await store.buyProduct(identifier: "com.libofu.yipath.monthly")
        await manager.syncCurrentEntitlements()

        XCTAssertEqual(verifyBodies.count, 1)
        let body = try JSONSerialization.jsonObject(with: verifyBodies[0]) as! [String: Any]
        let jws = try XCTUnwrap(body["signed_transaction"] as? String)
        let parts = jws.split(separator: ".")
        XCTAssertEqual(parts.count, 3, "a JWS is header.payload.signature")

        // decode the payload the way the server will, and check it says what we bought
        var b64 = String(parts[1]).replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        while b64.count % 4 != 0 { b64 += "=" }
        let payload = try JSONSerialization.jsonObject(with: Data(base64Encoded: b64)!) as! [String: Any]
        XCTAssertEqual(payload["productId"] as? String, "com.libofu.yipath.monthly")
        XCTAssertEqual(payload["environment"] as? String, "Xcode")
        XCTAssertEqual(payload["bundleId"] as? String, Bundle.main.bundleIdentifier)
        print("JWSDUMP:\(jws)")   // used once to capture a real StoreKit transaction as a backend test fixture

        XCTAssertEqual(state.entitlement?.status, .subscribed)
    }

    func testNothingIsSentWhenThereIsNoPurchase() async throws {
        _ = try session()
        var verifyCalls = 0
        StubURLProtocol.handler = { request in
            if request.url?.path == "/subscription/verify" { verifyCalls += 1 }
            return request.httpMethod == "POST" ? (200, sessionAnon) : (200, entitlementJSON("expired"))
        }
        let state = AppState(api: makeClient())
        try await state.onboardAnonymously(Profile(birthDate: day("2000-01-01")))
        await SubscriptionManager(appState: state).syncCurrentEntitlements()
        XCTAssertEqual(verifyCalls, 0)
    }
}
