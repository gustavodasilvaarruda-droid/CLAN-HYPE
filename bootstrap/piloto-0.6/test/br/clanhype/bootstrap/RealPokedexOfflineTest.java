package br.clanhype.bootstrap;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.MessageDigest;
import java.security.Signature;
import java.util.Base64;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Opt-in OFFLINE test using the owner's locally available protected Pokédex JAR.
 * Does NOT contact Render, sign with a production key, touch real mods/ or install.
 * The JAR itself must NEVER be committed to GitHub.
 */
public final class RealPokedexOfflineTest {
    static final String ID = "hype_pokedex";
    static final String VERSION =
        "2.0.0-beta.8-defesas-multiplas-colecao-compacta-20261109";
    static final String SHA =
        "176819c73facf52da2826ba3ac1d179926670d64f10c6e92923ccefa65f5ca18";
    static final String TOKEN = "temporary-offline-fixture";
    static int checks;
    interface Work { void run() throws Exception; }
    static void check(boolean ok, String label) {
        if (!ok) throw new AssertionError(label);
        checks++;
    }
    static void rejects(Work action, String label) throws Exception {
        try {
            action.run();
        } catch (SecurityException expected) {
            checks++;
            return;
        }
        throw new AssertionError("Rejected input was accepted: " + label);
    }
    static String hash(byte[] bytes) throws Exception {
        StringBuilder s = new StringBuilder();
        for (byte b : MessageDigest.getInstance("SHA-256").digest(bytes))
            s.append(String.format("%02x", b & 255));
        return s.toString();
    }
    static String signed(KeyPair key, String url, int size) throws Exception {
        Map<String, String> values = Map.of(
            "release", "1", "version", VERSION, "url", url, "sha256", SHA,
            "size", Integer.toString(size), "minecraft", "1.21.1",
            "mod_id", ID, "channel", "stable");
        StringBuilder canonical = new StringBuilder();
        for (String field : PrivateModUpdater.FIELDS)
            canonical.append(field).append('=').append(values.get(field)).append('\n');
        Signature signature = Signature.getInstance("Ed25519");
        signature.initSign(key.getPrivate());
        signature.update(canonical.toString().getBytes(StandardCharsets.US_ASCII));
        return canonical + "signature=" +
            Base64.getEncoder().encodeToString(signature.sign()) + "\n";
    }
    static byte[] catalog(String manifest, String url, int size) {
        return JsonCodec.canonical(Map.of(
            "ok", true,
            "releases", List.of(Map.of(
                "id", ID, "version", VERSION, "release", 1L,
                "sha256", SHA, "size", (long) size,
                "url", url, "manifest", manifest
            ))
        )).getBytes(StandardCharsets.UTF_8);
    }
    static Path stagingDir() throws Exception {
        Path dir = Files.createTempDirectory("hype-pokedex-real-offline-");
        Files.createDirectories(dir.resolve("config"));
        Files.writeString(dir.resolve("config/hype-bootstrap.properties"),
                          "update_mode=stage\n");
        return dir;
    }
    public static void main(String[] args) throws Exception {
        if (args.length != 1) throw new IllegalArgumentException(
            "Supply path to the private, protected Pokédex JAR (never Git-commit it)");
        byte[] jar = Files.readAllBytes(Path.of(args[0]));
        check(SHA.equals(hash(jar)), "Exact tested protected Pokédex SHA-256");
        check(jar.length >= 1000 && jar.length <= 10 * 1024 * 1024,
              "Within private release limit");
        String url = PrivateModUpdater.API + "/mods/" + ID + "/" + SHA + ".jar";
        KeyPair key = KeyPairGenerator.getInstance("Ed25519").generateKeyPair();
        KeyPair wrong = KeyPairGenerator.getInstance("Ed25519").generateKeyPair();
        String manifest = signed(key, url, jar.length);
        byte[] catalog = catalog(manifest, url, jar.length);
        check(PrivateModUpdater.readReleases(catalog, key.getPublic()).size() == 1,
              "Signed catalog verified with throwaway key");
        int[] binaryCalls = {0};
        PrivateModUpdater.Fetcher server = (requested, token, max) -> {
            if (!TOKEN.equals(token)) throw new SecurityException("Unauthorized session");
            if (requested.equals(PrivateModUpdater.API + "/releases")) return catalog;
            if (requested.equals(url)) {
                binaryCalls[0]++;
                return jar;
            }
            throw new SecurityException("Unrecognized URL");
        };
        Path game = stagingDir();
        Path mods = Files.createDirectory(game.resolve("mods"));
        Files.writeString(mods.resolve("another-mod.jar"), "never replace");
        var first = PrivateModUpdater.stageAfterLogin(
            game, TOKEN, key.getPublic(), server, () -> true);
        check(first.staged() == 1 && first.offered() == 1, "Protected JAR staged");
        Path candidate = game.resolve(".hype-private-staging")
            .resolve(ID + "-" + SHA + ".jar");
        check(Files.exists(candidate) && SHA.equals(hash(Files.readAllBytes(candidate))),
              "Staged real JAR has expected SHA");
        check(Files.readString(mods.resolve("another-mod.jar")).equals("never replace")
              && Files.list(mods).count() == 1, "mods/ untouched");
        check(PrivateModUpdater.stageAfterLogin(
            game, TOKEN, key.getPublic(), server, () -> true).alreadyPresent() == 1
            && binaryCalls[0] == 1, "Validated cached stage reused");
        rejects(() -> PrivateModUpdater.readReleases(catalog, wrong.getPublic()),
                "Invalid signature");
        byte[] tampered = jar.clone();
        tampered[tampered.length / 2] ^= 0x20;
        Path tamperDir = stagingDir();
        rejects(() -> PrivateModUpdater.stageAfterLogin(tamperDir, TOKEN,
            key.getPublic(), (requested, token, limit) ->
                requested.endsWith("/releases") ? catalog : tampered, () -> true),
            "Tampered private binary");
        check(Files.list(tamperDir.resolve(".hype-private-staging")).count() == 0,
              "No corrupt staged JAR");
        AtomicBoolean active = new AtomicBoolean(true);
        Path logoutDir = stagingDir();
        rejects(() -> PrivateModUpdater.stageAfterLogin(logoutDir, TOKEN,
            key.getPublic(), (requested, token, limit) -> {
                if (requested.endsWith("/releases")) return catalog;
                active.set(false);
                return jar;
            }, active::get), "Logout while downloading");
        check(Files.list(logoutDir.resolve(".hype-private-staging")).count() == 0,
              "No staged JAR after logout");
        Path deniedDir = stagingDir();
        byte[] empty = JsonCodec.canonical(Map.of(
            "ok", true, "releases", List.of())).getBytes(StandardCharsets.UTF_8);
        check(PrivateModUpdater.stageAfterLogin(deniedDir, TOKEN,
            key.getPublic(), (requested, token, limit) -> {
                if (requested.endsWith("/releases")) return empty;
                throw new SecurityException("Unauthorized binary");
            }, () -> true).offered() == 0, "Entitlement-denied empty catalog");
        check(Files.list(deniedDir.resolve(".hype-private-staging")).count() == 0,
              "No JAR for denied account");
        Path off = Files.createTempDirectory("hype-bootstrap-default-off-");
        check(PrivateModUpdater.stageAfterLogin(off, null,
            key.getPublic(), (requested, token, limit) -> {
                throw new AssertionError("OFF cannot make HTTP requests");
            }, () -> false).staged() == 0, "OFF remains zero-network");
        check(!Files.exists(off.resolve(".hype-private-staging")),
              "OFF does not write staging files");
        System.out.println("PASS: " + checks +
            " real-artifact offline assertions; no network or installation.");
    }
}
