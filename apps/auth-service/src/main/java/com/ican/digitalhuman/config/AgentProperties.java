package com.ican.digitalhuman.config;

import java.time.Duration;
import java.util.Locale;
import java.util.Set;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.ConstructorBinding;

@ConfigurationProperties(prefix = "agent")
public record AgentProperties(
        String baseUrl,
        String internalToken,
        Duration connectTimeout,
        Duration readTimeout,
        String realtimePath,
        int realtimeMaxQueueBytes,
        int realtimeSendTimeLimitMs,
        int realtimeBufferSizeBytes,
        int realtimeMaxConnections,
        String environment
) {
    private static final String DEFAULT_INTERNAL_TOKEN = "dev-internal-token";
    private static final int PRODUCTION_TOKEN_MIN_LENGTH = 32;
    private static final Set<String> PRODUCTION_TOKEN_PLACEHOLDERS = Set.of(
            DEFAULT_INTERNAL_TOKEN,
            "replace-with-a-long-random-token",
            "replace-with-a-different-long-random-token");

    @ConstructorBinding
    public AgentProperties {
        baseUrl = baseUrl == null || baseUrl.isBlank() ? "http://localhost:8000" : baseUrl;
        internalToken = internalToken == null ? DEFAULT_INTERNAL_TOKEN : internalToken.trim();
        connectTimeout = connectTimeout == null ? Duration.ofSeconds(3) : connectTimeout;
        readTimeout = readTimeout == null ? Duration.ofSeconds(45) : readTimeout;
        realtimePath = realtimePath == null || realtimePath.isBlank() ? "/internal/realtime" : realtimePath;
        realtimeMaxQueueBytes = positive(realtimeMaxQueueBytes, 256 * 1024);
        realtimeSendTimeLimitMs = positive(realtimeSendTimeLimitMs, 10_000);
        realtimeBufferSizeBytes = positive(realtimeBufferSizeBytes, 512 * 1024);
        realtimeMaxConnections = positive(realtimeMaxConnections, 256);
        environment = environment == null || environment.isBlank() ? "development" : environment.trim();
        if (isProduction(environment) && unsafeProductionToken(internalToken)) {
            throw new IllegalArgumentException("agent.internal-token must be replaced in production");
        }
    }

    public AgentProperties(String baseUrl, String internalToken, Duration connectTimeout, Duration readTimeout) {
        this(baseUrl, internalToken, connectTimeout, readTimeout, "/internal/realtime", 256 * 1024, 10_000, 512 * 1024, 256);
    }

    public AgentProperties(
            String baseUrl,
            String internalToken,
            Duration connectTimeout,
            Duration readTimeout,
            String realtimePath,
            int realtimeMaxQueueBytes,
            int realtimeSendTimeLimitMs,
            int realtimeBufferSizeBytes,
            int realtimeMaxConnections) {
        this(
                baseUrl,
                internalToken,
                connectTimeout,
                readTimeout,
                realtimePath,
                realtimeMaxQueueBytes,
                realtimeSendTimeLimitMs,
                realtimeBufferSizeBytes,
                realtimeMaxConnections,
                "development");
    }

    private static boolean isProduction(String environment) {
        String normalized = environment.strip().toLowerCase(Locale.ROOT);
        return normalized.equals("prod") || normalized.equals("production");
    }

    private static boolean unsafeProductionToken(String token) {
        String normalized = token == null ? "" : token.strip().toLowerCase(Locale.ROOT);
        return normalized.isBlank()
                || PRODUCTION_TOKEN_PLACEHOLDERS.contains(normalized)
                || normalized.length() < PRODUCTION_TOKEN_MIN_LENGTH;
    }

    private static int positive(int value, int fallback) {
        return value > 0 ? value : fallback;
    }
}
