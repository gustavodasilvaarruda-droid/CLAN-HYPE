package br.clanhype.client;

/**
 * Optional cross-mod integration with HYPE Bootstrap 0.6.
 * The HYPE Client keeps working on its own if Bootstrap is absent.
 * Never logs or persists an access token.
 */
public final class HypeAutoStagingBridge {
    private static final String BOOTSTRAP = "br.clanhype.bootstrap.HypePrivateSessionBridge";
    private HypeAutoStagingBridge() { }

    static void afterLogin(String bearer) {
        if (bearer == null || bearer.isBlank()) return;
        try {
            Class<?> bridge = Class.forName(BOOTSTRAP);
            bridge.getMethod("acceptLogin", String.class).invoke(null, bearer);
        } catch (ClassNotFoundException ignored) {
            // Bootstrap is optional for the HYPE Client.
        } catch (ReflectiveOperationException | LinkageError failure) {
            System.err.println("[HYPE Client] Optional Bootstrap bridge unavailable: " +
                    failure.getClass().getSimpleName());
        }
    }

    static void afterLogout() {
        try {
            Class<?> bridge = Class.forName(BOOTSTRAP);
            bridge.getMethod("onLogout").invoke(null);
        } catch (ClassNotFoundException ignored) {
        } catch (ReflectiveOperationException | LinkageError failure) {
            System.err.println("[HYPE Client] Optional Bootstrap bridge unavailable: " +
                    failure.getClass().getSimpleName());
        }
    }
}
