package studio.beyonders.initiative;

import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.security.NetworkSecurityPolicy;
import com.android.billingclient.api.BillingClient;
import com.android.billingclient.api.BillingClientStateListener;
import com.android.billingclient.api.BillingResult;
import com.android.billingclient.api.GetBillingConfigParams;
import com.android.billingclient.api.PendingPurchasesParams;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.google.android.play.core.review.ReviewManager;
import com.google.android.play.core.review.ReviewManagerFactory;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Facts about this install that the web layer cannot see: which app installed it (Google Play
 * is "com.android.vending"), so an update prompt can send a Play install to Play, and whether
 * this build may reach plain-HTTP servers, which only a debug build does. For a Play install it
 * also reports the country of the person's Play billing account, which decides whether the app
 * may link to the web for plans, and it can hand Play its review prompt.
 */
@CapacitorPlugin(name = "AppEnvironment")
public class AppEnvironmentPlugin extends Plugin {

    private static final String PLAY_STORE_INSTALLER = "com.android.vending";
    private static final long STORE_COUNTRY_TIMEOUT_MS = 5000;

    @PluginMethod
    public void get(PluginCall call) {
        JSObject result = new JSObject();
        String installer = installerPackage();
        if (installer != null) {
            result.put("installer", installer);
        }
        result.put("cleartextPermitted", NetworkSecurityPolicy.getInstance().isCleartextTrafficPermitted());
        call.resolve(result);
    }

    /**
     * Resolves {country} with the Play billing country (ISO 3166-1 alpha-2) for a Play install,
     * and {} for any other install, or when Play cannot say within the timeout.
     */
    @PluginMethod
    public void storeCountry(PluginCall call) {
        if (!PLAY_STORE_INSTALLER.equals(installerPackage())) {
            call.resolve(new JSObject());
            return;
        }

        AtomicBoolean finished = new AtomicBoolean(false);
        Handler mainHandler = new Handler(Looper.getMainLooper());
        BillingClient client;
        try {
            client = BillingClient.newBuilder(getContext())
                .setListener((billingResult, purchases) -> {})
                .enablePendingPurchases(PendingPurchasesParams.newBuilder().enableOneTimeProducts().build())
                .build();
        } catch (RuntimeException e) {
            call.resolve(new JSObject());
            return;
        }

        Runnable timeout = () -> finishStoreCountry(call, client, null, finished);
        mainHandler.postDelayed(timeout, STORE_COUNTRY_TIMEOUT_MS);

        try {
            client.startConnection(
                new BillingClientStateListener() {
                    @Override
                    public void onBillingSetupFinished(BillingResult setupResult) {
                        // The timeout already answered and closed the client.
                        if (finished.get()) {
                            return;
                        }
                        if (setupResult.getResponseCode() != BillingClient.BillingResponseCode.OK) {
                            mainHandler.removeCallbacks(timeout);
                            finishStoreCountry(call, client, null, finished);
                            return;
                        }
                        client.getBillingConfigAsync(
                            GetBillingConfigParams.newBuilder().build(),
                            (configResult, billingConfig) -> {
                                mainHandler.removeCallbacks(timeout);
                                String country = null;
                                if (configResult.getResponseCode() == BillingClient.BillingResponseCode.OK && billingConfig != null) {
                                    country = billingConfig.getCountryCode();
                                }
                                finishStoreCountry(call, client, country, finished);
                            }
                        );
                    }

                    @Override
                    public void onBillingServiceDisconnected() {
                        mainHandler.removeCallbacks(timeout);
                        finishStoreCountry(call, client, null, finished);
                    }
                }
            );
        } catch (RuntimeException e) {
            mainHandler.removeCallbacks(timeout);
            finishStoreCountry(call, client, null, finished);
        }
    }

    /**
     * Hands Google Play its in-app review prompt, for a Play install only. Play decides whether
     * it shows and never says whether it did or whether a review was left, so the call resolves
     * {} either way, once the prompt is gone or was never shown.
     */
    @PluginMethod
    public void requestReview(PluginCall call) {
        if (!PLAY_STORE_INSTALLER.equals(installerPackage()) || getActivity() == null) {
            call.resolve();
            return;
        }
        ReviewManager manager = ReviewManagerFactory.create(getContext());
        manager
            .requestReviewFlow()
            .addOnCompleteListener(request -> {
                if (!request.isSuccessful() || getActivity() == null) {
                    call.resolve();
                    return;
                }
                manager.launchReviewFlow(getActivity(), request.getResult()).addOnCompleteListener(flow -> call.resolve());
            });
    }

    /** Resolves the call once, whichever of the answer, a failure or the timeout comes first. */
    private void finishStoreCountry(PluginCall call, BillingClient client, String country, AtomicBoolean finished) {
        if (!finished.compareAndSet(false, true)) {
            return;
        }
        JSObject result = new JSObject();
        if (country != null && !country.isEmpty()) {
            result.put("country", country);
        }
        call.resolve(result);
        try {
            client.endConnection();
        } catch (RuntimeException e) {
            // The connection is already gone.
        }
    }

    @SuppressWarnings("deprecation")
    private String installerPackage() {
        PackageManager packageManager = getContext().getPackageManager();
        String packageName = getContext().getPackageName();
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                return packageManager.getInstallSourceInfo(packageName).getInstallingPackageName();
            }
            return packageManager.getInstallerPackageName(packageName);
        } catch (PackageManager.NameNotFoundException | IllegalArgumentException e) {
            return null;
        }
    }
}
