package br.clanhype.bootstrap;

import net.fabricmc.api.ClientModInitializer;

/**
 * Safe Fabric entrypoint for the private-update staging pilot.
 *
 * There is intentionally NO automatic network activity on game startup.
 * The HYPE Client must complete login and explicitly invoke
 * PrivateModUpdater.stageAfterLogin(gameDir, token) in a future integration.
 * This pilot cannot install/restart itself or launch the legacy 0.5 updater.
 */
public final class HypeBootstrap implements ClientModInitializer {
    @Override
    public void onInitializeClient() {
        System.out.println("[HYPE Bootstrap 0.6 PILOTO] Loaded; updater inactive until authenticated HYPE Client integration.");
    }
}
