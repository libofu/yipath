import Foundation

/// Everything that can go wrong when talking to the backend, with a message
/// that is safe to show to the user (in Chinese).
enum APIError: LocalizedError, Equatable {
    case unauthorized                 // 401: the token is no longer valid
    case serverBusy                   // 502: the model could not produce a reading
    case server(Int)                  // any other HTTP error
    case network                      // could not reach the server at all
    case badResponse                  // reply was not the JSON we expected

    var errorDescription: String? {
        switch self {
        case .unauthorized: return "登录已失效，请重新起盘。"
        case .serverBusy: return "先生一时没能排好，请稍后再试。"
        case .server(let code): return "服务暂时不可用（\(code)），请稍后再试。"
        case .network: return "无法连接服务，请检查网络，或确认后端已启动。"
        case .badResponse: return "收到的内容无法解读，请稍后再试。"
        }
    }
}

/// A small wrapper around URLSession for the four backend calls we need.
/// `async throws` means: "call me with `try await`; I may take a while and may fail".
struct APIClient {
    var baseURL: URL
    var session: URLSession = .shared

    /// The URL from Info.plist (set by YIPATH_API_BASE_URL in project.yml).
    static func fromBundle(_ bundle: Bundle = .main) -> APIClient {
        let text = bundle.object(forInfoDictionaryKey: "YipathAPIBaseURL") as? String ?? "http://127.0.0.1:8000"
        return APIClient(baseURL: URL(string: text) ?? URL(string: "http://127.0.0.1:8000")!)
    }

    // MARK: Calls

    /// Creates the account and returns the access token.
    func createProfile(_ profile: Profile) async throws -> String {
        struct Created: Decodable { let token: String }
        let request = try makeRequest("profile", method: "POST", body: profile)
        let created: Created = try await send(request)
        return created.token
    }

    func updateProfile(_ profile: Profile, token: String) async throws {
        let request = try makeRequest("profile", method: "PUT", body: profile, token: token)
        _ = try await sendRaw(request)
    }

    /// `day` is the device's current day; the server uses it to pick the day or week.
    func reading(_ period: Period, on day: Date, token: String) async throws -> Reading {
        let query = [URLQueryItem(name: "date", value: DayFormat.formatter.string(from: day))]
        // A first reading can take several seconds while the model writes it.
        let request = try makeRequest("reading/\(period.rawValue)", method: "GET", query: query, token: token, timeout: 90)
        return try await send(request)
    }

    // MARK: Plumbing

    private func makeRequest(
        _ path: String,
        method: String,
        body: Encodable? = nil,
        query: [URLQueryItem] = [],
        token: String? = nil,
        timeout: TimeInterval = 30
    ) throws -> URLRequest {
        var components = URLComponents(url: baseURL.appendingPathComponent(path), resolvingAgainstBaseURL: false)!
        if !query.isEmpty { components.queryItems = query }
        var request = URLRequest(url: components.url!, timeoutInterval: timeout)
        request.httpMethod = method
        if let token { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(AnyEncodable(body))
        }
        return request
    }

    private func send<T: Decodable>(_ request: URLRequest) async throws -> T {
        let data = try await sendRaw(request)
        do {
            return try JSONDecoder().decode(T.self, from: data)
        } catch {
            throw APIError.badResponse
        }
    }

    /// Performs the request and turns HTTP failures into `APIError`s.
    private func sendRaw(_ request: URLRequest) async throws -> Data {
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw APIError.network
        }
        guard let http = response as? HTTPURLResponse else { throw APIError.badResponse }
        switch http.statusCode {
        case 200..<300: return data
        case 401: throw APIError.unauthorized
        case 502: throw APIError.serverBusy
        default: throw APIError.server(http.statusCode)
        }
    }
}

/// Lets us pass "any Encodable value" around as one type.
private struct AnyEncodable: Encodable {
    private let encodeValue: (Encoder) throws -> Void
    init(_ value: Encodable) { encodeValue = value.encode }
    func encode(to encoder: Encoder) throws { try encodeValue(encoder) }
}
