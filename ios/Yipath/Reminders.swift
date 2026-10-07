import UserNotifications

/// The slice of UNUserNotificationCenter we use. Putting it behind a protocol lets the tests
/// use a fake instead of the real system notification center.
protocol NotificationCentering {
    func requestAuthorization() async -> Bool
    func add(_ request: UNNotificationRequest) async throws
    func removePending(withIdentifiers ids: [String])
}

extension UNUserNotificationCenter: NotificationCentering {
    /// Asks the user for permission (shows the system prompt the first time only).
    func requestAuthorization() async -> Bool {
        (try? await requestAuthorization(options: [.alert, .sound])) ?? false
    }

    func removePending(withIdentifiers ids: [String]) {
        removePendingNotificationRequests(withIdentifiers: ids)
    }
}

/// The optional daily reminder: "your reading is ready", at a time the user picks.
///
/// It is a *local* notification (scheduled on the phone, no server or push needed). The text is
/// fixed, not the reading itself, because the reading is written on demand by the server.
/// We schedule seven repeating notifications, one per weekday, so the line changes through the week.
struct ReminderScheduler {
    var center: NotificationCentering = UNUserNotificationCenter.current()

    static let enabledKey = "yipath.reminder.enabled"
    static let hourKey = "yipath.reminder.hour"
    static let minuteKey = "yipath.reminder.minute"
    static let defaultHour = 8

    private static let idPrefix = "yipath.daily."

    /// Keyed by weekday as Calendar numbers it: 1 = Sunday ... 7 = Saturday. Calm, never alarming.
    static let lines: [Int: String] = [
        1: "新的一周将启，先看看本周的宜与忌。",
        2: "一周之始，今日宜忌已备好。",
        3: "今日的安排，先生已为你理好。",
        4: "周中一日，翻开看看今日宜忌。",
        5: "今日宜忌已备好，从容应对。",
        6: "一周将尽，看看今日该留意什么。",
        7: "闲暇之日，也看看今日的宜与忌。",
    ]

    private var identifiers: [String] { (1...7).map { Self.idPrefix + String($0) } }

    /// Asks permission if needed, then schedules. Returns false if the user said no.
    func enable(hour: Int, minute: Int) async -> Bool {
        guard await center.requestAuthorization() else { return false }
        await reschedule(hour: hour, minute: minute)
        return true
    }

    /// Replaces any existing reminders with ones at the new time.
    func reschedule(hour: Int, minute: Int) async {
        cancel()
        for weekday in 1...7 {
            let content = UNMutableNotificationContent()
            content.title = "易行"
            content.body = Self.lines[weekday] ?? "今日宜忌已备好。"
            content.sound = .default
            // `repeats: true` with a weekday + time means "every week at this time".
            let when = DateComponents(hour: hour, minute: minute, weekday: weekday)
            let trigger = UNCalendarNotificationTrigger(dateMatching: when, repeats: true)
            let request = UNNotificationRequest(identifier: Self.idPrefix + String(weekday), content: content, trigger: trigger)
            try? await center.add(request)
        }
    }

    func cancel() {
        center.removePending(withIdentifiers: identifiers)
        UserDefaults.standard.set(false, forKey: Self.enabledKey)
    }
}
