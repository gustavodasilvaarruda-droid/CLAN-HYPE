package br.clanhype.bootstrap;

import net.fabricmc.api.ClientModInitializer;
import java.nio.file.Path;

/** Fabric entrypoint; remains inert without explicit local configuration. */
public final class HypeBootstrap implements ClientModInitializer {
    @Override
    public void onInitializeClient() {
        Thread check = new Thread(() -> {
            try {
                Class<?> loader = Class.forName("net.fabricmc.loader.api.FabricLoader");
                Object instance = loader.getMethod("getInstance").invoke(null);
                Path gameDir = (Path) loader.getMethod("getGameDir").invoke(instance);
                UpdateCoordinator.runOnGameStart(gameDir);
            } catch (Exception failure) {
                System.err.println("[HYPE Bootstrap 0.5] Update check failed safely: "
                        + failure.getClass().getSimpleName() + ": " + failure.getMessage());
            }
        }, "hype-bootstrap-0.5-preview");
        check.setDaemon(true);
        check.start();
    }
}
