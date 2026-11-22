package br.clanhype.bootstrap;

import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.security.PublicKey;
import java.util.function.BooleanSupplier;

/**
 * Experimental, offline FIRST installation transaction ONLY.
 * NOT connected to the Fabric entrypoint, login bridge or game shutdown.
 * Never updates an existing JAR and never publishes or downloads a mod.
 * A future launcher must authoritatively prove game exit and permission.
 */
public final class PrivateFirstInstallTransaction {
    private PrivateFirstInstallTransaction() { }

    enum Outcome { INSTALLED, EXACT_JAR_ALREADY_PRESENT }
    @FunctionalInterface interface Fault { void afterNewFileCreated() throws Exception; }

    static Outcome apply(Path gameDir, PrivateModUpdater.Release release,
                         PublicKey verificationKey, BooleanSupplier gameExited,
                         BooleanSupplier permissionStillGranted, Fault fault) throws Exception {
        if (gameExited == null || permissionStillGranted == null || fault == null)
            throw new SecurityException("Missing post-exit safety checks");
        if (UpdateConfiguration.load(gameDir) != UpdateMode.AFTER_EXIT)
            throw new SecurityException("Explicit after_exit opt-in required");
        verifyGate(gameExited, permissionStillGranted);
        PrivateInstallPlanner.Plan plan =
            PrivateInstallPlanner.inspect(gameDir, release, verificationKey);
        if (plan.action() == PrivateInstallPlanner.Action.CONFLICT)
            throw new SecurityException("Existing manually managed or duplicate Fabric mod");
        if (plan.action() == PrivateInstallPlanner.Action.ALREADY_INSTALLED)
            return Outcome.EXACT_JAR_ALREADY_PRESENT;

        Path game = gameDir.toAbsolutePath().normalize();
        Path managed = game.resolve(".hype-private-managed");
        Path mods = game.resolve("mods");
        requireOrCreateDirectory(managed);
        // State is created only for a FIRST install; a preexisting marker is never adopted.
        Path state = managed.resolve(release.id() + ".state");
        if (Files.exists(state, LinkOption.NOFOLLOW_LINKS))
            throw new SecurityException("Existing managed state requires separate upgrade flow");
        requireOrCreateDirectory(mods);
        String filename = "hype-" + release.id() + "-" + release.sha256() + ".jar";
        Path target = mods.resolve(filename);
        if (Files.exists(target, LinkOption.NOFOLLOW_LINKS))
            throw new SecurityException("Refusing to overwrite existing target");
        Path temporary = Files.createTempFile(mods, ".hype-private-install-", ".part");
        boolean linked = false;
        boolean marked = false;
        Path tempState = null;
        try {
            Files.copy(plan.stagedJar(), temporary, StandardCopyOption.REPLACE_EXISTING);
            PrivateModUpdater.validateFile(temporary, release);
            // Recheck consent and permissions immediately before publication.
            verifyGate(gameExited, permissionStillGranted);
            PrivateInstallPlanner.Plan current =
                PrivateInstallPlanner.inspect(game, release, verificationKey);
            if (current.action() != PrivateInstallPlanner.Action.READY_FOR_FIRST_INSTALL)
                throw new SecurityException("Mod directory changed during preparation");
            // Exclusive, atomic creation; createLink fails if target exists.
            // Unsupported filesystems fail closed (no fallback overwrite).
            Files.createLink(target, temporary);
            linked = true;
            fault.afterNewFileCreated(); // Test-only fault injection before state commit.
            verifyGate(gameExited, permissionStillGranted);
            PrivateModUpdater.validateFile(target, release);
            String marker = "sha256=" + release.sha256() + "\nfile=" + filename + "\n";
            tempState = Files.createTempFile(managed, ".hype-state-", ".part");
            Files.writeString(tempState, marker, StandardOpenOption.TRUNCATE_EXISTING,
                              StandardOpenOption.WRITE);
            // State appears atomically and exclusively, never half-written.
            Files.createLink(state, tempState);
            marked = true;
            return Outcome.INSTALLED;
        } catch (Exception failure) {
            // The only file this transaction ever removes is its own new target.
            if (linked) {
                try { Files.deleteIfExists(target); }
                catch (Exception cleanup) { failure.addSuppressed(cleanup); }
            }
            if (marked) {
                try { Files.deleteIfExists(state); }
                catch (Exception cleanup) { failure.addSuppressed(cleanup); }
            }
            throw failure;
        } finally {
            Files.deleteIfExists(temporary);
            if (tempState != null) Files.deleteIfExists(tempState);
        }
    }

    private static void verifyGate(BooleanSupplier exited, BooleanSupplier permission) {
        if (!exited.getAsBoolean()) throw new SecurityException("Minecraft still running");
        if (!permission.getAsBoolean())
            throw new SecurityException("Live private permission not verified");
        if (Thread.currentThread().isInterrupted())
            throw new SecurityException("Post-exit install cancelled");
    }

    private static void requireOrCreateDirectory(Path dir) throws Exception {
        if (Files.isSymbolicLink(dir)) throw new SecurityException("Symlinked install directory");
        if (Files.exists(dir, LinkOption.NOFOLLOW_LINKS)) {
            if (!Files.isDirectory(dir, LinkOption.NOFOLLOW_LINKS))
                throw new SecurityException("Unsafe install directory");
        } else {
            Files.createDirectory(dir);
        }
        if (Files.isSymbolicLink(dir) ||
                !Files.isDirectory(dir, LinkOption.NOFOLLOW_LINKS))
            throw new SecurityException("Unsafe install path");
    }
}
