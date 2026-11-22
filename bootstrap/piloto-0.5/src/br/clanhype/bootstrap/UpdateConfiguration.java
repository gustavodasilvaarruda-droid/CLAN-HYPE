package br.clanhype.bootstrap;

import java.io.ByteArrayInputStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.util.Properties;
import java.util.Set;

/** Explicit local pilot config; never trusts a URL or an unverified manifest. */
public final class UpdateConfiguration {
    private static final long MAX_BYTES = 16_384;
    private static final Set<String> ALLOWED_KEYS = Set.of("update_mode");
    private UpdateConfiguration() { }

    public static UpdateMode load(Path gameDirectory) throws Exception {
        Path base = gameDirectory.toAbsolutePath().normalize();
        Path configDir = base.resolve("config");
        if (Files.isSymbolicLink(base) || Files.isSymbolicLink(configDir)) {
            throw new SecurityException("Symbolic link in configuration path");
        }
        Path file = configDir.resolve("hype-bootstrap.properties");
        if (!Files.exists(file, LinkOption.NOFOLLOW_LINKS)) {
            return UpdateMode.OFF;
        }
        if (!Files.isRegularFile(file, LinkOption.NOFOLLOW_LINKS) || Files.isSymbolicLink(file)) {
            throw new SecurityException("Invalid HYPE configuration file");
        }
        if (Files.size(file) > MAX_BYTES) {
            throw new SecurityException("Oversized HYPE configuration file");
        }
        byte[] bytes = Files.readAllBytes(file);
        if (bytes.length > MAX_BYTES) {
            throw new SecurityException("Oversized HYPE configuration file");
        }
        Properties properties = new Properties();
        properties.load(new ByteArrayInputStream(bytes));
        for (String name : properties.stringPropertyNames()) {
            if (!ALLOWED_KEYS.contains(name)) {
                throw new IllegalArgumentException("Unknown HYPE configuration key: " + name);
            }
        }
        return UpdateMode.parse(properties.getProperty("update_mode", "off"));
    }
}
