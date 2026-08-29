package com.ican.digitalhuman.config;

import java.time.Duration;
import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "agent")
public record AgentProperties(
        String baseUrl,
        String internalToken,
        Duration connectTimeout,
        Duration readTimeout
) {
    public AgentProperties {
        baseUrl = baseUrl == null || baseUrl.isBlank() ? "http://localhost:8000" : baseUrl;
        internalToken = internalToken == null ? "dev-internal-token" : internalToken;
        connectTimeout = connectTimeout == null ? Duration.ofSeconds(3) : connectTimeout;
        readTimeout = readTimeout == null ? Duration.ofSeconds(45) : readTimeout;
    }
}
