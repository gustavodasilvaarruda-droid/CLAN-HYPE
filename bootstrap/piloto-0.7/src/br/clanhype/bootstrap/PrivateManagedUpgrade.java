package br.clanhype.bootstrap;

import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.security.PublicKey;
import java.util.function.BooleanSupplier;

/**
 * Isolated, offline-only upgrade transaction for mods previously installed by
 * the HYPE Bootstrap. DO NOT invoke on Fabric entrypoint or ship as an agent.
 * The caller's gate is deliberately NOT wired to an authorization server yet.
 */
public final class PrivateManagedUpgrade {
    private PrivateManagedUpgrade() {}
    public enum Outcome { UPDATED, ALREADY_INSTALLED }
    @FunctionalInterface public interface Fault { void afterNewJarCreated() throws Exception; }

    private record Owned(String hash, String name) { }
    private static final String PREFIX = "hype-";
    private static final LinkOption NOFOLLOW = LinkOption.NOFOLLOW_LINKS;

    static Outcome upgrade(Path gameDir, PrivateModUpdater.Release release, PublicKey key,
                           BooleanSupplier gameExited, BooleanSupplier liveAuthorized, Fault fault)
                           throws Exception {
        if (release == null || key == null || gameExited == null || liveAuthorized == null || fault == null)
            throw new SecurityException("Missing approved upgrade inputs");
        if (UpdateConfiguration.load(gameDir) != UpdateMode.AFTER_EXIT)
            throw new SecurityException("Explicit after_exit mode required");
        gate(gameExited, liveAuthorized);
        // Read-only preflight validates Ed25519 signed manifest and staged real JAR.
        PrivateInstallPlanner.Plan plan = PrivateInstallPlanner.inspect(gameDir, release, key);
        Path root = gameDir.toAbsolutePath().normalize();
        Path mods = root.resolve("mods");
        Path managed = root.resolve(".hype-private-managed");
        Path backups = root.resolve(".hype-private-backups");
        requireDir(mods);
        requireDir(managed);
        Path state = managed.resolve(release.id() + ".state");
        Owned owned = readOwned(state, release.id());
        // Interrupted transactions must be recovered by the external launcher
        // BEFORE we consider an otherwise matching installed SHA as current.
        Path pending = managed.resolve(release.id() + ".pending");
        if (Files.exists(pending, NOFOLLOW))
            throw new SecurityException("Interrupted prior update needs recovery");
        Path oldJar = mods.resolve(owned.name());
        requireFile(oldJar);
        if (!hashMatches(oldJar, owned.hash()) ||
            !release.id().equals(PrivateInstallPlanner.readFabricModId(oldJar)))
            throw new SecurityException("Previous managed JAR was modified");
        if (plan.action() == PrivateInstallPlanner.Action.ALREADY_INSTALLED) {
            if (!owned.hash().equals(release.sha256()))
                throw new SecurityException("Unowned duplicate JAR detected");
            return Outcome.ALREADY_INSTALLED;
        }
        if (owned.hash().equals(release.sha256()))
            throw new SecurityException("Managed state already claims offered release");
        // All same-ID JARs must be exactly the ONE owned file.
        try (var stream = Files.newDirectoryStream(mods, "*.jar")) {
            int inspected = 0;
            for (Path entry : stream) {
                if (++inspected > 2000) throw new SecurityException("Too many installed JARs");
                requireFile(entry);
                if (release.id().equals(PrivateInstallPlanner.readFabricModId(entry))
                        && !entry.equals(oldJar))
                    throw new SecurityException("Duplicate or manually installed Fabric mod ID");
            }
        }
        requireOrCreateDir(backups);
        Path newJar = mods.resolve(filename(release.id(), release.sha256()));
        if (Files.exists(newJar, NOFOLLOW)) throw new SecurityException("Target JAR already exists");
        Path lockFile = managed.resolve(".updater-lock");
        if (Files.isSymbolicLink(lockFile)) throw new SecurityException("Unsafe lock");
        try (FileChannel channel = FileChannel.open(lockFile, StandardOpenOption.CREATE,
                                                   StandardOpenOption.WRITE);
             FileLock lock = channel.tryLock()) {
            if (lock == null) throw new SecurityException("Another updater is running");
            // An exclusive copy of the old verified file is retained for rollback.
            Path backup = backups.resolve(filename(release.id(), owned.hash()));
            if (Files.exists(backup, NOFOLLOW)) {
                requireFile(backup);
                if (!hashMatches(backup, owned.hash()))
                    throw new SecurityException("Existing rollback backup is untrusted");
            } else {
                Path tempBackup = Files.createTempFile(backups, ".backup-", ".part");
                try {
                    Files.copy(oldJar, tempBackup, StandardCopyOption.REPLACE_EXISTING);
                    if (!hashMatches(tempBackup, owned.hash()))
                        throw new SecurityException("Backup verification failed");
                    Files.createLink(backup, tempBackup); // no overwrite or fallback
                } finally { Files.deleteIfExists(tempBackup); }
            }
            gate(gameExited, liveAuthorized);
            String journal = "old=" + owned.hash() + "\nnew=" + release.sha256() + "\n";
            Path journalTmp = Files.createTempFile(managed, ".journal-", ".part");
            try {
                Files.writeString(journalTmp, journal);
                Files.createLink(pending, journalTmp);
            } finally { Files.deleteIfExists(journalTmp); }
            boolean newCreated = false;
            boolean stateChanged = false;
            try {
                gate(gameExited, liveAuthorized);
                // Atomic exclusive link, no file overwrite; old remains until commit.
                Files.createLink(newJar, plan.stagedJar());
                newCreated = true;
                PrivateModUpdater.validateFile(newJar, release);
                fault.afterNewJarCreated();
                gate(gameExited, liveAuthorized);
                Path stateTemp = Files.createTempFile(managed, ".state-", ".part");
                try {
                    Files.writeString(stateTemp,
                        "sha256=" + release.sha256() + "\nfile=" + newJar.getFileName() + "\n");
                    // The state marker changes atomically; pending journal persists until done.
                    Files.move(stateTemp, state, StandardCopyOption.ATOMIC_MOVE,
                               StandardCopyOption.REPLACE_EXISTING);
                    stateChanged = true;
                } finally { Files.deleteIfExists(stateTemp); }
                // Keep all checks before deleting the known-owned former version.
                gate(gameExited, liveAuthorized);
                if (!hashMatches(oldJar, owned.hash()))
                    throw new SecurityException("Old JAR changed during transaction");
                Files.delete(oldJar);
                Files.delete(pending);
                return Outcome.UPDATED;
            } catch (Exception failure) {
                // Never touch any file not verified as created/managed by this transaction.
                try {
                    if (stateChanged) restoreState(managed, state, owned);
                    if (newCreated && Files.exists(newJar, NOFOLLOW)) {
                        if (!hashMatches(newJar, release.sha256()))
                            throw new SecurityException("New JAR changed; preserve recovery journal");
                        Files.delete(newJar);
                    }
                    if (!Files.exists(oldJar, NOFOLLOW)) {
                        if (hashMatches(backup, owned.hash())) Files.createLink(oldJar, backup);
                        else throw new SecurityException("Rollback backup missing");
                    }
                    if (!hashMatches(oldJar, owned.hash()))
                        throw new SecurityException("Rollback old JAR mismatch");
                    Files.deleteIfExists(pending);
                } catch (Exception rollback) {
                    // Leave pending journal for the external pre-launch recovery agent.
                    failure.addSuppressed(rollback);
                }
                throw failure;
            }
        }
    }

    /**
     * Recover an interrupted upgrade BEFORE the next Fabric startup.
     * Must be invoked by a separately tested external launcher/agent, NEVER
     * by Fabric's client entrypoint (which runs after mod discovery).
     * Leaves the journal untouched if any integrity check fails.
     */
    static boolean recoverPending(Path gameDir, String id, BooleanSupplier gameExited) throws Exception {
        if (gameExited == null || !gameExited.getAsBoolean())
            throw new SecurityException("Minecraft still running; recovery denied");
        if (!PrivateModUpdater.IDS.contains(id))
            throw new SecurityException("Unknown private mod");
        Path root = gameDir.toAbsolutePath().normalize();
        requireDir(root);
        Path mods = root.resolve("mods");
        Path managed = root.resolve(".hype-private-managed");
        Path backups = root.resolve(".hype-private-backups");
        requireDir(mods);
        requireDir(managed);
        Path pending = managed.resolve(id + ".pending");
        if (!Files.exists(pending, NOFOLLOW)) return false;
        requireFile(pending);
        if (Files.size(pending) > 256) throw new SecurityException("Oversized journal");
        String[] lines = Files.readString(pending).split("\n", -1);
        if (lines.length != 3 || !lines[2].isEmpty() ||
            !lines[0].startsWith("old=") || !lines[1].startsWith("new="))
            throw new SecurityException("Invalid recovery journal");
        String oldHash = lines[0].substring(4), newHash = lines[1].substring(4);
        Path oldJar = mods.resolve(filename(id, oldHash));
        Path newJar = mods.resolve(filename(id, newHash));
        if (oldHash.equals(newHash)) throw new SecurityException("Invalid same-version journal");
        Path backup = backups.resolve(filename(id, oldHash));
        requireFile(backup);
        if (!hashMatches(backup, oldHash)) throw new SecurityException("Corrupt recovery backup");
        Path state = managed.resolve(id + ".state");
        Owned current = readOwned(state, id);
        if (!current.hash().equals(oldHash) && !current.hash().equals(newHash))
            throw new SecurityException("Managed state changed since journal");
        Path lockFile = managed.resolve(".updater-lock");
        if (Files.isSymbolicLink(lockFile)) throw new SecurityException("Unsafe recovery lock");
        try (FileChannel channel = FileChannel.open(lockFile, StandardOpenOption.CREATE,
                                                   StandardOpenOption.WRITE);
             FileLock lock = channel.tryLock()) {
            if (lock == null) throw new SecurityException("Updater busy");
            if (Files.exists(oldJar, NOFOLLOW)) {
                requireFile(oldJar);
                if (!hashMatches(oldJar, oldHash))
                    throw new SecurityException("Old JAR modified; refusing recovery");
            } else Files.createLink(oldJar, backup);
            if (Files.exists(newJar, NOFOLLOW)) {
                requireFile(newJar);
                if (!hashMatches(newJar, newHash))
                    throw new SecurityException("Unrecognized new file during recovery");
                Files.delete(newJar);
            }
            restoreState(managed, state, new Owned(oldHash, filename(id, oldHash)));
            Files.delete(pending);
            return true;
        }
    }

    private static void restoreState(Path managed, Path state, Owned old) throws Exception {
        Path tmp = Files.createTempFile(managed, ".rollback-state-", ".part");
        try {
            Files.writeString(tmp, "sha256=" + old.hash() + "\nfile=" + old.name() + "\n");
            Files.move(tmp, state, StandardCopyOption.ATOMIC_MOVE,
                       StandardCopyOption.REPLACE_EXISTING);
        } finally { Files.deleteIfExists(tmp); }
    }
    private static String filename(String id, String hash) {
        if (!PrivateModUpdater.IDS.contains(id) || !PrivateModUpdater.SHA.matcher(hash).matches())
            throw new SecurityException("Invalid HYPE owned filename");
        return PREFIX + id + "-" + hash + ".jar";
    }
    private static Owned readOwned(Path state, String id) throws Exception {
        requireFile(state);
        if (Files.size(state) > 256) throw new SecurityException("Invalid managed marker size");
        String[] lines = Files.readString(state).split("\n", -1);
        if (lines.length != 3 || !lines[2].isEmpty()
                || !lines[0].startsWith("sha256=") || !lines[1].startsWith("file="))
            throw new SecurityException("Invalid managed marker");
        String hash = lines[0].substring(7);
        String file = lines[1].substring(5);
        if (!file.equals(filename(id, hash)))
            throw new SecurityException("Marker does not identify a Bootstrap-owned JAR");
        return new Owned(hash, file);
    }
    private static boolean hashMatches(Path file, String expected) throws Exception {
        if (!Files.isRegularFile(file, NOFOLLOW) || Files.isSymbolicLink(file)) return false;
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (var in = Files.newInputStream(file)) {
            byte[] buf = new byte[65536]; int n;
            while ((n = in.read(buf)) != -1) digest.update(buf, 0, n);
        }
        StringBuilder hex = new StringBuilder();
        for (byte b : digest.digest()) hex.append(String.format("%02x", b & 255));
        return hex.toString().equals(expected);
    }
    private static void gate(BooleanSupplier exit, BooleanSupplier permission) {
        if (!exit.getAsBoolean() || !permission.getAsBoolean()
                || Thread.currentThread().isInterrupted())
            throw new SecurityException("Game exit / live permission not confirmed");
    }
    private static void requireFile(Path file) {
        if (Files.isSymbolicLink(file) || !Files.isRegularFile(file, NOFOLLOW))
            throw new SecurityException("Missing or unsafe HYPE managed file");
    }
    private static void requireDir(Path path) {
        if (Files.isSymbolicLink(path) || !Files.isDirectory(path, NOFOLLOW))
            throw new SecurityException("Missing or unsafe HYPE directory");
    }
    private static void requireOrCreateDir(Path path) throws Exception {
        if (Files.exists(path, NOFOLLOW)) requireDir(path);
        else Files.createDirectory(path);
    }
}
