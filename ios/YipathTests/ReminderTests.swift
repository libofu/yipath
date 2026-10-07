import UserNotifications
import XCTest
@testable import Yipath

/// Stands in for the system notification center.
final class FakeCenter: NotificationCentering {
    var grantPermission = true
    private(set) var permissionAsked = 0
    private(set) var pending: [UNNotificationRequest] = []

    func requestAuthorization() async -> Bool { permissionAsked += 1; return grantPermission }
    func add(_ request: UNNotificationRequest) async throws { pending.append(request) }
    func removePending(withIdentifiers ids: [String]) { pending.removeAll { ids.contains($0.identifier) } }
}

private func weekday(of request: UNNotificationRequest) -> Int? {
    (request.trigger as? UNCalendarNotificationTrigger)?.dateComponents.weekday
}

final class ReminderTests: XCTestCase {
    override func setUp() { UserDefaults.standard.set(true, forKey: ReminderScheduler.enabledKey) }
    override func tearDown() { UserDefaults.standard.removeObject(forKey: ReminderScheduler.enabledKey) }

    func testEnablingSchedulesOneRepeatingNotificationPerWeekday() async {
        let center = FakeCenter()
        let granted = await ReminderScheduler(center: center).enable(hour: 8, minute: 30)
        XCTAssertTrue(granted)
        XCTAssertEqual(center.pending.count, 7)
        XCTAssertEqual(Set(center.pending.compactMap(weekday(of:))), Set(1...7))
        for request in center.pending {
            let trigger = request.trigger as! UNCalendarNotificationTrigger
            XCTAssertTrue(trigger.repeats, "must repeat weekly")
            XCTAssertEqual(trigger.dateComponents.hour, 8)
            XCTAssertEqual(trigger.dateComponents.minute, 30)
            XCTAssertEqual(request.content.title, "易行")
        }
    }

    func testEveryWeekdayHasItsOwnCalmLine() {
        XCTAssertEqual(Set(ReminderScheduler.lines.keys), Set(1...7))
        XCTAssertEqual(Set(ReminderScheduler.lines.values).count, 7, "lines should differ through the week")
        for line in ReminderScheduler.lines.values {
            XCTAssertTrue(line.unicodeScalars.contains { $0.value > 0x4E00 })
            // calm tone, nothing alarming
            for scary in ["凶", "灾", "危险", "速", "立刻", "错过"] { XCTAssertFalse(line.contains(scary), line) }
        }
    }

    func testDeniedPermissionSchedulesNothing() async {
        let center = FakeCenter()
        center.grantPermission = false
        let granted = await ReminderScheduler(center: center).enable(hour: 8, minute: 0)
        XCTAssertFalse(granted)
        XCTAssertTrue(center.pending.isEmpty)
    }

    func testChangingTheTimeReplacesTheOldReminders() async {
        let center = FakeCenter()
        let scheduler = ReminderScheduler(center: center)
        _ = await scheduler.enable(hour: 8, minute: 0)
        await scheduler.reschedule(hour: 21, minute: 15)
        XCTAssertEqual(center.pending.count, 7, "no duplicates left behind")
        for request in center.pending {
            let c = (request.trigger as! UNCalendarNotificationTrigger).dateComponents
            XCTAssertEqual(c.hour, 21)
            XCTAssertEqual(c.minute, 15)
        }
    }

    func testCancelRemovesEverythingAndSwitchesTheFlagOff() async {
        let center = FakeCenter()
        let scheduler = ReminderScheduler(center: center)
        _ = await scheduler.enable(hour: 8, minute: 0)
        scheduler.cancel()
        XCTAssertTrue(center.pending.isEmpty)
        XCTAssertFalse(UserDefaults.standard.bool(forKey: ReminderScheduler.enabledKey))
    }
}

@MainActor
final class ReminderSignOutTests: XCTestCase {
    override func setUp() { TokenStore.delete(); ProfileStore.delete() }
    override func tearDown() { StubURLProtocol.handler = nil; TokenStore.delete(); ProfileStore.delete() }

    func testSigningOutStopsTheReminders() async throws {
        let center = FakeCenter()
        let scheduler = ReminderScheduler(center: center)
        StubURLProtocol.handler = { request in
            request.httpMethod == "POST" ? (200, #"{"user_id":1,"token":"t","has_profile":true}"#.data(using: .utf8)!) : (200, Data())
        }
        let state = AppState(api: makeClient(), reminders: scheduler)
        try await state.onboardAnonymously(Profile(birthDate: day("2000-01-01")))
        _ = await scheduler.enable(hour: 8, minute: 0)
        XCTAssertEqual(center.pending.count, 7)

        state.signOut()
        XCTAssertTrue(center.pending.isEmpty)
    }
}
