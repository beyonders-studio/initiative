import Capacitor
import Foundation
import StoreKit

/// Facts about this install that the web layer cannot see. On iOS that is the App Store
/// storefront the person's account belongs to, which decides whether the app may link to the
/// web for plans. It also hands the App Store its review prompt. The name matches the Android plugin so the web layer calls one interface.
@objc(AppEnvironmentPlugin)
public class AppEnvironmentPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "AppEnvironmentPlugin"
    public let jsName = "AppEnvironment"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "storeCountry", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "requestReview", returnType: CAPPluginReturnPromise)
    ]

    /// Resolves `{country}` with the storefront's ISO 3166-1 alpha-3 code (e.g. "USA"), or `{}`
    /// when StoreKit has no storefront to report.
    @objc func storeCountry(_ call: CAPPluginCall) {
        Task {
            if let country = await Storefront.current?.countryCode, !country.isEmpty {
                call.resolve(["country": country])
            } else {
                call.resolve([:])
            }
        }
    }

    /// Hands the App Store its review prompt for the app's window. StoreKit decides whether it
    /// shows and never says whether it did, so this resolves `{}` either way.
    @objc func requestReview(_ call: CAPPluginCall) {
        Task { @MainActor in
            if let scene = self.bridge?.viewController?.view.window?.windowScene {
                AppStore.requestReview(in: scene)
            }
            call.resolve()
        }
    }
}
