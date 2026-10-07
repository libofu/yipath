import Foundation

/// The three things the backend is asked for. `rawValue` is the URL path component.
enum Period: String, CaseIterable {
    case today
    case week

    var title: String { self == .today ? "今日" : "本周" }
}

/// One card: what to do (`action`) and why (`reason`).
struct Card: Codable, Equatable {
    let action: String
    let reason: String
}

/// The backend's answer for a day or a week. Field names match the JSON exactly,
/// so Swift's automatic Codable support needs no extra code here.
struct Reading: Codable, Equatable {
    let theme: String
    let work: Card   // 宜·事业
    let life: Card   // 宜·起居
    let avoid: Card  // 忌
}

/// What the user tells us at onboarding. Sent to the backend as JSON.
struct Profile: Codable, Equatable {
    var birthDate: Date
    var birthHour: Int?      // nil = birth time unknown
    var birthMinute: Int = 0
    var mbti: String?        // nil = not provided, otherwise like "INFJ"

    // The backend uses snake_case names; this maps them to Swift's camelCase.
    enum CodingKeys: String, CodingKey {
        case birthDate = "birth_date"
        case birthHour = "birth_hour"
        case birthMinute = "birth_minute"
        case mbti
    }

    init(birthDate: Date, birthHour: Int? = nil, birthMinute: Int = 0, mbti: String? = nil) {
        self.birthDate = birthDate
        self.birthHour = birthHour
        self.birthMinute = birthMinute
        self.mbti = mbti
    }

    // The backend wants the birth date as a plain "yyyy-MM-dd" string, so we
    // convert by hand instead of using Date's default encoding.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let text = try c.decode(String.self, forKey: .birthDate)
        guard let date = DayFormat.formatter.date(from: text) else {
            throw DecodingError.dataCorruptedError(forKey: .birthDate, in: c, debugDescription: "bad date: \(text)")
        }
        birthDate = date
        birthHour = try c.decodeIfPresent(Int.self, forKey: .birthHour)
        birthMinute = try c.decodeIfPresent(Int.self, forKey: .birthMinute) ?? 0
        mbti = try c.decodeIfPresent(String.self, forKey: .mbti)
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(DayFormat.formatter.string(from: birthDate), forKey: .birthDate)
        try c.encode(birthHour, forKey: .birthHour)   // nil is sent as JSON null
        try c.encode(birthMinute, forKey: .birthMinute)
        try c.encode(mbti, forKey: .mbti)
    }
}

/// What the server says about the user's access: free trial, subscribed, or expired.
struct Entitlement: Codable, Equatable {
    enum Status: String, Codable { case trial, subscribed, expired }

    let status: Status
    let trialEndsAt: Date
    let expiresAt: Date?     // when the subscription lapses; nil if never subscribed
    let productId: String?

    var isActive: Bool { status != .expired }

    enum CodingKeys: String, CodingKey {
        case status
        case trialEndsAt = "trial_ends_at"
        case expiresAt = "expires_at"
        case productId = "product_id"
    }

    init(status: Status, trialEndsAt: Date, expiresAt: Date? = nil, productId: String? = nil) {
        self.status = status
        self.trialEndsAt = trialEndsAt
        self.expiresAt = expiresAt
        self.productId = productId
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        status = try c.decode(Status.self, forKey: .status)
        trialEndsAt = try Self.date(c, .trialEndsAt)
        if c.contains(.expiresAt), try !c.decodeNil(forKey: .expiresAt) {
            expiresAt = try Self.date(c, .expiresAt)
        } else {
            expiresAt = nil
        }
        productId = try c.decodeIfPresent(String.self, forKey: .productId)
    }

    /// The server sends ISO 8601 ("2026-10-07T16:30:11Z"), with or without fractional seconds.
    private static func date(_ c: KeyedDecodingContainer<CodingKeys>, _ key: CodingKeys) throws -> Date {
        let text = try c.decode(String.self, forKey: key)
        let plain = ISO8601DateFormatter()
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = plain.date(from: text) ?? fractional.date(from: text) { return d }
        throw DecodingError.dataCorruptedError(forKey: key, in: c, debugDescription: "bad date: \(text)")
    }
}

/// The result of signing in: a login token, and whether the account already has a profile.
struct SessionInfo: Decodable, Equatable {
    let token: String
    let hasProfile: Bool

    enum CodingKeys: String, CodingKey {
        case token
        case hasProfile = "has_profile"
    }
}

/// "yyyy-MM-dd" in the device's calendar and time zone. A birth date is a calendar
/// day, not a moment in time, so we always read and write it in local terms.
enum DayFormat {
    static let formatter: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")   // fixed format, independent of user settings
        f.calendar = Calendar(identifier: .gregorian)
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()
}

/// The 16 MBTI types, for the picker.
let allMBTITypes: [String] = [
    "INTJ", "INTP", "ENTJ", "ENTP",
    "INFJ", "INFP", "ENFJ", "ENFP",
    "ISTJ", "ISFJ", "ESTJ", "ESFJ",
    "ISTP", "ISFP", "ESTP", "ESFP",
]
