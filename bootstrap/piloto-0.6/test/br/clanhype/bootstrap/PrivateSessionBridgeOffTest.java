package br.clanhype.bootstrap;
import java.nio.file.Files;
import java.nio.file.Path;

/** Login/logout with default OFF must not download or change mods. */
public final class PrivateSessionBridgeOffTest {
    public static void main(String[] args) throws Exception {
        Path gameDir = Files.createTempDirectory("hype-06-off-");
        net.fabricmc.loader.api.FabricLoader.gameDir = gameDir;
        HypePrivateSessionBridge.acceptLogin("some-temporary-token");
        HypePrivateSessionBridge.onLogout();
        if (Files.exists(gameDir.resolve(".hype-private-staging")))
            throw new AssertionError("OFF mode unexpectedly touched staging");
        if (Files.exists(gameDir.resolve("mods")))
            throw new AssertionError("OFF mode unexpectedly touched mods");
        System.out.println("PASS: no network/staging/modification for OFF mode with login/logout events");
    }
}
