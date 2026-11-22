package br.clanhype.bootstrap;

import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/** Read-only installation-planning checks using the owner's protected Pokédex. */
public final class PrivateInstallPlannerTest {
    static int passed;

    static void check(boolean ok, String message) {
        if (!ok) throw new AssertionError(message);
        passed++;
    }

    interface Work { void run() throws Exception; }
    static void rejects(Work work) throws Exception {
        try { work.run(); }
        catch (SecurityException expected) { passed++; return; }
        throw new AssertionError("Unsafe installation plan was accepted");
    }

    static byte[] alternateJar() throws Exception {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        try (ZipOutputStream zip = new ZipOutputStream(output)) {
            zip.putNextEntry(new ZipEntry("fabric.mod.json"));
            zip.write(("{\"id\":\"hype_pokedex\",\"version\":\"" +
                RealPokedexOfflineTest.VERSION + "\"}").getBytes(StandardCharsets.UTF_8));
            zip.closeEntry();
            zip.putNextEntry(new ZipEntry("some/Other.class"));
            zip.write(new byte[2000]);
            zip.closeEntry();
        }
        return output.toByteArray();
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 1) throw new IllegalArgumentException("Path to protected beta 8 JAR required");
        Path privateJar = Path.of(args[0]);
        byte[] realJar = Files.readAllBytes(privateJar);
        check(RealPokedexOfflineTest.SHA.equals(RealPokedexOfflineTest.hash(realJar)),
              "Exact protected candidate required");
        KeyPair signer = KeyPairGenerator.getInstance("Ed25519").generateKeyPair();
        String url = PrivateModUpdater.API + "/mods/hype_pokedex/" +
                     RealPokedexOfflineTest.SHA + ".jar";
        String manifest = RealPokedexOfflineTest.signed(signer, url, realJar.length);
        var release = new PrivateModUpdater.Release(
            RealPokedexOfflineTest.ID, RealPokedexOfflineTest.VERSION,
            RealPokedexOfflineTest.SHA, realJar.length, 1, url, manifest);
        Path game = Files.createTempDirectory("hype-install-plan-test-");
        Path staging = Files.createDirectory(game.resolve(".hype-private-staging"));
        Files.write(staging.resolve(release.id() + "-" + release.sha256() + ".jar"), realJar);
        var first = PrivateInstallPlanner.inspect(game, release, signer.getPublic());
        check(first.action() == PrivateInstallPlanner.Action.READY_FOR_FIRST_INSTALL,
              "Absent mods/ means first-install candidate");
        check(!Files.exists(game.resolve("mods")), "Planner does not create mods directory");
        Path mods = Files.createDirectory(game.resolve("mods"));
        check(PrivateInstallPlanner.inspect(game, release, signer.getPublic()).action() ==
              PrivateInstallPlanner.Action.READY_FOR_FIRST_INSTALL, "Empty mods directory is safe");
        Path userJar = mods.resolve("my-pokedex.jar");
        Files.write(userJar, realJar);
        check(PrivateInstallPlanner.inspect(game, release, signer.getPublic()).action() ==
              PrivateInstallPlanner.Action.ALREADY_INSTALLED, "Exact already installed SHA detected");
        check(Files.readAllBytes(userJar).length == realJar.length, "Existing file untouched");
        Files.write(userJar, alternateJar());
        check(PrivateInstallPlanner.inspect(game, release, signer.getPublic()).action() ==
              PrivateInstallPlanner.Action.CONFLICT, "Different same-ID JAR cannot be overwritten");
        Files.write(mods.resolve("second-pokedex.jar"), alternateJar());
        check(PrivateInstallPlanner.inspect(game, release, signer.getPublic()).action() ==
              PrivateInstallPlanner.Action.CONFLICT, "Two copies of same mod denied");
        check(Files.size(userJar) == Files.size(mods.resolve("second-pokedex.jar")),
              "No files edited while planning");
        var untrusted = new PrivateModUpdater.Release(release.id(), release.version(),
                          release.sha256(), release.size(), 1, url,
                          manifest.replace("channel=stable", "channel=beta"));
        rejects(() -> PrivateInstallPlanner.inspect(game, untrusted, signer.getPublic()));
        Files.delete(mods.resolve("second-pokedex.jar"));
        Files.delete(userJar);
        Path staged = staging.resolve(release.id() + "-" + release.sha256() + ".jar");
        Files.delete(staged);
        Files.write(staged, alternateJar());
        rejects(() -> PrivateInstallPlanner.inspect(game, release, signer.getPublic()));
        Files.delete(staged);
        try {
            Files.createSymbolicLink(staged, privateJar.toAbsolutePath());
            rejects(() -> PrivateInstallPlanner.inspect(game, release, signer.getPublic()));
        } catch (UnsupportedOperationException ignored) {
            // Some local systems disable symlinks.
        }
        System.out.println("PASS: " + passed +
            " private install planner checks. No installs or production network.");
    }
}
