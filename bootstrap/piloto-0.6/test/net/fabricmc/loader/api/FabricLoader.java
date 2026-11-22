package net.fabricmc.loader.api;
import java.nio.file.Path;

/** Isolated OFF-mode test stand-in; never shipped in a Fabric mod. */
public final class FabricLoader {
    private static final FabricLoader INSTANCE = new FabricLoader();
    public static Path gameDir;
    public static FabricLoader getInstance() { return INSTANCE; }
    public Path getGameDir() { return gameDir; }
}
