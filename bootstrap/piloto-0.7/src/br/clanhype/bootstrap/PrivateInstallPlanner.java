package br.clanhype.bootstrap;

import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.PublicKey;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/**
 * Read-only preparation for a future automatic after-exit installer.
 * No JARs are copied, moved, deleted or installed by this class.
 *
 * An already installed HYPE JAR with a different SHA is always a CONFLICT:
 * never silently replace a manually managed mod.
 */
public final class PrivateInstallPlanner {
    private PrivateInstallPlanner() { }

    public enum Action { READY_FOR_FIRST_INSTALL, ALREADY_INSTALLED, CONFLICT }

    public record Plan(PrivateModUpdater.Release release, Action action,
                       String note, Path stagedJar) { }

    public static Plan inspect(Path gameDir, PrivateModUpdater.Release release,
                               PublicKey verificationKey) throws Exception {
        if (release == null || !PrivateModUpdater.IDS.contains(release.id()))
            throw new SecurityException("Unsupported private HYPE module");
        PrivateModUpdater.verifyManifest(release, verificationKey);
        Path root = gameDir.toAbsolutePath().normalize();
        if (!Files.isDirectory(root, LinkOption.NOFOLLOW_LINKS) || Files.isSymbolicLink(root))
            throw new SecurityException("Unsafe Minecraft root directory");
        Path staging = root.resolve(".hype-private-staging");
        if (Files.isSymbolicLink(staging) ||
            !Files.isDirectory(staging, LinkOption.NOFOLLOW_LINKS))
            throw new SecurityException("Missing safe HYPE staging directory");
        Path staged = staging.resolve(release.id() + "-" + release.sha256() + ".jar");
        if (Files.isSymbolicLink(staged))
            throw new SecurityException("Symlinked staged file");
        PrivateModUpdater.validateFile(staged, release);

        Path mods = root.resolve("mods");
        if (Files.isSymbolicLink(mods) ||
            (Files.exists(mods, LinkOption.NOFOLLOW_LINKS)
                && !Files.isDirectory(mods, LinkOption.NOFOLLOW_LINKS)))
            throw new SecurityException("Unsafe mods directory");
        if (!Files.exists(mods, LinkOption.NOFOLLOW_LINKS)) {
            return new Plan(release, Action.READY_FOR_FIRST_INSTALL,
                            "No installed mod with this Fabric ID", staged);
        }

        List<Path> found = new ArrayList<>();
        try (DirectoryStream<Path> jars = Files.newDirectoryStream(mods, "*.jar")) {
            int scanned = 0;
            for (Path candidate : jars) {
                if (++scanned > 2000) throw new SecurityException("Too many installed JARs");
                if (Files.isSymbolicLink(candidate))
                    throw new SecurityException("Symbolic link in mods directory");
                if (!Files.isRegularFile(candidate, LinkOption.NOFOLLOW_LINKS))
                    throw new SecurityException("Invalid item in mods directory");
                if (release.id().equals(readFabricModId(candidate))) found.add(candidate);
            }
        }
        if (found.isEmpty()) {
            return new Plan(release, Action.READY_FOR_FIRST_INSTALL,
                            "No installed mod with this Fabric ID", staged);
        }
        if (found.size() != 1)
            return new Plan(release, Action.CONFLICT, "Duplicate Fabric mod ID", staged);
        Path existing = found.get(0);
        if (Files.size(existing) != release.size())
            return new Plan(release, Action.CONFLICT, "Existing mod differs from approved release", staged);
        if (!sameSha(existing, release.sha256()))
            return new Plan(release, Action.CONFLICT,
                            "Existing mod was not verified as this release", staged);
        return new Plan(release, Action.ALREADY_INSTALLED,
                        "Existing exact SHA-256 matches approved release", staged);
    }

    private static String readFabricModId(Path file) throws Exception {
        if (Files.size(file) > 100L * 1024 * 1024)
            throw new SecurityException("Oversized installed JAR");
        try (ZipFile zip = new ZipFile(file.toFile())) {
            ZipEntry meta = zip.getEntry("fabric.mod.json");
            if (meta == null) return "";
            if (meta.getSize() > 8192) throw new SecurityException("Oversized Fabric metadata");
            try (InputStream in = zip.getInputStream(meta)) {
                byte[] contents = in.readNBytes(8193);
                if (contents.length > 8192) throw new SecurityException("Oversized Fabric metadata");
                Object parsed = JsonCodec.read(new String(contents, StandardCharsets.UTF_8));
                if (!(parsed instanceof Map<?, ?> obj) || !(obj.get("id") instanceof String id))
                    throw new SecurityException("Invalid Fabric ID");
                return id;
            }
        } catch (java.util.zip.ZipException invalidJar) {
            // An unrelated malformed JAR cannot be safely classified;
            // fail closed rather than risk installing a duplicate ID.
            throw new SecurityException("Unrecognized damaged mod JAR", invalidJar);
        }
    }

    private static boolean sameSha(Path path, String expected) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream stream = Files.newInputStream(path)) {
            byte[] chunk = new byte[64 * 1024];
            int count;
            while ((count = stream.read(chunk)) != -1) digest.update(chunk, 0, count);
        }
        StringBuilder actual = new StringBuilder(64);
        for (byte b : digest.digest()) actual.append(String.format("%02x", b & 255));
        return actual.toString().equals(expected);
    }
}
