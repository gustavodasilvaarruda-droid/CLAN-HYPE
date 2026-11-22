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
import java.util.List;
import java.util.Map;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/** Java 21 deterministic tests with no network, no Fabric launch and no external libs. */
public final class PrivateModUpdaterTest {
    static int passed = 0;
    static final String ID = "hype_pokedex";
    static final String VERSION = "2.0.0-test";

    private static void check(boolean ok, String message) {
        if (!ok) throw new AssertionError(message);
        passed++;
    }
    private static void denies(Throwing op, String reason) throws Exception {
        try { op.run(); throw new AssertionError("Did not reject: " + reason); }
        catch (SecurityException | java.io.IOException expected) { passed++; }
    }
    @FunctionalInterface interface Throwing { void run() throws Exception; }

    static byte[] jar() throws Exception {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        try (ZipOutputStream zip = new ZipOutputStream(output)) {
            zip.putNextEntry(new ZipEntry("fabric.mod.json"));
            zip.write(("{\"id\":\"" + ID + "\",\"version\":\"" + VERSION + "\"}").getBytes(StandardCharsets.UTF_8));
            zip.closeEntry();
            zip.putNextEntry(new ZipEntry("Dummy.class"));
            byte[] bytes = new byte[2048];
            // Fill with incompressible-ish predictable bytes to exercise a larger JAR.
            for(int i = 0; i < bytes.length; i++) bytes[i] = (byte)((i * 43) ^ (i >>> 3));
            zip.write(bytes);
            zip.closeEntry();
        }
        byte[] binary = output.toByteArray();
        if (binary.length < 1000) throw new AssertionError("Test ZIP too small");
        return binary;
    }
    static String sha(byte[] raw) throws Exception {
        StringBuilder b = new StringBuilder();
        for (byte item : MessageDigest.getInstance("SHA-256").digest(raw))
            b.append(String.format("%02x", item & 0xff));
        return b.toString();
    }
    static String manifest(KeyPair key, String url, String sha, int size) throws Exception {
        Map<String, String> map = Map.of(
            "release", "1", "version", VERSION, "url", url, "sha256", sha,
            "size", String.valueOf(size), "minecraft", "1.21.1", "mod_id", ID, "channel", "stable");
        StringBuilder canonical = new StringBuilder();
        for(String field : PrivateModUpdater.FIELDS)
            canonical.append(field).append('=').append(map.get(field)).append('\n');
        Signature s = Signature.getInstance("Ed25519");
        s.initSign(key.getPrivate());
        s.update(canonical.toString().getBytes(StandardCharsets.US_ASCII));
        return canonical + "signature=" + Base64.getEncoder().encodeToString(s.sign()) + "\n";
    }
    static String releaseJson(String manifest, String url, String sha, int size) {
        return JsonCodec.canonical(Map.of("ok", true, "releases", List.of(Map.of(
            "id", ID, "version", VERSION, "release", 1,
            "sha256", sha, "size", size, "url", url, "manifest", manifest))));
    }
    static void setMode(Path dir, String mode) throws Exception {
        Files.createDirectories(dir.resolve("config"));
        Files.writeString(dir.resolve("config/hype-bootstrap.properties"), "update_mode=" + mode + "\n");
    }
    public static void main(String[] args) throws Exception {
        KeyPair key = KeyPairGenerator.getInstance("Ed25519").generateKeyPair();
        KeyPair wrong = KeyPairGenerator.getInstance("Ed25519").generateKeyPair();
        byte[] jar = jar(); String sha = sha(jar);
        String url = PrivateModUpdater.API + "/mods/" + ID + "/" + sha + ".jar";
        String m = manifest(key, url, sha, jar.length);
        String json = releaseJson(m, url, sha, jar.length);
        Path dir = Files.createTempDirectory("hype06-private-test-");
        int[] calls = {0};
        PrivateModUpdater.Fetcher good = (requested, token, max) -> {
            calls[0]++;
            if (!"test-bearer".equals(token)) throw new AssertionError("Credential lost");
            if (requested.equals(PrivateModUpdater.API + "/releases")) return json.getBytes(StandardCharsets.UTF_8);
            if (requested.equals(url)) return jar;
            throw new AssertionError("Unexpected endpoint: " + requested);
        };
        check(PrivateModUpdater.stageAfterLogin(dir, null, key.getPublic(), good).offered() == 0,
              "OFF must remain OFF even without credentials");
        check(calls[0] == 0, "OFF must not use network");
        setMode(dir,"stage");
        denies(() -> PrivateModUpdater.stageAfterLogin(dir,"bad\rvalue",key.getPublic(), good), "header injection");
        check(calls[0] == 0, "invalid token must not use network");
        PrivateModUpdater.Result first = PrivateModUpdater.stageAfterLogin(dir,"test-bearer",key.getPublic(),good);
        check(first.staged() == 1 && first.offered() == 1, "valid signed release staged");
        check(calls[0] == 2, "list and binary requested");
        check(Files.exists(dir.resolve(".hype-private-staging/" + ID + "-" + sha + ".jar")), "staged file exists");
        check(PrivateModUpdater.stageAfterLogin(dir,"test-bearer",key.getPublic(),good).alreadyPresent() == 1,
              "unchanged release not downloaded again");
        check(calls[0] == 3, "re-checks entitlement list each time");
        denies(() -> PrivateModUpdater.readReleases(json.getBytes(StandardCharsets.UTF_8), wrong.getPublic()),
               "wrong Ed25519 key");
        String corrupt = releaseJson(m.replace("stable","beta"), url, sha, jar.length);
        denies(() -> PrivateModUpdater.readReleases(corrupt.getBytes(StandardCharsets.UTF_8),key.getPublic()),
               "modified signed manifest");
        String badUrl = "https://evil.example.com/steal";
        String badJson = releaseJson(m,badUrl,sha,jar.length);
        denies(() -> PrivateModUpdater.readReleases(badJson.getBytes(StandardCharsets.UTF_8),key.getPublic()),
               "different download host");
        String dup = JsonCodec.canonical(Map.of("ok",true,"releases",List.of(
            Map.of("id",ID,"version",VERSION,"release",1,"sha256",sha,"size",jar.length,"url",url,"manifest",m),
            Map.of("id",ID,"version",VERSION,"release",1,"sha256",sha,"size",jar.length,"url",url,"manifest",m))));
        denies(() -> PrivateModUpdater.readReleases(dup.getBytes(StandardCharsets.UTF_8),key.getPublic()),
               "duplicate mod IDs");
        String empty = JsonCodec.canonical(Map.of("ok",true,"releases",List.of()));
        check(PrivateModUpdater.readReleases(empty.getBytes(StandardCharsets.UTF_8),key.getPublic()).isEmpty(),
              "valid empty entitlements list");
        denies(() -> PrivateModUpdater.readReleases("{\"ok\":false}".getBytes(StandardCharsets.UTF_8),key.getPublic()),
               "unauthorized server response");
        byte[] altered = jar.clone(); altered[altered.length-1] ^= 1;
        PrivateModUpdater.Release r = PrivateModUpdater.readReleases(json.getBytes(StandardCharsets.UTF_8),key.getPublic()).get(0);
        denies(() -> PrivateModUpdater.validateJar(altered,r), "tampered binary");
        String blank = releaseJson(m.replace("channel=stable\n", "channel=stable\n\n"), url, sha, jar.length);
        denies(() -> PrivateModUpdater.readReleases(blank.getBytes(StandardCharsets.UTF_8), key.getPublic()),
               "unexpected manifest blank lines");
        Path unsafe = Files.createTempDirectory("hype06-symlink-");
        Path other = Files.createTempDirectory("hype06-outside-");
        try {
            Files.createSymbolicLink(unsafe.resolve(".hype-private-staging"), other);
            setMode(unsafe, "stage");
            denies(() -> PrivateModUpdater.stageAfterLogin(unsafe, "test-bearer", key.getPublic(), good),
                   "symlinked staging path");
        } catch (UnsupportedOperationException e) {
            // Symbolic links unsupported by this test platform.
        }
        setMode(dir,"after_exit");
        check(PrivateModUpdater.stageAfterLogin(dir,"test-bearer",key.getPublic(),good).staged() == 0,
              "AFTER_EXIT mode remains stage-only in 0.6");
        check(!Files.exists(dir.resolve("mods")), "mods directory untouched");
        System.out.println("PASS: " + passed + " isolated private-update assertions");
    }
}
