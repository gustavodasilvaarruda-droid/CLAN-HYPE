package br.clanhype.bootstrap;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.util.List;

/**
 * Deterministic, OFFLINE regression test. Requires the 0.6
 * PrivateModUpdaterTest helper on the test classpath.
 * No Render, Supabase, Fabric or real HYPE account is contacted.
 */
public final class PrivateAuthorizedPostExitTest {
    private static int assertions;

    private static void check(boolean result, String name) {
        if (!result) throw new AssertionError(name);
        assertions++;
    }

    private static void refuses(Throwing action, String name) throws Exception {
        try {
            action.run();
            throw new AssertionError("Failed to reject " + name);
        } catch (SecurityException expected) {
            assertions++;
        }
    }
    @FunctionalInterface interface Throwing { void run() throws Exception; }

    public static void main(String[] args) throws Exception {
        Path game = Files.createTempDirectory("hype-post-exit-agent-test-");
        PrivateModUpdaterTest.setMode(game, "after_exit");
        byte[] jar = PrivateModUpdaterTest.jar();
        String sha = PrivateModUpdaterTest.sha(jar);
        String url = PrivateModUpdater.API + "/mods/" +
                PrivateModUpdaterTest.ID + "/" + sha + ".jar";
        KeyPair keys = KeyPairGenerator.getInstance("Ed25519").generateKeyPair();
        String manifest = PrivateModUpdaterTest.manifest(
                keys, url, sha, jar.length);
        PrivateModUpdater.Release release = new PrivateModUpdater.Release(
                PrivateModUpdaterTest.ID, PrivateModUpdaterTest.VERSION,
                sha, jar.length, 1, url, manifest);
        String listing = PrivateModUpdaterTest.releaseJson(
                manifest, url, sha, jar.length);
        PrivateModUpdater.Fetcher good = (requested, token, limit) -> {
            if (!"test-only-token".equals(token))
                throw new SecurityException("No live session");
            if (!requested.equals(PrivateModUpdater.API + "/releases"))
                throw new AssertionError("Unexpected endpoint");
            return listing.getBytes(StandardCharsets.UTF_8);
        };
        Path staging = game.resolve(".hype-private-staging");
        Files.createDirectory(staging);
        Files.write(staging.resolve(release.id() + "-" + sha + ".jar"), jar);

        refuses(() -> PrivateAuthorizedPostExit.apply(
                game, "test-only-token", List.of(release),
                () -> false, keys.getPublic(), good), "game still running");
        check(!Files.exists(game.resolve("mods")), "running game left untouched");
        refuses(() -> PrivateAuthorizedPostExit.apply(
                game, "", List.of(release),
                () -> true, keys.getPublic(), good), "missing session");
        refuses(() -> PrivateAuthorizedPostExit.apply(
                game, "test-only-token", List.of(release, release),
                () -> true, keys.getPublic(), good), "duplicate signed release");
        PrivateModUpdater.Fetcher revoked = (requested, token, max) ->
                "{\"ok\":true,\"releases\":[]}".getBytes(StandardCharsets.UTF_8);
        refuses(() -> PrivateAuthorizedPostExit.apply(
                game, "test-only-token", List.of(release),
                () -> true, keys.getPublic(), revoked), "permission revoked");
        check(!Files.exists(game.resolve("mods")), "revoked account left untouched");

        List<PrivateAuthorizedPostExit.Installed> first = PrivateAuthorizedPostExit.apply(
                game, "test-only-token", List.of(release),
                () -> true, keys.getPublic(), good);
        check(first.size() == 1 && first.get(0).outcome()
                == PrivateAuthorizedPostExit.Outcome.FIRST_INSTALLED,
                "first verified installation");
        check(Files.exists(game.resolve("mods/hype-" + release.id() +
                "-" + sha + ".jar")), "created signed approved private JAR");
        List<PrivateAuthorizedPostExit.Installed> again = PrivateAuthorizedPostExit.apply(
                game, "test-only-token", List.of(release),
                () -> true, keys.getPublic(), good);
        check(again.size() == 1 && again.get(0).outcome()
                == PrivateAuthorizedPostExit.Outcome.ALREADY_CURRENT,
                "repeat is idempotent");
        check(!Files.readString(game.resolve(
                ".hype-private-managed/" + release.id() + ".state"))
                .contains("test-only-token"), "token never stored in managed marker");

        PrivateModUpdaterTest.setMode(game, "off");
        refuses(() -> PrivateAuthorizedPostExit.apply(
                game, "test-only-token", List.of(release),
                () -> true, keys.getPublic(), good), "default OFF blocks agent");
        System.out.println("PASS: " + assertions + " post-exit auth checks (offline)");
    }
}
