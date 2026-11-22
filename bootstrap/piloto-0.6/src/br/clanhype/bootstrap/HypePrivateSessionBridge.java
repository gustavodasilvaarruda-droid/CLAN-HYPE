package br.clanhype.bootstrap;

import java.nio.file.Path;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.BooleanSupplier;

/**
 * Session-only bridge, called from the HYPE Client AFTER a successful login.
 * Never writes, prints, or returns the bearer token. OFF by default.
 * This pilot stages files only; it cannot install anything into mods/.
 */
public final class HypePrivateSessionBridge {
    private static final AtomicLong EPOCH = new AtomicLong();
    private static final Object LOCK = new Object();
    private static Thread worker;

    private HypePrivateSessionBridge() { }

    public static void acceptLogin(String bearer) {
        if (bearer == null || bearer.isBlank() || bearer.length() > 8192 ||
                bearer.indexOf('\r') >= 0 || bearer.indexOf('\n') >= 0) return;
        Path gameDir;
        try {
            Class<?> loader = Class.forName("net.fabricmc.loader.api.FabricLoader");
            Object fabric = loader.getMethod("getInstance").invoke(null);
            gameDir = (Path) loader.getMethod("getGameDir").invoke(fabric);
            if (UpdateConfiguration.load(gameDir) == UpdateMode.OFF) {
                System.out.println("[HYPE 0.6] Login bridge OK; private updates OFF (no downloads).");
                return;
            }
        } catch (Exception | LinkageError failure) {
            System.err.println("[HYPE 0.6] Private staging unavailable: " +
                    failure.getClass().getSimpleName());
            return;
        }
        synchronized (LOCK) {
            long epoch = EPOCH.incrementAndGet();
            if (worker != null) worker.interrupt();
            BooleanSupplier stillAuthenticated = () -> EPOCH.get() == epoch &&
                    !Thread.currentThread().isInterrupted();
            Thread next = new Thread(() -> {
                try {
                    PrivateModUpdater.Result result = PrivateModUpdater.stageAfterLogin(
                            gameDir, bearer, stillAuthenticated);
                    if (stillAuthenticated.getAsBoolean())
                        System.out.printf("[HYPE 0.6] Private stage: offered=%d, staged=%d, cached=%d%n",
                                result.offered(), result.staged(), result.alreadyPresent());
                } catch (Exception failure) {
                    if (stillAuthenticated.getAsBoolean())
                        System.err.println("[HYPE 0.6] Private staging deferred: " +
                                failure.getClass().getSimpleName());
                } finally {
                    synchronized (LOCK) {
                        if (worker == Thread.currentThread()) worker = null;
                    }
                }
            }, "hype-private-stage-after-login");
            next.setDaemon(true);
            worker = next;
            next.start();
        }
    }

    /** Logout cancels the in-flight stage and prevents stale writes. */
    public static void onLogout() {
        synchronized (LOCK) {
            EPOCH.incrementAndGet();
            if (worker != null) worker.interrupt();
            worker = null;
        }
        System.out.println("[HYPE 0.6] Logout bridge OK; staging cancelled.");
    }
}
