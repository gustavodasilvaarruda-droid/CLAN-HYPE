package br.clanhype.bootstrap;

import java.nio.file.Files;
import java.nio.file.Path;

public final class UpdateConfigurationTest {
    private static int passed;
    private static void expect(boolean okay, String message) {
        if (!okay) throw new AssertionError(message);
        passed++;
    }
    private static void mustReject(Path home, String contents) throws Exception {
        Files.writeString(home.resolve("config/hype-bootstrap.properties"), contents);
        try {
            UpdateConfiguration.load(home);
            throw new AssertionError("Rejected value accepted");
        } catch (IllegalArgumentException | SecurityException expected) {
            passed++;
        }
    }
    public static void main(String[] args) throws Exception {
        Path home = Files.createTempDirectory("hype-pilot-test-");
        expect(UpdateConfiguration.load(home) == UpdateMode.OFF, "no configuration is off");
        Files.createDirectories(home.resolve("config"));
        Path file = home.resolve("config/hype-bootstrap.properties");
        Files.writeString(file, "update_mode=off\n");
        expect(UpdateConfiguration.load(home) == UpdateMode.OFF, "off");
        Files.writeString(file, "update_mode=stage\n");
        expect(UpdateConfiguration.load(home) == UpdateMode.STAGE, "stage");
        Files.writeString(file, "update_mode=after_exit\n");
        expect(UpdateConfiguration.load(home) == UpdateMode.AFTER_EXIT, "after exit");
        mustReject(home, "update_mode=unknown\n");
        mustReject(home, "update_mode=off\ncustom_url=https://example.org/\n");
        Files.writeString(file, "x".repeat(16385));
        try {
            UpdateConfiguration.load(home);
            throw new AssertionError("oversized file accepted");
        } catch (SecurityException expected) { passed++; }
        Files.delete(file);
        Path elsewhere = Files.createTempFile("hype-config-test-", ".properties");
        Files.writeString(elsewhere, "update_mode=after_exit\n");
        try {
            Files.createSymbolicLink(file, elsewhere);
            try {
                UpdateConfiguration.load(home);
                throw new AssertionError("symlink accepted");
            } catch (SecurityException expected) { passed++; }
        } catch (UnsupportedOperationException | java.nio.file.FileSystemException unsupported) {
            System.out.println("Symlinks unsupported on test volume");
        }
        System.out.println("HYPE 0.5 local config tests: " + passed + " passed");
    }
}
