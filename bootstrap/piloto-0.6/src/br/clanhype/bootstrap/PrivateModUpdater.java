package br.clanhype.bootstrap;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.security.PublicKey;
import java.security.Signature;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Base64;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/**
 * Private HYPE release fetcher (0.6 pre-pilot). Stages but NEVER installs JARs.
 * HYPE Client must pass the short-lived Bearer token IN MEMORY after login.
 * No token, URL override, download URL, or private key is written to disk.
 */
public final class PrivateModUpdater {
    static final String ORIGIN = "https://clan-hype.onrender.com";
    static final String API = ORIGIN + "/api/hype/v1/updates";
    static final Set<String> IDS = Set.of(
        "hype_pokedex", "hype_breed_calculator", "hype_battlefield", "hype_battle_ai");
    static final List<String> FIELDS = List.of(
        "release", "version", "url", "sha256", "size", "minecraft", "mod_id", "channel");
    static final Pattern SHA = Pattern.compile("[a-f0-9]{64}");
    static final Pattern VERSION = Pattern.compile("[A-Za-z0-9._+-]{1,120}");
    static final long MAX_JAR = 10L * 1024 * 1024;
    static final int MAX_LIST = 128 * 1024;
    static final int MAX_MANIFEST = 16 * 1024;

    private PrivateModUpdater() { }

    public record Release(String id, String version, String sha256, long size,
                          int release, String url, String manifest) { }
    public record Result(int staged, int alreadyPresent, int offered) { }

    /** For offline, deterministic regression tests; never call with unsigned releases. */
    interface Fetcher {
        byte[] get(String url, String token, int maxBytes) throws Exception;
    }

    /** Public bridge for authenticated HYPE Client. Never call from pre-login startup. */
    public static Result stageAfterLogin(Path gameDir, String token) throws Exception {
        return stageAfterLogin(gameDir, token, CatalogVerifier.pinnedPublicKey(),
                               new OfficialFetcher());
    }

    static Result stageAfterLogin(Path gameDir, String token, PublicKey key, Fetcher fetcher)
            throws Exception {
        // OFF by default. AFTER_EXIT is intentionally staging ONLY in 0.6.
        UpdateMode mode = UpdateConfiguration.load(gameDir);
        if (mode == UpdateMode.OFF) return new Result(0, 0, 0);
        if (token == null || token.isBlank() || token.length() > 8192
                || token.indexOf('\r') >= 0 || token.indexOf('\n') >= 0) {
            throw new SecurityException("Authenticated HYPE Client session required");
        }
        Path staging = safeStaging(gameDir);
        byte[] raw = fetcher.get(API + "/releases", token, MAX_LIST);
        List<Release> releases = readReleases(raw, key);
        int staged = 0, present = 0;
        for (Release item : releases) {
            String fileName = item.id() + "-" + item.sha256() + ".jar";
            Path target = staging.resolve(fileName);
            if (Files.isSymbolicLink(target)) throw new SecurityException("Unsafe staged file");
            if (Files.exists(target, LinkOption.NOFOLLOW_LINKS)) {
                validateFile(target, item);
                present++;
                continue;
            }
            byte[] jar = fetcher.get(item.url(), token, Math.toIntExact(item.size()));
            validateJar(jar, item);
            Path temp = Files.createTempFile(staging, "hype-", ".part");
            try {
                Files.write(temp, jar);
                // CREATE_NEW semantics are not available for atomic move: never replace.
                if (Files.exists(target, LinkOption.NOFOLLOW_LINKS)) {
                    validateFile(target, item);
                    present++;
                    continue;
                }
                Files.move(temp, target, StandardCopyOption.ATOMIC_MOVE);
                staged++;
            } finally {
                Files.deleteIfExists(temp);
            }
        }
        return new Result(staged, present, releases.size());
    }

    static List<Release> readReleases(byte[] bytes, PublicKey key) throws Exception {
        if (bytes == null || bytes.length > MAX_LIST) throw new SecurityException("Oversized releases response");
        Object parsed = JsonCodec.read(new String(bytes, StandardCharsets.UTF_8));
        if (!(parsed instanceof Map<?,?> response) || !Boolean.TRUE.equals(response.get("ok"))) {
            throw new SecurityException("Private releases unavailable");
        }
        if (!(response.get("releases") instanceof List<?> items) || items.size() > 4) {
            throw new SecurityException("Invalid private releases response");
        }
        List<Release> out = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        for (Object obj : items) {
            if (!(obj instanceof Map<?, ?> map)) throw new SecurityException("Invalid release record");
            String id = string(map.get("id")), version = string(map.get("version"));
            String sha = string(map.get("sha256")), url = string(map.get("url"));
            String manifest = string(map.get("manifest"));
            long size = number(map.get("size"));
            long seq = number(map.get("release"));
            if (!IDS.contains(id) || !seen.add(id)
                    || !VERSION.matcher(version).matches() || !SHA.matcher(sha).matches()
                    || size < 1000 || size > MAX_JAR || seq < 1 || seq > 999999999L) {
                throw new SecurityException("Invalid release metadata");
            }
            String expected = API + "/mods/" + id + "/" + sha + ".jar";
            if (!expected.equals(url)) throw new SecurityException("Unexpected private download URL");
            Release release = new Release(id, version, sha, size, (int)seq, url, manifest);
            verifyManifest(release, key);
            out.add(release);
        }
        return List.copyOf(out);
    }

    static void verifyManifest(Release release, PublicKey key) throws Exception {
        if (release.manifest() == null || release.manifest().isEmpty()
                || release.manifest().length() > MAX_MANIFEST) {
            throw new SecurityException("Missing signed manifest");
        }
        // ASCII only, exactly nine distinct fields, no comments, no escapes.
        if (!StandardCharsets.US_ASCII.newEncoder().canEncode(release.manifest()))
            throw new SecurityException("Manifest must be ASCII");
        Map<String,String> values = new HashMap<>();
        String[] lines = release.manifest().split("\n", -1);
        for (int i = 0; i < lines.length; i++) {
            String line = lines[i];
            if (line.isEmpty() && i == lines.length - 1) continue;
            if (line.isEmpty()) throw new SecurityException("Blank manifest line");
            int split = line.indexOf('=');
            if (split <= 0 || split == line.length()-1) throw new SecurityException("Invalid manifest line");
            String k = line.substring(0, split), v = line.substring(split+1);
            if ((!FIELDS.contains(k) && !k.equals("signature")) || values.putIfAbsent(k, v) != null
                    || v.length() > 2000 || !v.equals(v.trim()) || v.indexOf('\\') >= 0
                    || v.indexOf('\r') >= 0 || v.indexOf('\t') >= 0) {
                throw new SecurityException("Invalid signed manifest field");
            }
        }
        if (values.size() != 9 || !values.keySet().containsAll(FIELDS)
                || !values.containsKey("signature")) throw new SecurityException("Missing signed fields");
        Map<String,String> expected = Map.of(
            "release", String.valueOf(release.release()), "version", release.version(),
            "url", release.url(), "sha256", release.sha256(),
            "size", String.valueOf(release.size()), "minecraft", "1.21.1",
            "mod_id", release.id(), "channel", "stable");
        if (!FIELDS.stream().allMatch(k -> expected.get(k).equals(values.get(k))))
            throw new SecurityException("Manifest/metadata mismatch");
        StringBuilder canonical = new StringBuilder();
        for (String k : FIELDS) canonical.append(k).append('=').append(values.get(k)).append('\n');
        byte[] sig;
        try { sig = Base64.getDecoder().decode(values.get("signature")); }
        catch (IllegalArgumentException e) { throw new SecurityException("Invalid signature base64", e); }
        if (sig.length != 64) throw new SecurityException("Invalid signature size");
        Signature verifier = Signature.getInstance("Ed25519");
        verifier.initVerify(key);
        verifier.update(canonical.toString().getBytes(StandardCharsets.US_ASCII));
        if (!verifier.verify(sig)) throw new SecurityException("Manifest Ed25519 signature rejected");
    }

    static Path safeStaging(Path gameDir) throws Exception {
        Path base = gameDir.toAbsolutePath().normalize();
        Path target = base.resolve(".hype-private-staging");
        if (Files.isSymbolicLink(base) || Files.isSymbolicLink(target))
            throw new SecurityException("Symlink in staging path");
        if (!Files.isDirectory(base, LinkOption.NOFOLLOW_LINKS))
            throw new SecurityException("Missing Minecraft directory");
        Files.createDirectories(target);
        if (!Files.isDirectory(target, LinkOption.NOFOLLOW_LINKS) || Files.isSymbolicLink(target))
            throw new SecurityException("Invalid staging directory");
        return target;
    }

    static void validateFile(Path path, Release release) throws Exception {
        if (!Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS)
                || Files.size(path) != release.size()) throw new SecurityException("Damaged staged file");
        validateJar(Files.readAllBytes(path), release);
    }

    static void validateJar(byte[] bytes, Release release) throws Exception {
        if (bytes == null || bytes.length != release.size()) throw new SecurityException("Size mismatch");
        byte[] hash = MessageDigest.getInstance("SHA-256").digest(bytes);
        StringBuilder hex = new StringBuilder();
        for (byte b : hash) hex.append(String.format("%02x", b & 0xff));
        if (!hex.toString().equals(release.sha256())) throw new SecurityException("SHA-256 mismatch");
        boolean found = false;
        try (ZipInputStream zip = new ZipInputStream(new ByteArrayInputStream(bytes))) {
            ZipEntry entry;
            int entries = 0;
            while ((entry = zip.getNextEntry()) != null) {
                if (++entries > 50000) throw new SecurityException("Invalid JAR entry count");
                if ("fabric.mod.json".equals(entry.getName())) {
                    if (entry.getSize() > 8192) throw new SecurityException("Oversized Fabric metadata");
                    byte[] meta = zip.readNBytes(8193);
                    if (meta.length > 8192) throw new SecurityException("Oversized Fabric metadata");
                    Object decoded = JsonCodec.read(new String(meta, StandardCharsets.UTF_8));
                    if (!(decoded instanceof Map<?,?> m)
                            || !release.id().equals(m.get("id"))
                            || !release.version().equals(m.get("version"))) {
                        throw new SecurityException("Fabric metadata mismatch");
                    }
                    found = true;
                    break;
                }
            }
        }
        if (!found) throw new SecurityException("Missing Fabric metadata");
    }

    private static String string(Object value) {
        if (!(value instanceof String s)) throw new SecurityException("Expected release string");
        return s;
    }
    private static long number(Object value) {
        if (!(value instanceof Long n)) throw new SecurityException("Expected integer release field");
        return n;
    }

    static final class OfficialFetcher implements Fetcher {
        private final HttpClient client = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(5))
            .followRedirects(HttpClient.Redirect.NEVER).build();

        @Override
        public byte[] get(String url, String token, int maxBytes) throws Exception {
            // Guard EVERY request against SSRF, redirects and credentials leakage.
            URI u = URI.create(url);
            if (!"https".equals(u.getScheme()) || !"clan-hype.onrender.com".equals(u.getHost())
                    || u.getPort() != -1 || u.getUserInfo() != null || u.getFragment() != null
                    || u.getRawQuery() != null || !url.startsWith(API + "/"))
                throw new SecurityException("Non-official private download endpoint");
            HttpRequest request = HttpRequest.newBuilder(u)
                .timeout(Duration.ofSeconds(25))
                .header("Authorization", "Bearer " + token)
                .header("Cache-Control", "no-store").GET().build();
            HttpResponse<InputStream> response = client.send(request, HttpResponse.BodyHandlers.ofInputStream());
            try (InputStream in = response.body()) {
                if (response.statusCode() != 200) throw new IOException("HYPE private endpoint status " + response.statusCode());
                byte[] data = in.readNBytes(Math.addExact(maxBytes, 1));
                if (data.length > maxBytes) throw new IOException("Oversized HYPE response");
                return data;
            }
        }
    }
}
