package br.clanhype.bootstrap;

import java.nio.file.Path;

/** Adapts the signed 0.4 downloader to explicit pilot modes. */
public final class UpdateCoordinator {
    private UpdateCoordinator() { }

    public static void runOnGameStart(Path gameDir) throws Exception {
        UpdateMode mode = UpdateConfiguration.load(gameDir);
        switch (mode) {
            case OFF -> System.out.println("[HYPE Bootstrap 0.5] Updates disabled (pilot default).");
            case STAGE -> {
                StageDownloader.Result result = StageDownloader.stageOnline(gameDir);
                System.out.printf("[HYPE Bootstrap 0.5] Stage only: downloaded=%d, unchanged=%d, required=%d%n",
                    result.downloaded(), result.unchanged(), result.required());
            }
            case AFTER_EXIT -> {
                AfterExitPilot.prepareAndLaunch(gameDir);
                System.out.println("[HYPE Bootstrap 0.5] After-exit pilot prepared (if changed).");
            }
        }
    }
}
