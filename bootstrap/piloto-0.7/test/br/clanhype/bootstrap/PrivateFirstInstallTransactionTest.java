package br.clanhype.bootstrap;

import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.MessageDigest;
import java.security.Signature;
import java.util.Base64;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/** Offline test with owner's protected beta 8; throwaway signing key. */
public final class PrivateFirstInstallTransactionTest {
    static byte[] unrelatedMod() throws Exception {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        try (ZipOutputStream zip = new ZipOutputStream(out)) {
            zip.putNextEntry(new ZipEntry("fabric.mod.json"));
            zip.write("{\"id\":\"other_mod\",\"version\":\"1.0\"}".getBytes(StandardCharsets.UTF_8));
            zip.closeEntry();
        }
        return out.toByteArray();
    }
    static int passed;
    static final String ID = "hype_pokedex";
    static final String VERSION = "2.0.0-beta.8-defesas-multiplas-colecao-compacta-20261109";
    static final String SHA = "176819c73facf52da2826ba3ac1d179926670d64f10c6e92923ccefa65f5ca18";

    static String hash(byte[] bytes) throws Exception {
        StringBuilder out = new StringBuilder();
        for(byte b : MessageDigest.getInstance("SHA-256").digest(bytes))
            out.append(String.format("%02x", b & 255));
        return out.toString();
    }
    static String signed(KeyPair kp, String url, int size) throws Exception {
        Map<String,String> map = Map.of("release","1", "version", VERSION, "url",url,
            "sha256",SHA,"size",String.valueOf(size),"minecraft","1.21.1",
            "mod_id",ID,"channel","stable");
        StringBuilder canonical = new StringBuilder();
        for(String field : PrivateModUpdater.FIELDS)
            canonical.append(field).append('=').append(map.get(field)).append('\n');
        Signature signer = Signature.getInstance("Ed25519");
        signer.initSign(kp.getPrivate());
        signer.update(canonical.toString().getBytes(StandardCharsets.US_ASCII));
        return canonical + "signature=" + Base64.getEncoder().encodeToString(signer.sign()) + "\n";
    }
    static void check(boolean yes, String message) {
        if (!yes) throw new AssertionError(message);
        passed++;
    }
    interface Work { void run() throws Exception; }
    static void denies(Work action) throws Exception {
        try { action.run(); }
        catch (SecurityException expected) { passed++; return; }
        throw new AssertionError("Unsafe installation was accepted");
    }
    static Path game(byte[] jar, PrivateModUpdater.Release release) throws Exception {
        Path root = Files.createTempDirectory("hype-afterexit-fixture-");
        Path stage = Files.createDirectory(root.resolve(".hype-private-staging"));
        Path config = Files.createDirectory(root.resolve("config"));
        Files.writeString(config.resolve("hype-bootstrap.properties"), "update_mode=after_exit\n");
        Files.write(stage.resolve(release.id() + "-" + release.sha256() + ".jar"), jar);
        return root;
    }
    static Path target(Path game, PrivateModUpdater.Release release) {
        return game.resolve("mods/hype-" + release.id() + "-" + release.sha256() + ".jar");
    }
    public static void main(String[] args) throws Exception {
        if (args.length != 1) throw new IllegalArgumentException("Protected Pokédex JAR path required");
        byte[] jar = Files.readAllBytes(Path.of(args[0]));
        check(SHA.equals(hash(jar)), "Exact tested protected binary");
        KeyPair signer = KeyPairGenerator.getInstance("Ed25519").generateKeyPair();
        String url = PrivateModUpdater.API + "/mods/hype_pokedex/" + SHA + ".jar";
        var release = new PrivateModUpdater.Release(ID, VERSION, SHA, jar.length, 1, url,
                                                   signed(signer, url, jar.length));
        Path root = game(jar, release);
        Files.createDirectory(root.resolve("mods"));
        Files.write(root.resolve("mods/another-mod.jar"), unrelatedMod());
        denies(() -> PrivateFirstInstallTransaction.apply(root, release,
                signer.getPublic(), () -> false, () -> true, () -> {}));
        check(!Files.exists(target(root, release)), "Game-running gate leaves mods unchanged");
        denies(() -> PrivateFirstInstallTransaction.apply(root, release,
                signer.getPublic(), () -> true, () -> false, () -> {}));
        check(!Files.exists(target(root, release)), "Permission gate leaves mods unchanged");
        AtomicBoolean canInstall = new AtomicBoolean(true);
        var installed = PrivateFirstInstallTransaction.apply(root, release,
                signer.getPublic(), () -> true, canInstall::get, () -> {});
        check(installed == PrivateFirstInstallTransaction.Outcome.INSTALLED,
                "Exclusive first installation succeeded");
        check(SHA.equals(hash(Files.readAllBytes(target(root, release)))),
                "Installed protected hash matches signature");
        check(Files.exists(root.resolve(".hype-private-managed/hype_pokedex.state")),
                "Installed mod receives a managed state");
        check(java.util.Arrays.equals(Files.readAllBytes(root.resolve("mods/another-mod.jar")), unrelatedMod()),
                "Unrelated mod remains untouched");
        var cached = PrivateFirstInstallTransaction.apply(root, release,
                signer.getPublic(), () -> true, () -> true, () -> {});
        check(cached == PrivateFirstInstallTransaction.Outcome.EXACT_JAR_ALREADY_PRESENT,
                "Exact installed version is not modified");
        Path faulted = game(jar, release);
        try {
            PrivateFirstInstallTransaction.apply(faulted, release,
                    signer.getPublic(), () -> true, () -> true,
                    () -> { throw new IllegalStateException("simulated local write failure"); });
            throw new AssertionError("Simulated failure was ignored");
        } catch (IllegalStateException expected) { passed++; }
        check(!Files.exists(target(faulted, release)),
                "Rollback removes just the new incomplete installation");
        check(!Files.exists(faulted.resolve(".hype-private-managed/hype_pokedex.state")),
                "Rollback leaves no installed state marker");
        Path denied = game(jar, release);
        Files.createDirectory(denied.resolve("mods"));
        Files.write(denied.resolve("mods/my-pokedex.jar"), jar);
        check(PrivateFirstInstallTransaction.apply(denied, release,
                signer.getPublic(), () -> true, () -> true, () -> {}) ==
                PrivateFirstInstallTransaction.Outcome.EXACT_JAR_ALREADY_PRESENT,
                "Preexisting manual exact JAR is not adopted or replaced");
        check(!Files.exists(denied.resolve(".hype-private-managed/hype_pokedex.state")),
                "Never claims a manually installed mod as managed");
        Path malicious = game(jar, release);
        Path staged = malicious.resolve(".hype-private-staging/" + release.id() + "-" + release.sha256() + ".jar");
        Files.writeString(staged, "tamper!");
        denies(() -> PrivateFirstInstallTransaction.apply(malicious, release,
                signer.getPublic(), () -> true, () -> true, () -> {}));
        check(!Files.exists(target(malicious, release)), "Tampered binary never installed");
        Path revocation = game(jar, release);
        AtomicBoolean allowed = new AtomicBoolean(true);
        denies(() -> PrivateFirstInstallTransaction.apply(revocation, release,
                signer.getPublic(), () -> true, allowed::get,
                () -> allowed.set(false)));
        check(!Files.exists(target(revocation, release)),
                "Revocation before state commit triggers rollback");
        System.out.println("PASS: " + passed +
             " private first-install transaction assertions (offline, not integrated)");
    }
}
