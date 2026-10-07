# Launch checklist (things only you can do, or that need a real Apple account / server)

The code for sign-in, the paywall and subscription verification is built and tested locally.
These steps remain before real users can use it. Nothing below has been done or tested against
Apple's real services, because that needs your developer account.

## 1. Apple Developer account and App Store Connect
- [ ] Join the Apple Developer Program (needed for device builds, TestFlight, Sign in with Apple, in-app purchases).
- [ ] Create the App ID `com.libofu.yipath` and enable the **Sign in with Apple** capability on it.
- [ ] In `ios/project.yml`, set your `DEVELOPMENT_TEAM`, then `cd ios && xcodegen`.
- [ ] In App Store Connect create one **subscription group** with two auto-renewable subscriptions whose
      product ids are exactly `com.libofu.yipath.monthly` and `com.libofu.yipath.yearly`.
      The prices in `ios/StoreKit/Yipath.storekit` (¥18 / ¥128) are **placeholders** for local testing only.
- [ ] Sign the Paid Applications agreement and fill in tax/banking, or purchases will not work.

## 2. Required links and wording
- [ ] Publish a Terms of Use and a Privacy Policy, then set `Copy.termsURL` / `Copy.privacyURL`
      in `ios/Yipath/Theme.swift` (the paywall shows them once set; App Review requires both).
- [ ] The privacy policy and App Store "App Privacy" answers must say birth date/time, MBTI and
      subscription status are sent to your server, and that the reading text is generated with a
      third-party AI model (currently DeepSeek).

## 3. Deploy the backend
- [ ] Host it somewhere with HTTPS (the app only allows plain http to localhost). Keep `yipath.sqlite3`
      on a persistent disk and back it up.
- [ ] Set environment: `YIPATH_ENV=production`, the model API key, and optionally `YIPATH_TRIAL_DAYS`.
      In production the anonymous dev signup (`POST /profile`) is off and `YIPATH_STOREKIT_LOCAL` is ignored.
- [ ] Point the app at it: change `YIPATH_API_BASE_URL` in `ios/project.yml` (an `https://` URL).

- [ ] In App Store Connect (App Information > App Store Server Notifications) set the **Production** and
      **Sandbox** URL to `https://<your-host>/apple/notifications` and choose **Version 2**. This is how renewals
      and refunds reach the server when the user does not open the app. Use "Request a test notification" to check it
      (the server answers `{"handled": false}` for Apple's TEST message).

## 4. Verify against the real App Store (cannot be done offline)
- [ ] Sign in with Apple on a real device or a simulator signed in to an Apple ID.
- [ ] Make a **sandbox** purchase (TestFlight or a sandbox tester). Confirm `POST /subscription/verify` returns 200.
      This is the first test against Apple's real certificate chain: the marker OIDs in
      `backend/app/subscription.py` (`LEAF_MARKER_OID`, `INTERMEDIATE_MARKER_OID`) were copied from Apple's
      open-source library and could only be checked against a locally built chain.
- [ ] Check: renewal arrives, "Restore purchases" works, a refund from a sandbox tester cuts access, deleting the account works.

## Known gaps (not blockers for a first TestFlight)
- The webhook only knows subscriptions an account has already registered through the app. A notification for an
  unknown subscription is acknowledged and ignored.
- The free trial is server-side (3 days from signup, per Apple ID), not an Apple introductory offer.
- Deleting the account erases server data but cannot cancel the Apple subscription; the app tells the user.
- Local StoreKit test purchases all report transaction id `0`, so two dev accounts cannot both "buy" in local mode.
