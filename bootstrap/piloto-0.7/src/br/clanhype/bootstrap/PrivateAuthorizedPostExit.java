package br.clanhype.bootstrap;

import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.security.PublicKey;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.function.BooleanSupplier;

/**
 * Post-exit coordinator for HYPE's four PRIVATE signed mods.
 *
 * Deliberately NOT a Fabric entrypoint and NOT launched by the current Bootstrap:
 * an independently tested external agent still needs to supply proof that the
 * Minecraft process has exited and keep a short-lived login token IN MEMORY.
 * This class never writes tokens or signs/publishes original JARs.
 */
public final class PrivateAuthorizedPostExit {
    private PrivateAuthorizedPostExit() { }

    public enum Outcome { FIRST_INSTALLED, UPDATED, ALREADY_CURRENT }
    public record Installed(String moduleId, Outcome outcome) { }

    /** Future external-agent API; requires explicit after_exit opt-in. */
    public static List<Installed> apply(
            Path gameDir, String bearer, List<PrivateModUpdater.Release> staged,
            BooleanSupplier gameExited) throws Exception {
        return apply(gameDir, bearer, staged, gameExited,
                CatalogVerifier.pinnedPublicKey(), new PrivateModUpdater.OfficialFetcher());
    }

    /** Injectable only for isolated tests; authorization must always be re-queried. */
    static List<Installed> apply(
            Path gameDir, String bearer, List<PrivateModUpdater.Release> staged,
            BooleanSupplier gameExited, PublicKey publicKey,
            PrivateModUpdater.Fetcher fetcher) throws Exception {
        if (gameDir == null || staged == null || gameExited == null
                || publicKey == null || fetcher == null)
            throw new SecurityException("Missing post-exit inputs");
        if (UpdateConfiguration.load(gameDir) != UpdateMode.AFTER_EXIT)
            throw new SecurityException("Opt-in after_exit required");
        if (bearer == null || bearer.isBlank() || bearer.length() > 8192
                || bearer.indexOf('\r') >= 0 || bearer.indexOf('\n') >= 0)
            throw new SecurityException("HYPE account session required");
        if (!gameExited.getAsBoolean())
            throw new SecurityException("Minecraft is still running");

        Set<String> seen = new HashSet<>();
        // Verify ALL offered manifests before any installation can start.
        for (PrivateModUpdater.Release release : staged) {
            if (release == null || !PrivateModUpdater.IDS.contains(release.id())
                    || !seen.add(release.id()))
                throw new SecurityException("Invalid or duplicated HYPE module");
            PrivateModUpdater.verifyManifest(release, publicKey);
        }

        Path root = gameDir.toAbsolutePath().normalize();
        Path managed = root.resolve(".hype-private-managed");
        if (Files.isSymbolicLink(root) || Files.isSymbolicLink(managed))
            throw new SecurityException("Unsafe managed HYPE directory");
        List<Installed> results = new ArrayList<>();
        for (PrivateModUpdater.Release release : staged) {
            // Fail closed on 401, 403, empty listing, network failure, altered
            // signature or a server-side revocation. No offline permission cache.
            BooleanSupplier stillAuthorized = () -> {
                if (!gameExited.getAsBoolean() || Thread.currentThread().isInterrupted())
                    return false;
                try {
                    byte[] response = fetcher.get(PrivateModUpdater.API + "/releases",
                                                  bearer, PrivateModUpdater.MAX_LIST);
                    for (PrivateModUpdater.Release authorized :
                            PrivateModUpdater.readReleases(response, publicKey)) {
                        if (sameExactRelease(release, authorized)) return true;
                    }
                } catch (Exception unavailable) {
                    return false;
                }
                return false;
            };
            if (!stillAuthorized.getAsBoolean())
                throw new SecurityException("Live release authorization was not confirmed");

            Path state = managed.resolve(release.id() + ".state");
            if (Files.isSymbolicLink(state))
                throw new SecurityException("Symlinked managed state");
            if (Files.exists(state, LinkOption.NOFOLLOW_LINKS)) {
                PrivateManagedUpgrade.Outcome outcome = PrivateManagedUpgrade.upgrade(
                        root, release, publicKey, gameExited, stillAuthorized, () -> { });
                results.add(new Installed(release.id(),
                    outcome == PrivateManagedUpgrade.Outcome.UPDATED
                            ? Outcome.UPDATED : Outcome.ALREADY_CURRENT));
            } else {
                PrivateFirstInstallTransaction.Outcome outcome = PrivateFirstInstallTransaction.apply(
                        root, release, publicKey, gameExited, stillAuthorized, () -> { });
                results.add(new Installed(release.id(),
                    outcome == PrivateFirstInstallTransaction.Outcome.INSTALLED
                            ? Outcome.FIRST_INSTALLED : Outcome.ALREADY_CURRENT));
            }
        }
        return List.copyOf(results);
    }

    private static boolean sameExactRelease(
            PrivateModUpdater.Release expected, PrivateModUpdater.Release live) {
        return expected.id().equals(live.id())
                && expected.release() == live.release()
                && expected.version().equals(live.version())
                && expected.sha256().equals(live.sha256())
                && expected.size() == live.size()
                && expected.url().equals(live.url())
                && expected.manifest().equals(live.manifest());
    }
}
