import XCTest
@testable import Yipath

// MARK: - Test helpers

/// Replaces the network: every request URLSession makes is answered by `handler`.
final class StubURLProtocol: URLProtocol {
    nonisolated(unsafe) static var handler: ((URLRequest) throws -> (Int, Data))?
    nonisolated(unsafe) static var lastRequest: URLRequest?
    nonisolated(unsafe) static var lastBody: Data?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        Self.lastRequest = request
        Self.lastBody = request.httpBody ?? request.httpBodyStream.map(Self.readAll)
        do {
            guard let handler = Self.handler else { throw URLError(.badServerResponse) }
            let (status, data) = try handler(request)
            let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }
    override func stopLoading() {}

    private static func readAll(_ stream: InputStream) -> Data {
        stream.open(); defer { stream.close() }
        var data = Data()
        let buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: 4096)
        defer { buffer.deallocate() }
        while stream.hasBytesAvailable {
            let n = stream.read(buffer, maxLength: 4096)
            if n <= 0 { break }
            data.append(buffer, count: n)
        }
        return data
    }
}

func makeClient() -> APIClient {
    let config = URLSessionConfiguration.ephemeral
    config.protocolClasses = [StubURLProtocol.self]
    return APIClient(baseURL: URL(string: "http://test.local")!, session: URLSession(configuration: config))
}

func day(_ text: String) -> Date { DayFormat.formatter.date(from: text)! }

let readingJSON = """
{"theme":"春风化雨",
 "work":{"action":"午前找一位同伴对齐分工","reason":"食神之日，借人手共养一事"},
 "life":{"action":"午后煮一壶茶","reason":"食神主表达与创作"},
 "avoid":{"action":"晨起只开一件新事","reason":"多线并起，易打乱节奏"}}
""".data(using: .utf8)!

// MARK: - Models

final class ModelTests: XCTestCase {
    func testProfileEncodesTheBackendFormat() throws {
        let profile = Profile(birthDate: day("2000-01-01"), birthHour: nil, mbti: "INFJ")
        let json = try JSONSerialization.jsonObject(with: JSONEncoder().encode(profile)) as! [String: Any]
        XCTAssertEqual(json["birth_date"] as? String, "2000-01-01")
        XCTAssertTrue(json["birth_hour"] is NSNull, "unknown birth time must be sent as null")
        XCTAssertEqual(json["birth_minute"] as? Int, 0)
        XCTAssertEqual(json["mbti"] as? String, "INFJ")
    }

    func testProfileRoundTrips() throws {
        let profile = Profile(birthDate: day("1990-05-17"), birthHour: 14, birthMinute: 30, mbti: nil)
        let decoded = try JSONDecoder().decode(Profile.self, from: JSONEncoder().encode(profile))
        XCTAssertEqual(decoded, profile)
    }

    func testProfileRejectsABadDate() {
        let bad = #"{"birth_date":"not-a-date","birth_hour":null,"birth_minute":0,"mbti":null}"#.data(using: .utf8)!
        XCTAssertThrowsError(try JSONDecoder().decode(Profile.self, from: bad))
    }

    func testReadingDecodesTheBackendSample() throws {
        let r = try JSONDecoder().decode(Reading.self, from: readingJSON)
        XCTAssertEqual(r.theme, "春风化雨")
        XCTAssertEqual(r.work.action, "午前找一位同伴对齐分工")
        XCTAssertEqual(r.avoid.reason, "多线并起，易打乱节奏")
    }

    func testAllSixteenMBTITypes() {
        XCTAssertEqual(Set(allMBTITypes).count, 16)
    }

    func testDraftConvertsToProfile() {
        var draft = ProfileDraft()
        draft.birthDate = day("2000-01-01")
        draft.mbti = ""
        draft.knowsBirthTime = false
        XCTAssertNil(draft.toProfile().birthHour)
        XCTAssertNil(draft.toProfile().mbti)

        draft.knowsBirthTime = true
        draft.mbti = "ENFP"
        let p = draft.toProfile()
        XCTAssertEqual(p.birthHour, 12)   // the draft starts at noon
        XCTAssertEqual(p.mbti, "ENFP")
    }
}

// MARK: - API client

final class APIClientTests: XCTestCase {
    override func tearDown() { StubURLProtocol.handler = nil }

    func testCreateProfilePostsJSONAndReturnsToken() async throws {
        StubURLProtocol.handler = { _ in (200, #"{"user_id":1,"token":"abc"}"#.data(using: .utf8)!) }
        let token = try await makeClient().createProfile(Profile(birthDate: day("2000-01-01"), mbti: "INFJ"))
        XCTAssertEqual(token, "abc")
        XCTAssertEqual(StubURLProtocol.lastRequest?.httpMethod, "POST")
        XCTAssertEqual(StubURLProtocol.lastRequest?.url?.path, "/profile")
        let body = try JSONSerialization.jsonObject(with: StubURLProtocol.lastBody!) as! [String: Any]
        XCTAssertEqual(body["birth_date"] as? String, "2000-01-01")
    }

    func testReadingSendsTokenAndDate() async throws {
        StubURLProtocol.handler = { _ in (200, readingJSON) }
        let r = try await makeClient().reading(.week, on: day("2026-10-07"), token: "tok")
        XCTAssertEqual(r.theme, "春风化雨")
        let request = StubURLProtocol.lastRequest!
        XCTAssertEqual(request.url?.path, "/reading/week")
        XCTAssertEqual(request.url?.query, "date=2026-10-07")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer tok")
    }

    func testUpdateProfileUsesPUT() async throws {
        StubURLProtocol.handler = { _ in (204, Data()) }
        try await makeClient().updateProfile(Profile(birthDate: day("2000-01-01")), token: "tok")
        XCTAssertEqual(StubURLProtocol.lastRequest?.httpMethod, "PUT")
    }

    func testHTTPErrorsMapToFriendlyErrors() async {
        let cases: [(Int, APIError)] = [(401, .unauthorized), (502, .serverBusy), (500, .server(500)), (422, .server(422))]
        for (status, expected) in cases {
            StubURLProtocol.handler = { _ in (status, Data()) }
            do {
                _ = try await makeClient().reading(.today, on: Date(), token: "t")
                XCTFail("expected an error for \(status)")
            } catch {
                XCTAssertEqual(error as? APIError, expected, "status \(status)")
            }
        }
    }

    func testUnreachableServerIsANetworkError() async {
        StubURLProtocol.handler = { _ in throw URLError(.cannotConnectToHost) }
        do {
            _ = try await makeClient().reading(.today, on: Date(), token: "t")
            XCTFail("expected an error")
        } catch {
            XCTAssertEqual(error as? APIError, .network)
        }
    }

    func testGarbageBodyIsABadResponse() async {
        StubURLProtocol.handler = { _ in (200, "not json".data(using: .utf8)!) }
        do {
            _ = try await makeClient().reading(.today, on: Date(), token: "t")
            XCTFail("expected an error")
        } catch {
            XCTAssertEqual(error as? APIError, .badResponse)
        }
    }

    func testErrorMessagesAreInChinese() {
        for e in [APIError.unauthorized, .serverBusy, .server(500), .network, .badResponse] {
            XCTAssertNotNil(e.errorDescription)
            XCTAssertTrue(e.errorDescription!.unicodeScalars.contains { $0.value > 0x4E00 })
        }
    }
}

// MARK: - App state

@MainActor
final class AppStateTests: XCTestCase {
    override func setUp() {
        TokenStore.delete()
        ProfileStore.delete()
    }
    override func tearDown() {
        StubURLProtocol.handler = nil
        TokenStore.delete()
        ProfileStore.delete()
    }

    func testOnboardingStoresTokenAndProfile() async throws {
        StubURLProtocol.handler = { _ in (200, #"{"user_id":1,"token":"abc"}"#.data(using: .utf8)!) }
        let state = AppState(api: makeClient())
        XCTAssertFalse(state.isOnboarded)
        try await state.onboard(Profile(birthDate: day("2000-01-01")))
        XCTAssertTrue(state.isOnboarded)
        XCTAssertEqual(TokenStore.load(), "abc")
        XCTAssertEqual(ProfileStore.load()?.birthDate, day("2000-01-01"))
        // a relaunch picks the same session up again
        XCTAssertTrue(AppState(api: makeClient()).isOnboarded)
    }

    func testLoadFillsReadingAndCachesForTheDay() async throws {
        StubURLProtocol.handler = { request in
            request.url?.path == "/profile" ? (200, #"{"user_id":1,"token":"abc"}"#.data(using: .utf8)!) : (200, readingJSON)
        }
        let state = AppState(api: makeClient())
        try await state.onboard(Profile(birthDate: day("2000-01-01")))
        await state.load(.today)
        guard case .loaded(let r) = state.readings[.today]! else { return XCTFail("not loaded") }
        XCTAssertEqual(r.theme, "春风化雨")

        var calls = 0
        StubURLProtocol.handler = { _ in calls += 1; return (200, readingJSON) }
        await state.load(.today)                       // already have today's: no new request
        XCTAssertEqual(calls, 0)
        await state.load(.today, force: true)          // pull to refresh: asks again
        XCTAssertEqual(calls, 1)
    }

    func testFailureShowsMessageAndRetrySucceeds() async throws {
        StubURLProtocol.handler = { _ in (200, #"{"user_id":1,"token":"abc"}"#.data(using: .utf8)!) }
        let state = AppState(api: makeClient())
        try await state.onboard(Profile(birthDate: day("2000-01-01")))

        StubURLProtocol.handler = { _ in (502, Data()) }
        await state.load(.today)
        guard case .failed(let message) = state.readings[.today]! else { return XCTFail("expected failure") }
        XCTAssertEqual(message, APIError.serverBusy.errorDescription)

        StubURLProtocol.handler = { _ in (200, readingJSON) }
        await state.load(.today, force: true)
        guard case .loaded = state.readings[.today]! else { return XCTFail("retry should load") }
    }

    func testExpiredTokenSignsTheUserOut() async throws {
        StubURLProtocol.handler = { _ in (200, #"{"user_id":1,"token":"abc"}"#.data(using: .utf8)!) }
        let state = AppState(api: makeClient())
        try await state.onboard(Profile(birthDate: day("2000-01-01")))

        StubURLProtocol.handler = { _ in (401, Data()) }
        await state.load(.today)
        XCTAssertFalse(state.isOnboarded)
        XCTAssertNil(TokenStore.load())
        XCTAssertEqual(state.notice, APIError.unauthorized.errorDescription)
    }

    func testProfileUpdateClearsOldReadings() async throws {
        StubURLProtocol.handler = { request in
            switch (request.httpMethod, request.url?.path) {
            case ("POST", "/profile"): return (200, #"{"user_id":1,"token":"abc"}"#.data(using: .utf8)!)
            case ("PUT", "/profile"): return (204, Data())
            default: return (200, readingJSON)
            }
        }
        let state = AppState(api: makeClient())
        try await state.onboard(Profile(birthDate: day("2000-01-01")))
        await state.load(.today)
        try await state.updateProfile(Profile(birthDate: day("1990-05-17"), mbti: "ENFP"))
        guard case .idle = state.readings[.today]! else { return XCTFail("old reading should be cleared") }
        XCTAssertEqual(state.profile?.mbti, "ENFP")
    }

    func testSignOutClearsEverything() async throws {
        StubURLProtocol.handler = { _ in (200, #"{"user_id":1,"token":"abc"}"#.data(using: .utf8)!) }
        let state = AppState(api: makeClient())
        try await state.onboard(Profile(birthDate: day("2000-01-01")))
        state.signOut()
        XCTAssertFalse(state.isOnboarded)
        XCTAssertNil(TokenStore.load())
        XCTAssertNil(ProfileStore.load())
    }
}
