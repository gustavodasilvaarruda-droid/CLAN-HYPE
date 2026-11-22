package br.clanhype.bootstrap;

public enum UpdateMode {
    OFF, STAGE, AFTER_EXIT;

    public static UpdateMode parse(String value) {
        return switch (value.trim().toLowerCase(java.util.Locale.ROOT)) {
            case "off" -> OFF;
            case "stage" -> STAGE;
            case "after_exit" -> AFTER_EXIT;
            default -> throw new IllegalArgumentException("Unsupported update_mode: " + value);
        };
    }
}
